"""Subprocess engine for downloads: runs yt-dlp and ffmpeg, parses their
progress output, and handles cancel / pause / stall detection.

Public API (used by downloader.py):
    known_size_mb, run_download, run_download_with_retry, run_ffmpeg_merge

run_download_with_retry() is what downloader.py calls for yt-dlp phases: it
adds the bounded HTTP 403 retry (and the final-failure diagnostics) on top of
run_download()'s pause/cancel/stall handling.
"""
import logging
import queue
import re
import subprocess
import threading
import time
from collections import deque

from system.process_manager import (
    NO_WINDOW,
    attach_to_job,
    apply_pause_state,
    enqueue_lines,
    resume_if_suspended,
    terminate_process_tree,
)
from core.error_classifier import (
    DownloadCancelled,
    DownloadStalled,
    YtDlpProcessError,
    FfmpegProcessError,
    is_http_403,
)

logger = logging.getLogger(__name__)

# If yt-dlp produces absolutely no output for this long, we treat it as
# stuck (e.g. an infinite loop while solving YouTube's nsig challenge for a
# specific video — CPU stays high while disk/network usage stays at zero)
# rather than waiting forever, and kill the process.
_STALL_TIMEOUT = 60  # seconds

# How often the yt-dlp download loop, the ffmpeg merge loop and the
# paused-wait loop re-check cancel/pause while no new output arrives.
# Cancellation won't be delayed beyond this interval.
_CANCEL_POLL_INTERVAL = 0.2  # seconds

# HTTP 403 from YouTube's servers is often transient (rate limiting after many
# requests in a row, an expired or rejected stream URL). Every run of a download
# command re-extracts the video, so a retry gets fresh URLs. Bounded on purpose:
# a persistent 403 (e.g. a format that needs a PO token) still fails quickly.
_RETRY_DELAYS_403 = (3, 8)   # seconds to wait before retry 1 and retry 2
_LOG_TAIL_LINES = 25


# ---------------------------------------------------------------------------
# Progress parsing (yt-dlp CLI's --newline stdout output)
# ---------------------------------------------------------------------------

# Matches lines like:
# "[download]  45.2% of   10.00MiB at    1.20MiB/s ETA 00:05"
_PROGRESS_RE = re.compile(
    r"\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+)(B|KiB|MiB|GiB)"
    r"(?:\s+at\s+(\S+))?"
    r"(?:\s+ETA\s+(\S+))?"
)

_UNIT_TO_MB = {"B": 1 / (1024 * 1024), "KiB": 1 / 1024, "MiB": 1, "GiB": 1024}


def known_size_mb(fmt: dict):
    """Real size (in MB) from yt-dlp's format metadata, if it has one.

    Prefers the exact 'filesize'; falls back to 'filesize_approx' (yt-dlp's
    own one-time estimate from bitrate * duration, which is stable — unlike
    the live per-fragment estimate --newline prints during the download).
    Returns None if neither is present (e.g. some DASH formats).
    """
    size_bytes = fmt.get("filesize") or fmt.get("filesize_approx")
    if not size_bytes:
        return None
    return size_bytes / (1024 * 1024)


def _parse_progress_line(line: str):
    """Return (percent, downloaded_mb, total_mb, eta) or None if not a progress line."""
    match = _PROGRESS_RE.search(line)
    if not match:
        return None

    percent = float(match.group(1))
    total_value = float(match.group(2))
    unit = match.group(3)
    eta = match.group(5) or "--:--"

    total_mb = total_value * _UNIT_TO_MB.get(unit, 1)
    downloaded_mb = total_mb * (percent / 100)
    return percent, downloaded_mb, total_mb, eta


# ---------------------------------------------------------------------------
# yt-dlp download (progress, cancel, pause/resume, stall detection)
# ---------------------------------------------------------------------------

class _PausedForResume(Exception):
    """Internal signal — never seen outside this module. Raised by
    _download_once when the user pauses mid-download; caught by
    run_download, which waits for resume and relaunches the exact same
    yt-dlp command so it continues the partial file instead of starting
    the download over (see run_download's docstring for why)."""


