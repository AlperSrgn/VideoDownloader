import logging
import os
import re
import subprocess
import threading
import queue
import uuid
from collections import deque

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
    find_info_with_compatible_format,
)
from error_classifier import (
    DownloadCancelled,
    YtDlpProcessError,
    FfmpegProcessError,
    classify_ytdlp_error,
    classify_ffmpeg_error,
    classify_extraction_failure,
    classify_generic_exception,
)

logger = logging.getLogger(__name__)

RESOLUTION_MAP = {
    "720p": 720,
    "1080p": 1080,
    "2K": 1440,
    "4K": 2160,
}

# Fixed weights combine video download, audio download,
# and ffmpeg merge into one progress bar.
# Previously, weights were calculated dynamically from file sizes.
# However, some DASH/adaptive formats don’t report a filesize, causing progress to get stuck at 0%,
# while fragmented downloads could make the total estimate fluctuate.
# Fixed weights make progress simpler and more stable, at the cost of not reflecting actual file-size ratios.
VIDEO_PHASE_WEIGHT = 75
AUDIO_PHASE_WEIGHT = 15
MERGE_PHASE_WEIGHT = 10


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# Shared cancel flag — set to True from UI to abort an active download
cancel_download = False


# ---------------------------------------------------------------------------
# Format selection (unchanged — operates on the same 'formats' list shape
# that yt-dlp's --dump-json output produces)
# ---------------------------------------------------------------------------

def _select_original_audio(audio_formats: list):
    """
    Selects the *original* audio track instead of an auto-dubbed one.

    yt-dlp tags audio formats with language and language_preference.
    The original track usually has the highest language_preference value.

    First, formats with the highest language_preference are selected;
    ties are then resolved by bitrate.
    """
    if not audio_formats:
        return None

    max_pref = max((f.get("language_preference") or -1) for f in audio_formats)
    original_candidates = [
        f for f in audio_formats
        if (f.get("language_preference") or -1) == max_pref
    ]
    chosen = max(original_candidates, key=lambda x: x.get("abr") or 0)

    logger.debug(
        "Original audio track selected: format=%s language=%s language_preference=%s abr=%s",
        chosen.get("format_id"), chosen.get("language"),
        chosen.get("language_preference"), chosen.get("abr"),
    )
    return chosen


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
        chosen_audio = _select_original_audio(audio_formats)

        if chosen_video.get("url") and chosen_audio and chosen_audio.get("url"):
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


def find_suitable_audio_format(formats: list):
    """
    Returns the original audio track as (audio_format,) so it can be passed
    directly to find_info_with_compatible_format.

    Returns (None,) if no usable audio track is available, allowing the next
    client to be tried.
    """
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    return (_select_original_audio(audio_formats),)


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
    Runs the yt-dlp.exe download, reports progress, and stops if cancelled.
    Cancellation is checked periodically even without output.
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

    line_queue = queue.Queue()
    reader_thread = threading.Thread(
        target=_enqueue_lines, args=(process.stdout, line_queue), daemon=True
    )
    reader_thread.start()

    # Keep the last N lines of yt-dlp's output to capture the actual
    # "ERROR: ..." message when it fails.
    # Limit the output to prevent unbounded memory usage.
    output_lines = deque(maxlen=200)

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
                break  # reader thread hit EOF — yt-dlp closed stdout

            output_lines.append(line)
            parsed = _parse_progress_line(line)
            if parsed:
                on_progress(*parsed)
    finally:
        if process.stdout:
            process.stdout.close()

    process.wait()
    if process.returncode != 0:
        raise YtDlpProcessError(process.returncode, "".join(output_lines))


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


# Determines how often cancellation is checked while ffmpeg is waiting.
# Cancellation won't be delayed beyond this interval, even without new output.
_CANCEL_POLL_INTERVAL = 0.2  # seconds


def _enqueue_lines(pipe, line_queue):
    """Runs in the background, pushing `pipe` lines to `line_queue` and adding
    None at the end. This allows the main loop to use a timeout; `readline()`
    has no timeout support, and Windows pipes can't be used with `select()`."""
    try:
        for line in pipe:
            line_queue.put(line)
    finally:
        line_queue.put(None)


