import logging
import os
import re
import subprocess
import threading
import queue
import uuid

from settings import get_appdata_path
from utils import (
    get_ffmpeg_path,
    sanitize_filename,
    unique_filename,
    update_file_timestamp,
    find_glob_file,
)
from ytdlp_manager import (
    ensure_ytdlp,
    extract_info,
    find_info_with_compatible_format,
    CLIENT_LIST,
)

logger = logging.getLogger(__name__)

RESOLUTION_MAP = {
    "720p": 720,
    "1080p": 1080,
    "2K": 1440,
    "4K": 2160,
}

# Fixed weights (must sum to 100) for combining the three sub-phases of a
# video download — video download, audio download, ffmpeg merge — into a
# single overall percentage, so the UI can drive one progress bar across
# all three instead of resetting it to 0 at the start of each phase.

VIDEO_PHASE_WEIGHT = 75
AUDIO_PHASE_WEIGHT = 15
MERGE_PHASE_WEIGHT = 10

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# Shared cancel flag — set to True from UI to abort an active download
cancel_download = False


class DownloadCancelled(Exception):
    pass


# ---------------------------------------------------------------------------
# Format selection (unchanged — operates on the same 'formats' list shape
# that yt-dlp's --dump-json output produces)
# ---------------------------------------------------------------------------

def find_suitable_format(formats: list, video_height: int):
    """
    Return (video_format, audio_format) for the best available resolution
    at or below video_height. Returns (None, None) if SABR-protected or unavailable.
    """
    video_formats = [
        f for f in formats
        if f.get("url") and f.get("vcodec") != "none" and f.get("height") is not None
    ]
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]

    if not video_formats or not audio_formats:
        return None, None

    available_heights = sorted(
        {f["height"] for f in video_formats if f["height"] <= video_height},
        reverse=True
    )
    if not available_heights:
        available_heights = sorted({f["height"] for f in video_formats}, reverse=True)

    for h in available_heights:
        candidates = [f for f in video_formats if f.get("height") == h]
        if not candidates:
            continue

        chosen_video = max(candidates, key=lambda x: x.get("tbr") or 0)
        chosen_audio = max(audio_formats, key=lambda x: x.get("abr") or 0)

        if chosen_video.get("url") and chosen_audio.get("url"):
            logger.debug(
                "Compatible formats found — Video: %s (%dp), Audio: %s",
                chosen_video["format_id"], h, chosen_audio["format_id"]
            )
            return chosen_video, chosen_audio
        else:
            logger.debug(
                "SABR protection detected for %s (%dp)", chosen_video["format_id"], h
            )
            return None, None

    return None, None


# ---------------------------------------------------------------------------
# Progress parsing (replaces yt_dlp's progress_hooks — we now read yt-dlp
# CLI's --newline stdout output directly)
# ---------------------------------------------------------------------------

# Matches lines like:
# "[download]  45.2% of   10.00MiB at    1.20MiB/s ETA 00:05"
_PROGRESS_RE = re.compile(
    r"\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+)(B|KiB|MiB|GiB)"
    r"(?:\s+at\s+(\S+))?"
    r"(?:\s+ETA\s+(\S+))?"
)

_UNIT_TO_MB = {"B": 1 / (1024 * 1024), "KiB": 1 / 1024, "MiB": 1, "GiB": 1024}


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