def _wait_while_paused(on_cancel_check, on_pause_check, cancel_message):
    """Blocks the calling (background) thread while paused. Still reacts
    to cancellation immediately, without waiting for a resume first."""
    while on_pause_check is not None and on_pause_check():
        if on_cancel_check():
            raise DownloadCancelled(cancel_message)
        time.sleep(_CANCEL_POLL_INTERVAL)


def run_download(cmd, on_progress, on_cancel_check, cancel_message, stall_message=None,
                 known_total_mb=None, on_pause_check=None):
    """
    Runs the yt-dlp.exe download, reports progress, and stops if cancelled.
    Cancellation is checked periodically even without output.

    known_total_mb: Pass the real file size when available to keep the total fixed.
    Without it, yt-dlp may re-estimate fragmented downloads on each fragment,
    causing the displayed total to jump. If unavailable, use a non-decreasing
    estimate so the total never shrinks due to estimation fluctuations.

    Also guards against yt-dlp getting stuck in a local infinite loop for a
    specific video (e.g. while solving YouTube's nsig challenge) — in that
    case yt-dlp never prints another line and never exits, so without this
    check the app would hang forever with no feedback. If no output is
    received for _STALL_TIMEOUT seconds, the process is killed and
    DownloadStalled is raised instead.

    on_pause_check: optional callable checked while downloading. An
    in-flight HTTP download can't be reliably frozen by just suspending
    the yt-dlp process — the OS network stack keeps receiving into the
    socket's buffer regardless of whether our thread gets scheduled, so a
    "paused" download can silently keep completing itself in the
    background. So instead, pausing
    stops the yt-dlp process — its partial file is left on disk — and
    blocks until resumed, then relaunches the exact same command; yt-dlp
    resumes the partial file itself via an HTTP Range request (its
    default behavior) instead of re-downloading from scratch.
    """
    while True:
        try:
            _download_once(
                cmd, on_progress, on_cancel_check, cancel_message,
                stall_message, known_total_mb, on_pause_check,
            )
            return
        except _PausedForResume:
            _wait_while_paused(on_cancel_check, on_pause_check, cancel_message)
            # Loop back around and relaunch cmd — yt-dlp continues the
            # partial file it already wrote rather than starting over.
            continue


