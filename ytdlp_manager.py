"""
Uses the standalone yt-dlp.exe binary so new yt-dlp releases can be picked up
without rebuilding the app.The binary is stored in AppData and updated
once per app run, rather than before every download.
"""

import json
import logging
import os
import subprocess
import urllib.request

logger = logging.getLogger(__name__)

YT_DLP_EXE_NAME = "yt-dlp.exe"
# Using nightly instead of stable; YouTube-side issues are usually fixed faster.
# Nightly is an official yt-dlp channel and is released more frequently.

YT_DLP_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.exe"
YT_DLP_UPDATE_CHANNEL = "nightly"

# Player clients to try, in order, when extracting video info.
CLIENT_LIST = ["web_mobile", "web", "ios", "android", "tv"]

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# In-process cache: After ensure_ytdlp runs once,
# update checks are skipped; subsequent downloads reuse the existing binary.
_session_checked = False
_cached_exe_path = None


class YtDlpError(Exception):
    """Raised when yt-dlp.exe cannot be run or returns no usable data."""


def _run_hidden(cmd, **kwargs):
    return subprocess.run(cmd, creationflags=_NO_WINDOW, **kwargs)


def get_ytdlp_path(appdata_dir: str) -> str:
    return os.path.join(appdata_dir, YT_DLP_EXE_NAME)


def download_ytdlp_exe(dest_path: str, on_progress=None) -> None:
    """Downloads the latest yt-dlp.exe from GitHub. If on_progress is provided,
    it reports download progress from 0-100%; otherwise, progress is indeterminate."""
    tmp_path = dest_path + ".tmp"

    def _reporthook(block_num, block_size, total_size):
        if on_progress and total_size > 0:
            percent = min(100.0, block_num * block_size * 100 / total_size)
            on_progress(percent)

    urllib.request.urlretrieve(
        YT_DLP_DOWNLOAD_URL, tmp_path,
        reporthook=_reporthook if on_progress else None,
    )
    os.replace(tmp_path, dest_path)
    logger.info("yt-dlp.exe downloaded to %s", dest_path)


def ensure_ytdlp(appdata_dir: str, force_check: bool = False, on_status=None) -> str:
    """
    Ensures yt-dlp.exe exists and is up to date. On failure, uses the existing
    copy or downloads one if none exists. The update check runs only
    once per app session; subsequent calls reuse the result.
    If provided, on_status reports the download status.
    Returns the path to the executable.
    """
    global _session_checked, _cached_exe_path

    def _notify(stage, percent=None):
        if on_status:
            on_status(stage, percent)

    exe_path = get_ytdlp_path(appdata_dir)

    if not os.path.exists(exe_path):
        _notify("downloading", 0.0)
        try:
            download_ytdlp_exe(exe_path, on_progress=lambda p: _notify("downloading", p))
        except Exception as e:
            logger.error("Could not download yt-dlp.exe: %s", e)
        _session_checked = True
        _cached_exe_path = exe_path
        _notify("ready")
        return exe_path

    if _session_checked and not force_check:
        _notify("ready")
        return _cached_exe_path or exe_path

    _notify("checking_update")
    try:
        # Official yt-dlp.exe builds know how to update themselves in place.
        # --update-to nightly (instead of plain -U) both updates AND makes
        # sure we stay on the nightly channel — plain -U only updates within
        # whatever channel the binary was already built for, so an existing
        # stable .exe would otherwise keep re-updating to stable.
        result = _run_hidden(
            [exe_path, "--update-to", YT_DLP_UPDATE_CHANNEL],
            capture_output=True, text=True, timeout=30,
        )
        logger.debug("yt-dlp self-update output: %s", result.stdout.strip())
    except Exception as e:
        logger.warning("yt-dlp self-update check failed, continuing with existing copy: %s", e)

    _session_checked = True
    _cached_exe_path = exe_path
    _notify("ready")
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


def find_info_with_compatible_format(exe_path: str, url: str, format_selector, collected_errors=None):
    """
    Tries each client in CLIENT_LIST until format_selector(formats) succeeds.
    Returns (info, client, result) on success, or (None, None, (None, None)) if all clients fail.
    If collected_errors is provided,
    it stores each YtDlpError message so the caller can identify the actual failure reason
    instead of showing a generic “no compatible format” error.
    """
    for client in CLIENT_LIST:
        logger.debug("Trying client=%s", client)
        try:
            info = extract_info(exe_path, url, client)
        except YtDlpError as e:
            logger.debug("Client %s failed to extract info: %s", client, e)
            if collected_errors is not None:
                collected_errors.append(str(e))
            continue

        formats = info.get("formats", [])
        result = format_selector(formats)
        if result and all(result):
            logger.debug("Client %s: found compatible format(s)", client)
            return info, client, result

        logger.debug(
            "Client %s: extracted info but no compatible format among %d formats",
            client, len(formats),
        )

    return None, None, (None, None)