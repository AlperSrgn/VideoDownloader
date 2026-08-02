"""
Handles the standalone yt-dlp.exe binary instead of the `yt_dlp` Python
package. This lets the app pick up new yt-dlp releases (which happen often,
since YouTube keeps changing things) without needing to rebuild and
redistribute the whole application exe.

The binary is stored in the app's AppData folder and is downloaded on first
run, then asked to self-update on every subsequent launch.
"""

import json
import logging
import os
import subprocess
import urllib.request

logger = logging.getLogger(__name__)

YT_DLP_EXE_NAME = "yt-dlp.exe"
YT_DLP_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

# Player clients to try, in order, when extracting video info.
CLIENT_LIST = ["android", "web", "ios", "tv", "web_mobile"]

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class YtDlpError(Exception):
    """Raised when yt-dlp.exe cannot be run or returns no usable data."""


def _run_hidden(cmd, **kwargs):
    return subprocess.run(cmd, creationflags=_NO_WINDOW, **kwargs)


def get_ytdlp_path(appdata_dir: str) -> str:
    return os.path.join(appdata_dir, YT_DLP_EXE_NAME)


def download_ytdlp_exe(dest_path: str) -> None:
    """Download the latest yt-dlp.exe release from GitHub."""
    tmp_path = dest_path + ".tmp"
    urllib.request.urlretrieve(YT_DLP_DOWNLOAD_URL, tmp_path)
    os.replace(tmp_path, dest_path)
    logger.info("yt-dlp.exe downloaded to %s", dest_path)


def ensure_ytdlp(appdata_dir: str) -> str:
    """
    Make sure yt-dlp.exe exists and is up to date. Safe to call on every
    startup or before every download — never raises; on any failure it just
    falls back to whatever copy is already on disk (or downloads one if
    there isn't one yet).

    Returns the path to the executable.
    """
    exe_path = get_ytdlp_path(appdata_dir)

    if not os.path.exists(exe_path):
        try:
            download_ytdlp_exe(exe_path)
        except Exception as e:
            logger.error("Could not download yt-dlp.exe: %s", e)
        return exe_path

    try:
        # Official yt-dlp.exe builds know how to update themselves in place.
        result = _run_hidden(
            [exe_path, "-U"],
            capture_output=True, text=True, timeout=30,
        )
        logger.debug("yt-dlp self-update output: %s", result.stdout.strip())
    except Exception as e:
        logger.warning("yt-dlp self-update check failed, continuing with existing copy: %s", e)

    return exe_path


def get_ytdlp_version(exe_path: str) -> str:
    try:
        result = _run_hidden(
            [exe_path, "--version"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or "unknown"
    except Exception as e:
        logger.warning("Could not read yt-dlp version: %s", e)
        return "unknown"


def extract_info(exe_path: str, url: str, client: str) -> dict:
    """
    Run `yt-dlp --dump-json` for a given player client and return the parsed
    info dict (same shape as yt_dlp's Python `extract_info`, including the
    'formats' list). Raises YtDlpError on failure.
    """
    cmd = [
        exe_path,
        "--dump-json",
        "--no-warnings",
        "--extractor-args", f"youtube:player_client={client}",
        url,
    ]
    result = _run_hidden(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0 or not result.stdout.strip():
        raise YtDlpError(result.stderr.strip() or "yt-dlp returned no data")

    try:
        # --dump-json prints one JSON object per line; take the first.
        return json.loads(result.stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        raise YtDlpError(f"Could not parse yt-dlp output: {e}")


def find_info_with_compatible_format(exe_path: str, url: str, format_selector):
    """
    Try each client in CLIENT_LIST until `format_selector(formats)` returns a
    fully truthy result (e.g. a (video_format, audio_format) tuple with both
    entries set). Returns (info, client, result). If nothing works, returns
    (None, None, (None, None)).
    """
    for client in CLIENT_LIST:
        try:
            info = extract_info(exe_path, url, client)
        except YtDlpError as e:
            logger.debug("Client %s failed: %s", client, e)
            continue

        result = format_selector(info.get("formats", []))
        if result and all(result):
            return info, client, result

    return None, None, (None, None)