def _run_download(cmd, on_progress, on_cancel_check, cancel_message):
    """
    Run a yt-dlp.exe download command, streaming its --newline progress
    output into on_progress, and killing it if on_cancel_check() becomes
    True mid-download.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )

    try:
        for line in process.stdout:
            if on_cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise DownloadCancelled(cancel_message)

            parsed = _parse_progress_line(line)
            if parsed:
                on_progress(*parsed)
    finally:
        if process.stdout:
            process.stdout.close()

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp exited with code {process.returncode}")


# ---------------------------------------------------------------------------
# FFmpeg merge progress parsing + cancellation
# ---------------------------------------------------------------------------
# ffmpeg is run with `-progress pipe:1`, which makes it print machine-
# readable "key=value" lines to stdout as it works (one full batch per
# update, terminated by a "progress=continue"/"progress=end" line) instead
# of the human-oriented stats it normally writes to stderr. We read that
# stream the same way _run_download reads yt-dlp's --newline output: line
# by line, checking on_cancel_check() as we go.

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


# How often we re-check on_cancel_check() while waiting for ffmpeg's next
# stdout line. This is a *ceiling* on cancel latency, not the normal case —
# lines from `-progress pipe:1` normally arrive faster than this on their
# own, so in practice cancellation reacts to whichever comes first: a new
# line, or this timeout. That means even if ffmpeg were to stall and stop
# producing output entirely (stuck I/O, etc.), cancellation still can't be
# blocked for more than this long.
_CANCEL_POLL_INTERVAL = 0.2  # seconds


def _enqueue_lines(pipe, line_queue):
    """Runs in a background thread: pushes each line from `pipe` onto
    `line_queue`, then pushes None as an end-of-stream sentinel. This is
    what lets the main loop use queue.get(timeout=...) — a blocking
    pipe.readline() has no timeout on its own, and on Windows, pipes can't
    be used with select()."""
    try:
        for line in pipe:
            line_queue.put(line)
    finally:
        line_queue.put(None)


def _run_ffmpeg_merge(cmd, total_duration, on_merge_progress, on_cancel_check, cancel_message):
    """
    Run the ffmpeg merge command, parsing its `-progress pipe:1` output to
    report merge progress via on_merge_progress(percent, elapsed_seconds,
    total_seconds, eta) — a distinct callback from on_progress, since merge
    progress is measured in seconds-of-media-processed, not downloaded MB,
    and reusing on_progress's (percent, downloaded_mb, total_mb, eta) shape
    would mislabel seconds as megabytes in the UI.

    If on_merge_progress is None, progress simply isn't reported, but
    cancellation still works the same way as during download.

    total_duration is the video's total length in seconds (e.g. from
    yt-dlp's info.get("duration")). If it's falsy, percent is always
    reported as 0 — callers should treat that as an indeterminate
    "merging..." state rather than a real percentage.

    Cancellation is checked both when a new stdout line arrives AND on a
    fixed timeout (_CANCEL_POLL_INTERVAL) even if no line arrives — so a
    stalled/silent ffmpeg process can't block cancellation indefinitely.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )

    line_queue = queue.Queue()
    reader_thread = threading.Thread(
        target=_enqueue_lines, args=(process.stdout, line_queue), daemon=True
    )
    reader_thread.start()

    elapsed_seconds = 0.0
    speed = None

    try:
        while True:
            if on_cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise DownloadCancelled(cancel_message)

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
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with code {process.returncode}")


# ---------------------------------------------------------------------------
# Video download (with merge)
# ---------------------------------------------------------------------------