def _download_once(cmd, on_progress, on_cancel_check, cancel_message, stall_message,
                   known_total_mb, on_pause_check):
    """Runs a single yt-dlp process end-to-end. Raises _PausedForResume if
    the user paused mid-download — see run_download, which wraps this."""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=NO_WINDOW,
    )
    attach_to_job(process)

    line_queue = queue.Queue()
    reader_thread = threading.Thread(
        target=enqueue_lines, args=(process.stdout, line_queue), daemon=True
    )
    reader_thread.start()

    # Keep the last N lines of yt-dlp's output to capture the actual
    # "ERROR: ..." message when it fails.
    # Limit the output to prevent unbounded memory usage.
    output_lines = deque(maxlen=200)
    last_output_time = time.monotonic()

    # Tracks the total size reported to on_progress. Starts with known_total_mb
    # if available; otherwise uses yt-dlp's estimate and only allows it to grow.
    # This prevents the displayed value from decreasing.
    stable_total_mb = known_total_mb

    # yt-dlp calculates the percentage using its fluctuating total size estimate for
    # fragmented formats, so small fluctuations may occur. We smooth out small
    # drops to prevent the downloaded size from appearing to move backwards.
    # We don't lock the percentage completely, since yt-dlp may initially report
    # an incorrectly high percentage. Large drops are treated as yt-dlp correcting
    # its estimate rather than as noise.
    max_percent_seen = 0.0
    _PERCENT_JITTER_TOLERANCE = 5.0  # percentage points

    try:
        while True:
            if on_cancel_check():
                terminate_process_tree(process)
                raise DownloadCancelled(cancel_message)

            if on_pause_check is not None and on_pause_check():
                # Stop the process (its partial file stays on disk) rather
                # than suspending it — see run_download's docstring for
                # why suspending alone doesn't actually pause an in-flight
                # HTTP download.
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise _PausedForResume()

            if time.monotonic() - last_output_time > _STALL_TIMEOUT:
                logger.warning(
                    "yt-dlp produced no output for %ss — treating as stalled "
                    "and killing the process. cmd=%s", _STALL_TIMEOUT, cmd,
                )
                terminate_process_tree(process)
                raise DownloadStalled(stall_message)

            try:
                line = line_queue.get(timeout=_CANCEL_POLL_INTERVAL)
            except queue.Empty:
                # No output in the last _CANCEL_POLL_INTERVAL seconds — loop
                # back around to the checks above rather than blocking
                # further.
                continue

            if line is None:
                break  # reader thread hit EOF — yt-dlp closed stdout

            last_output_time = time.monotonic()
            output_lines.append(line)
            parsed = _parse_progress_line(line)
            if parsed:
                percent, downloaded_mb, parsed_total_mb, eta = parsed

                # Absorb small dips (jitter) by holding at the highest value
                # seen so far; but a big drop means the earlier high reading
                # was itself the bad one (e.g. a wrong initial estimate), so
                # let the new, presumably-correct value through and reset the
                # ceiling to it.
                if percent >= max_percent_seen:
                    max_percent_seen = percent
                elif percent >= max_percent_seen - _PERCENT_JITTER_TOLERANCE:
                    percent = max_percent_seen
                else:
                    max_percent_seen = percent

                if known_total_mb is not None:
                    # We already trust the format's real filesize — ignore
                    # yt-dlp's per-fragment re-estimate entirely.
                    effective_total_mb = known_total_mb
                elif parsed_total_mb and (
                    stable_total_mb is None or parsed_total_mb > stable_total_mb
                ):
                    stable_total_mb = parsed_total_mb
                    effective_total_mb = stable_total_mb
                else:
                    effective_total_mb = stable_total_mb or parsed_total_mb

                if effective_total_mb:
                    downloaded_mb = effective_total_mb * (percent / 100)

                on_progress(percent, downloaded_mb, effective_total_mb, eta)
    finally:
        if process.stdout:
            process.stdout.close()

    process.wait()
    if process.returncode != 0:
        raise YtDlpProcessError(process.returncode, "".join(output_lines))


# ---------------------------------------------------------------------------
# HTTP 403 retry
# ---------------------------------------------------------------------------

def _output_tail(output: str, max_lines: int = _LOG_TAIL_LINES) -> str:
    """Last lines of yt-dlp's output for the log, without the progress lines."""
    lines = [l for l in output.splitlines() if l.strip() and "% of" not in l]
    return "\n".join("    | " + l for l in lines[-max_lines:]) or "    | (empty)"


