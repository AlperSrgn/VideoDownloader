import logging
import os
import subprocess
import threading

import yt_dlp

from utils import (
    get_ffmpeg_path,
    sanitize_filename,
    unique_filename,
    update_file_timestamp,
    find_glob_file,
)

logger = logging.getLogger(__name__)

RESOLUTION_MAP = {
    "720p": 720,
    "1080p": 1080,
    "2K": 1440,
    "4K": 2160,
}

CLIENT_LIST = ["android", "web", "ios", "tv", "web_mobile"]

# Shared cancel flag — set to True from UI to abort an active download
cancel_download = False


# ---------------------------------------------------------------------------
# Format selection
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
# Progress hook
# ---------------------------------------------------------------------------

def make_progress_hook(on_progress, on_cancel_check, lang):
    """
    Returns a yt-dlp progress hook that calls on_progress(percent, downloaded_mb,
    total_mb, eta) and raises if cancel is requested.
    """
    def hook(d):
        if on_cancel_check():
            raise Exception(lang["download_canceled_message"])

        if d["status"] == "downloading":
            try:
                percent = float(d["_percent_str"].strip("%"))
                downloaded_mb = d.get("downloaded_bytes", 0) / (1024 * 1024)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                total_mb = total / (1024 * 1024)
                eta = d.get("_eta_str", "--:--")
                on_progress(percent, downloaded_mb, total_mb, eta)
            except Exception as e:
                logger.debug("Progress hook parse error: %s", e)

    return hook


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
        video_info = None
        selected_client = None
        video_format = None
        audio_format = None

        # Try each client until one returns accessible URLs
        for client in CLIENT_LIST:
            try:
                logger.debug("Trying client: %s", client)
                with yt_dlp.YoutubeDL({"quiet": True, "player_client": client}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    v_fmt, a_fmt = find_suitable_format(info.get("formats", []), video_height)
                    if v_fmt and a_fmt:
                        video_info = info
                        selected_client = client
                        video_format = v_fmt
                        audio_format = a_fmt
                        break
                    else:
                        logger.debug("Client %s: no compatible format or SABR protected.", client)
            except Exception as e:
                logger.debug("Client %s raised an error: %s", client, e)

        if not video_info:
            on_error(lang["download_video_format_error"])
            return

        title = video_info.get("title", "video")
        safe_title = sanitize_filename(title)
        base = os.path.join(save_location, safe_title)

        progress_hook = make_progress_hook(on_progress, on_cancel_check, lang)

        common_opts = {
            "quiet": True,
            "progress_hooks": [progress_hook],
            "player_client": selected_client,
        }

        try:
            with yt_dlp.YoutubeDL({**common_opts, "format": video_format["format_id"],
                                    "outtmpl": f"{base}_(Video).%(ext)s"}) as ydl:
                ydl.download([url])

            with yt_dlp.YoutubeDL({**common_opts, "format": audio_format["format_id"],
                                    "outtmpl": f"{base}_(Audio).%(ext)s"}) as ydl:
                ydl.download([url])
        except Exception as e:
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
                creationflags=subprocess.CREATE_NO_WINDOW,
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
        try:
            with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "audio")

            safe_title = sanitize_filename(title)
            output_filename = unique_filename(save_location, f"{safe_title}.mp3")
            output_path = os.path.join(save_location, output_filename)

            progress_hook = make_progress_hook(on_progress, on_cancel_check, lang)

            ydl_opts = {
                "format": "bestaudio",
                "outtmpl": output_path,
                "progress_hooks": [progress_hook],
                "quiet": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            update_file_timestamp(output_path)
            on_done()

        except Exception as e:
            on_error(str(e))

    threading.Thread(target=worker, daemon=True).start()