def _run_ffmpeg_merge(cmd, total_duration, on_merge_progress, on_cancel_check, cancel_message):
    """
    Runs the ffmpeg merge and reports progress through on_merge_progress.
    Progress is based on media seconds rather than MB.

    If on_merge_progress is None, progress is not reported, but cancellation
    still works. If total_duration is unavailable, percent stays at 0.

    Cancellation is checked on stdout lines and at regular intervals.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
    # Since stdout and the process have ended, stderr is also closed.
    # This join prevents a possible race before reading stderr_lines.
    stderr_thread.join(timeout=2)
    if process.stderr:
        process.stderr.close()
    if process.returncode != 0:
        raise FfmpegProcessError(process.returncode, "".join(stderr_lines))


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
    Downloads video and audio separately, then merges them with ffmpeg.
    Calls on_done() or on_error(msg) when finished.
    Merge progress is reported based on processed seconds.
    """

    def worker():
        try:
            _worker_impl()
        except Exception as e:
            # Safety net: # Unexpected errors can stop the thread and leave the UI stuck.
            logger.exception("Unexpected error in download_video worker")
            on_error(classify_generic_exception(e, lang))

    def _worker_impl():
        if not os.path.exists(get_ffmpeg_path()):
            on_error(lang["ffmpeg_not_found_error"])
            return

        if target_resolution not in RESOLUTION_MAP:
            on_error(f"Invalid resolution: {target_resolution}")
            return

        video_height = RESOLUTION_MAP[target_resolution]
        exe_path = ensure_ytdlp(get_appdata_path())

        def selector(formats):
            return find_suitable_format(formats, video_height)

        extraction_errors = []
        info, client, (video_format, audio_format) = find_info_with_compatible_format(
            exe_path, url, selector, collected_errors=extraction_errors
        )

        if not info:
            on_error(classify_extraction_failure(
                extraction_errors, lang, fallback_key="download_video_format_error"
            ))
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

        # Temp files use a UUID, so even repeated downloads of the same video
        # only match the current download's file.
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

        # Scales each phase's progress by *_PHASE_WEIGHT for the overall bar.
        # downloaded_mb/total_mb/eta remain unchanged as phase-specific values.
        def _video_phase_progress(percent, downloaded_mb, total_mb, eta):
            on_progress(VIDEO_PHASE_WEIGHT * (percent / 100), downloaded_mb, total_mb, eta)

        def _audio_phase_progress(percent, downloaded_mb, total_mb, eta):
            overall = VIDEO_PHASE_WEIGHT + AUDIO_PHASE_WEIGHT * (percent / 100)
            on_progress(overall, downloaded_mb, total_mb, eta)

        try:
            _run_download(video_cmd, _video_phase_progress, on_cancel_check, lang["download_canceled_message"])
            _run_download(audio_cmd, _audio_phase_progress, on_cancel_check, lang["download_canceled_message"])
        except DownloadCancelled as e:
            on_error(str(e))
            return
        except YtDlpProcessError as e:
            on_error(classify_ytdlp_error(e.output, e.returncode, lang))
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
        except FfmpegProcessError as e:
            # Same reasoning as the cancellation branch above: ffmpeg may
            # have written a partial, unplayable file before erroring out.
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            on_error(classify_ffmpeg_error(e.output, e.returncode, lang))
            return
        finally:
            # Always clean up temporary video/audio files, regardless of merge result.
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
        try:
            _worker_impl()
        except Exception as e:
            logger.exception("Unexpected error in download_audio worker")
            on_error(classify_generic_exception(e, lang))

    def _worker_impl():
        if not os.path.exists(get_ffmpeg_path()):
            on_error(lang["ffmpeg_not_found_error"])
            return

        exe_path = ensure_ytdlp(get_appdata_path())

        def selector(formats):
            return find_suitable_audio_format(formats)

        extraction_errors = []
        info, client, (chosen_audio,) = find_info_with_compatible_format(
            exe_path, url, selector, collected_errors=extraction_errors
        )

        if not info or not chosen_audio:
            on_error(classify_extraction_failure(
                extraction_errors, lang, fallback_key="download_video_format_error"
            ))
            return

        logger.info(
            "Selected client=%s audio_format=%s (acodec=%s, abr=%s, language=%s)",
            client, chosen_audio.get("format_id"), chosen_audio.get("acodec"),
            chosen_audio.get("abr"), chosen_audio.get("language"),
        )

        title = info.get("title", "audio")
        safe_title = sanitize_filename(title)
        output_filename = unique_filename(save_location, f"{safe_title}.mp3")
        output_path = os.path.join(save_location, output_filename)

        # Same as download_video: use a UUID for the temp file so find_glob_file
        # doesn't accidentally match an old file.
        temp_id = uuid.uuid4().hex
        output_template = os.path.join(save_location, f".ytdlp_tmp_{temp_id}")

        cmd = [
            exe_path,
            "-f", chosen_audio["format_id"],
            "--extractor-args", f"youtube:player_client={client}",
            "-x", "--audio-format", "mp3",
            "--ffmpeg-location", get_ffmpeg_path(),
            "--newline", "--no-warnings",
            "-o", f"{output_template}.%(ext)s",
            url,
        ]

        try:
            _run_download(cmd, on_progress, on_cancel_check, lang["download_canceled_message"])
        except DownloadCancelled as e:
            on_error(str(e))
            return
        except YtDlpProcessError as e:
            on_error(classify_ytdlp_error(e.output, e.returncode, lang))
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