def download_video(
    url: str,
    save_location: str,
    target_resolution: str,
    on_progress,
    on_cancel_check,
    on_done,
    on_error,
    lang: dict,
    on_merge_progress=None,
) -> None:
    """
    Download video+audio separately and merge with ffmpeg.
    Runs in a background thread. Calls on_done() or on_error(msg) when finished.

    on_merge_progress(percent, elapsed_seconds, total_seconds, eta), if
    given, is called during the ffmpeg merge step — separate from
    on_progress since merge progress is time-based (seconds of media
    processed), not MB-based like the download progress is.
    """
    def worker():
        if target_resolution not in RESOLUTION_MAP:
            on_error(f"Invalid resolution: {target_resolution}")
            return

        video_height = RESOLUTION_MAP[target_resolution]
        exe_path = ensure_ytdlp(get_appdata_path())

        def selector(formats):
            return find_suitable_format(formats, video_height)

        info, client, (video_format, audio_format) = find_info_with_compatible_format(
            exe_path, url, selector
        )

        if not info:
            on_error(lang["download_video_format_error"])
            return

        logger.info(
            "Selected client=%s video_format=%s (vcodec=%s, tbr=%s) "
            "audio_format=%s (acodec=%s, abr=%s)",
            client,
            video_format.get("format_id"), video_format.get("vcodec"), video_format.get("tbr"),
            audio_format.get("format_id"), audio_format.get("acodec"), audio_format.get("abr"),
        )

        title = info.get("title", "video")
        safe_title = sanitize_filename(title)

        # Temp files use a per-download UUID rather than safe_title. This
        # guarantees uniqueness even if the same video is queued/downloaded
        # more than once, and it means find_glob_file's pattern can only
        # ever match *this* download's own temp file — never a stale
        # leftover from a previous failed run.
        temp_id = uuid.uuid4().hex
        temp_base = os.path.join(save_location, f".ytdlp_tmp_{temp_id}")

        video_cmd = [
            exe_path,
            "-f", video_format["format_id"],
            "--extractor-args", f"youtube:player_client={client}",
            "--newline", "--no-warnings",
            "-o", f"{temp_base}_video.%(ext)s",
            url,
        ]
        audio_cmd = [
            exe_path,
            "-f", audio_format["format_id"],
            "--extractor-args", f"youtube:player_client={client}",
            "--newline", "--no-warnings",
            "-o", f"{temp_base}_audio.%(ext)s",
            url,
        ]

        # Rescale each phase's own 0-100 progress into its slice of the
        # overall bar (see *_PHASE_WEIGHT above), so on_progress/
        # on_merge_progress — and therefore the UI's single progress bar —
        # always reflect the whole video+audio+merge job, not just whichever
        # sub-step happens to be running. downloaded_mb/total_mb/eta are
        # passed through unchanged since those are still meaningful as
        # "this phase's own numbers."
        def _video_phase_progress(percent, downloaded_mb, total_mb, eta):
            on_progress(VIDEO_PHASE_WEIGHT * (percent / 100), downloaded_mb, total_mb, eta)

        def _audio_phase_progress(percent, downloaded_mb, total_mb, eta):
            overall = VIDEO_PHASE_WEIGHT + AUDIO_PHASE_WEIGHT * (percent / 100)
            on_progress(overall, downloaded_mb, total_mb, eta)

        try:
            _run_download(video_cmd, _video_phase_progress, on_cancel_check, lang["download_canceled_message"])
            _run_download(audio_cmd, _audio_phase_progress, on_cancel_check, lang["download_canceled_message"])
        except (DownloadCancelled, RuntimeError) as e:
            on_error(str(e))
            return

        # Locate downloaded temp files
        try:
            video_path = find_glob_file(f"{temp_base}_video.*")
            audio_path = find_glob_file(f"{temp_base}_audio.*")
        except FileNotFoundError as e:
            on_error(str(e))
            return

        output_filename = unique_filename(save_location, f"{safe_title}.mp4")
        output_path = os.path.join(save_location, output_filename)

        ffmpeg_cmd = [
            get_ffmpeg_path(), "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-progress", "pipe:1",
            "-nostats",
            output_path,
        ]

        def _merge_phase_progress(percent, elapsed_seconds, total_seconds, eta):
            overall = VIDEO_PHASE_WEIGHT + AUDIO_PHASE_WEIGHT + MERGE_PHASE_WEIGHT * (percent / 100)
            on_merge_progress(overall, elapsed_seconds, total_seconds, eta)

        try:
            _run_ffmpeg_merge(
                ffmpeg_cmd,
                info.get("duration"),
                _merge_phase_progress if on_merge_progress else None,
                on_cancel_check,
                lang["download_canceled_message"],
            )
        except DownloadCancelled as e:
            # ffmpeg was killed mid-merge — output_path may contain a
            # partially-written, unplayable file. Remove it so it doesn't
            # look like a completed download.
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            on_error(str(e))
            return
        except RuntimeError as e:
            on_error(f"FFmpeg merge failed ({e}). "
                     "The downloaded temp files were kept for inspection.")
            return
        finally:
            # Always clean up the video/audio temp files, regardless of
            # whether the merge succeeded, failed, or was cancelled — we
            # don't keep them around for inspection.
            for path in [video_path, audio_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

        logger.debug("Download completed: %s", output_path)
        on_done()

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Audio-only download
# ---------------------------------------------------------------------------

def download_audio(
    url: str,
    save_location: str,
    on_progress,
    on_cancel_check,
    on_done,
    on_error,
    lang: dict,
) -> None:
    """Download audio only as mp3. Runs in a background thread."""
    def worker():
        exe_path = ensure_ytdlp(get_appdata_path())

        info = None
        for client in CLIENT_LIST:
            try:
                info = extract_info(exe_path, url, client)
                break
            except Exception as e:
                logger.debug("Client %s failed: %s", client, e)

        if not info:
            on_error(lang["download_video_format_error"])
            return

        title = info.get("title", "audio")
        safe_title = sanitize_filename(title)
        output_filename = unique_filename(save_location, f"{safe_title}.mp3")
        output_path = os.path.join(save_location, output_filename)

        # Same reasoning as download_video: use a per-download UUID for the
        # temp download template so find_glob_file can't accidentally match
        # a pre-existing file (e.g. an older download with the same title)
        # that happens to already sit in save_location.
        temp_id = uuid.uuid4().hex
        output_template = os.path.join(save_location, f".ytdlp_tmp_{temp_id}")

        cmd = [
            exe_path,
            "-f", "bestaudio",
            "-x", "--audio-format", "mp3",
            "--ffmpeg-location", get_ffmpeg_path(),
            "--newline", "--no-warnings",
            "-o", f"{output_template}.%(ext)s",
            url,
        ]

        try:
            _run_download(cmd, on_progress, on_cancel_check, lang["download_canceled_message"])
        except (DownloadCancelled, RuntimeError) as e:
            on_error(str(e))
            return

        try:
            final_path = find_glob_file(f"{output_template}.mp3")
        except FileNotFoundError as e:
            on_error(str(e))
            return

        if os.path.abspath(final_path) != os.path.abspath(output_path):
            os.replace(final_path, output_path)

        update_file_timestamp(output_path)
        on_done()

    threading.Thread(target=worker, daemon=True).start()