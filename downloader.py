import logging
import os
import re
import subprocess
import threading

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
) -> None:
    """
    Download video+audio separately and merge with ffmpeg.
    Runs in a background thread. Calls on_done() or on_error(msg) when finished.
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

        title = info.get("title", "video")
        safe_title = sanitize_filename(title)
        base = os.path.join(save_location, safe_title)

        video_cmd = [
            exe_path,
            "-f", video_format["format_id"],
            "--extractor-args", f"youtube:player_client={client}",
            "--newline", "--no-warnings",
            "-o", f"{base}_(Video).%(ext)s",
            url,
        ]
        audio_cmd = [
            exe_path,
            "-f", audio_format["format_id"],
            "--extractor-args", f"youtube:player_client={client}",
            "--newline", "--no-warnings",
            "-o", f"{base}_(Audio).%(ext)s",
            url,
        ]

        try:
            _run_download(video_cmd, on_progress, on_cancel_check, lang["download_canceled_message"])
            _run_download(audio_cmd, on_progress, on_cancel_check, lang["download_canceled_message"])
        except (DownloadCancelled, RuntimeError) as e:
            on_error(str(e))
            return

        # Locate downloaded temp files
        try:
            video_path = find_glob_file(f"{base}_(Video).*")
            audio_path = find_glob_file(f"{base}_(Audio).*")
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
            output_path,
        ]

        try:
            subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                creationflags=_NO_WINDOW,
            )
        except subprocess.CalledProcessError as e:
            on_error(f"FFmpeg merge failed (exit code {e.returncode}). "
                     "The downloaded temp files were kept for inspection.")
            return
        finally:
            # Clean up temp files only if merge succeeded
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
        output_template = os.path.join(save_location, safe_title)

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