def _wait_cancellable(seconds: float, on_cancel_check) -> bool:
    """Sleeps for `seconds`; returns False as soon as the user cancels."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if on_cancel_check():
            return False
        time.sleep(0.25)
    return not on_cancel_check()


def run_download_with_retry(cmd, on_progress, on_cancel_check, cancel_message,
                            stall_message=None, known_total_mb=None, on_pause_check=None):
    """run_download() plus the HTTP 403 retry policy; same arguments.

    A 403 (see core.error_classifier.is_http_403) is retried up to
    len(_RETRY_DELAYS_403) times after a short, cancellable pause. A failure
    that is final is logged with the command and the tail of yt-dlp's output,
    then re-raised.

    Raises DownloadCancelled (also when the user cancels during a retry
    pause), DownloadStalled, or YtDlpProcessError once retries are used up
    or the failure is not a 403.
    """
    retries_done = 0
    while True:
        try:
            run_download(
                cmd, on_progress, on_cancel_check, cancel_message, stall_message,
                known_total_mb=known_total_mb, on_pause_check=on_pause_check,
            )
            return
        except YtDlpProcessError as e:
            if is_http_403(e.output) and retries_done < len(_RETRY_DELAYS_403):
                delay = _RETRY_DELAYS_403[retries_done]
                retries_done += 1
                logger.warning(
                    "HTTP 403 during download; retry %d/%d in %ss",
                    retries_done, len(_RETRY_DELAYS_403), delay,
                )
                if not _wait_cancellable(delay, on_cancel_check):
                    raise DownloadCancelled(cancel_message)
                continue
            logger.warning(
                "yt-dlp download failed (exit=%s, 403 retries used: %d)\n  command: %s\n  output (tail):\n%s",
                e.returncode, retries_done, subprocess.list2cmdline(cmd), _output_tail(e.output),
            )
            raise


# ---------------------------------------------------------------------------
# FFmpeg merge progress + cancellation
# ---------------------------------------------------------------------------
# ffmpeg reports progress as "key=value" lines.
# We read each line to track progress and check for cancellation.

def _parse_ffmpeg_time(value: str):
    """Parse an ffmpeg HH:MM:SS(.ffffff) timestamp into seconds, or None."""
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _format_duration(seconds: float) -> str:
    """Format seconds as MM:SS, or H:MM:SS once it reaches an hour — matches
    the ETA style yt-dlp itself prints during downloads."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def run_ffmpeg_merge(cmd, total_duration, on_merge_progress, on_cancel_check, cancel_message,
                     on_pause_check=None):
    """
    Runs the ffmpeg merge and reports progress through on_merge_progress.
    Progress is based on media seconds rather than MB.

    If on_merge_progress is None, progress is not reported, but cancellation
    still works. If total_duration is unavailable, percent stays at 0.

    Cancellation is checked on stdout lines and at regular intervals.

    on_pause_check: optional callable — while it returns True, the ffmpeg
    process is suspended in place (see apply_pause_state). Unlike the
    yt-dlp download phase (which stops and relaunches yt-dlp — see
    run_download's docstring), no relaunch is needed here since ffmpeg
    is local CPU work with no network buffering.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=NO_WINDOW,
    )
    attach_to_job(process)

    line_queue = queue.Queue()
    reader_thread = threading.Thread(
        target=enqueue_lines, args=(process.stdout, line_queue), daemon=True
    )
    reader_thread.start()

    # ffmpeg's actual errors (codec, disk, permissions, etc.) go to stderr;
    # stdout is reserved for `-progress pipe:1` key=value lines.
    # Capture stderr on a separate thread for error classification.
    # Cancellation is already handled in the stdout loop.
    stderr_lines = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_lines.extend(process.stderr), daemon=True
    )
    stderr_thread.start()

    elapsed_seconds = 0.0
    speed = None
    suspended = False

    try:
        while True:
            if on_cancel_check():
                resume_if_suspended(process, suspended)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise DownloadCancelled(cancel_message)

            suspended = apply_pause_state(process, on_pause_check, suspended)
            if suspended:
                time.sleep(_CANCEL_POLL_INTERVAL)
                continue

            try:
                line = line_queue.get(timeout=_CANCEL_POLL_INTERVAL)
            except queue.Empty:
                # No output in the last _CANCEL_POLL_INTERVAL seconds — loop
                # back around to the on_cancel_check() at the top rather
                # than blocking further.
                continue

            if line is None:
                break  # reader thread hit EOF — ffmpeg closed stdout

            line = line.strip()

            if line.startswith("out_time="):
                parsed = _parse_ffmpeg_time(line[len("out_time="):])
                if parsed is not None:
                    elapsed_seconds = parsed

            elif line.startswith("speed="):
                raw = line[len("speed="):].strip().rstrip("x")
                try:
                    speed = float(raw)
                except ValueError:
                    speed = None

            elif line.startswith("progress="):
                # End of one stats batch ("continue" or "end") — report now
                # rather than on every individual key=value line.
                if on_merge_progress:
                    if total_duration:
                        percent = min(100.0, (elapsed_seconds / total_duration) * 100)
                        remaining = max(0.0, total_duration - elapsed_seconds)
                        eta = _format_duration(remaining / speed) if speed else "--:--"
                    else:
                        percent = 0.0
                        eta = "--:--"
                    on_merge_progress(percent, elapsed_seconds, total_duration or 0, eta)
    finally:
        if process.stdout:
            process.stdout.close()

    process.wait()
    # Since stdout and the process have ended, stderr is also closed.
    # This join prevents a possible race before reading stderr_lines.
    stderr_thread.join(timeout=2)
    if process.stderr:
        process.stderr.close()
    if process.returncode != 0:
        raise FfmpegProcessError(process.returncode, "".join(stderr_lines))