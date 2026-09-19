"""
Uses the standalone yt-dlp.exe binary.
The binary is stored in the AppData folder and checked for updates
at regular intervals.
"""


import json
import logging
import os
import subprocess
import time
import urllib.request

from settings import load_setting, save_setting

logger = logging.getLogger(__name__)

YT_DLP_EXE_NAME = "yt-dlp.exe"
# Using nightly instead of stable; YouTube-side issues are usually fixed faster.
# Nightly is an official yt-dlp channel and is released more frequently.

YT_DLP_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.exe"
YT_DLP_UPDATE_CHANNEL = "nightly"

# config.json key: Unix timestamp of the last GitHub update check.
# Persists the check time across app restarts until MIN_UPDATE_CHECK_INTERVAL passes.
_LAST_UPDATE_CHECK_SETTING_KEY = "ytdlp_last_update_check_ts"

# Minimum time to wait between two consecutive GitHub update checks.
MIN_UPDATE_CHECK_INTERVAL = 12 * 60 * 60  # 12 hours

# Applied to both connecting and each subsequent read while downloading
# yt-dlp.exe. urllib.request.urlretrieve has no timeout support on its own,
# so without this a dropped/stalled connection would hang forever instead
# of failing promptly.
_DOWNLOAD_TIMEOUT = 30  # seconds

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


def _read_last_update_check() -> float:
    """Reads the unix timestamp of the last update check from config.json.
    Returns 0.0 if the setting was never written or is malformed (i.e.
    "act as if it was never checked" -> a check is performed)."""
    try:
        return float(load_setting(_LAST_UPDATE_CHECK_SETTING_KEY, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _write_last_update_check(ts: float) -> None:
    """Writes the timestamp of the last update check to config.json."""
    save_setting(_LAST_UPDATE_CHECK_SETTING_KEY, ts)


def download_ytdlp_exe(dest_path: str, on_progress=None) -> None:
    """Downloads the latest yt-dlp.exe from GitHub. If on_progress is provided,
    it reports download progress from 0-100%; otherwise, progress is indeterminate.

    Uses an explicit timeout (applied to connecting AND each subsequent read),
    so a dropped or stalled connection raises promptly instead of hanging
    forever — urlretrieve alone has no timeout support.
    """
    tmp_path = dest_path + ".tmp"
    try:
        with urllib.request.urlopen(YT_DLP_DOWNLOAD_URL, timeout=_DOWNLOAD_TIMEOUT) as response:
            total_size = int(response.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total_size > 0:
                        on_progress(min(100.0, downloaded * 100 / total_size))
        os.replace(tmp_path, dest_path)
        logger.info("yt-dlp.exe downloaded to %s", dest_path)
    except Exception:
        # Don't leave a partial/corrupt .tmp file lying around on failure.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def ensure_ytdlp(appdata_dir: str, force_check: bool = False, on_status=None) -> str:
    """
    Ensures yt-dlp.exe exists and is up to date. Uses the existing copy or
    downloads one if needed. Update checks are limited by
    MIN_UPDATE_CHECK_INTERVAL and the current process session, with the
    check time persisted via settings. Pass force_check=True to bypass
    these limits and force an immediate check.

    If provided, on_status(stage, detail) reports download progress,
    fatal errors, or non-fatal update failures. Returns the executable path."""

    global _session_checked, _cached_exe_path

    def _notify(stage, detail=None):
        if on_status:
            on_status(stage, detail)

    exe_path = get_ytdlp_path(appdata_dir)

    if not os.path.exists(exe_path):
        _notify("downloading", 0.0)
        try:
            download_ytdlp_exe(exe_path, on_progress=lambda p: _notify("downloading", p))
        except Exception as e:
            logger.error("Could not download yt-dlp.exe: %s", e)
            # exe_path doesn't actually exist — don't cache it or report
            # "ready" as if it does. Leaving _session_checked False means a
            # later retry (e.g. after the user's connection is back) tries
            # the download again instead of silently reusing a broken state.
            _notify("error", e)
            raise YtDlpError(f"Could not download yt-dlp.exe: {e}") from e
        _session_checked = True
        _cached_exe_path = exe_path
        _notify("ready")
        return exe_path

    if _session_checked and not force_check:
        _notify("ready")
        return _cached_exe_path or exe_path

    if not force_check:
        last_check = _read_last_update_check()
        elapsed = time.time() - last_check
        if elapsed < MIN_UPDATE_CHECK_INTERVAL:
            # If not enough time has passed, skip GitHub and use the existing exe.
            logger.debug(
                "Skipping yt-dlp update check, last check was %.0f min ago",
                elapsed / 60,
            )
            _session_checked = True
            _cached_exe_path = exe_path
            _notify("ready")
            return exe_path

    _notify("checking_update")
    update_failed_exc = None
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
        if result.returncode != 0:
            # The subprocess itself ran fine, but yt-dlp reported that the
            # update didn't go through (e.g. no internet, GitHub rate
            # limit) — this was previously never even noticed, since only
            # exceptions from launching the subprocess were caught here.
            update_failed_exc = RuntimeError(
                (result.stdout or "").strip() or f"exit code {result.returncode}"
            )
    except Exception as e:
        update_failed_exc = e

    _session_checked = True
    _cached_exe_path = exe_path

    if update_failed_exc is not None:
        # Don't update the timestamp on a failed check; retry on the next launch.
        # The existing yt-dlp.exe still works, so the process isn't blocked.
        logger.warning(
            "yt-dlp self-update check failed, continuing with existing copy: %s",
            update_failed_exc,
        )
        _notify("update_failed", update_failed_exc)
    else:
        # Only record the check as "done" once it actually succeeded.
        _write_last_update_check(time.time())
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


def _extract_preview_info(exe_path: str, url: str, client: str) -> dict:
    """
    Like extract_info(), but tells yt-dlp to skip resolving the HLS/DASH
    adaptive-stream manifests (skip=hls,dash) — each of those requires its
    own extra network round-trip to build the full 'formats' list, which
    the preview panel never looks at anyway (it only needs
    title/duration/thumbnail). This is noticeably faster than the full
    extraction extract_info() does for an actual download, where every
    format really does need to be resolved.
    """
    cmd = [
        exe_path,
        "--dump-json",
        "--no-warnings",
        "--extractor-args", f"youtube:player_client={client};skip=hls,dash",
        url,
    ]
    result = _run_hidden(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0 or not result.stdout.strip():
        raise YtDlpError(result.stderr.strip() or "yt-dlp returned no data")

    try:
        return json.loads(result.stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        raise YtDlpError(f"Could not parse yt-dlp output: {e}")


def fetch_preview_info(exe_path: str, url: str) -> dict | None:
    """
    Tries each client in CLIENT_LIST until one returns *any* usable info
    dict (title/duration/thumbnail/...). Used for the URL-paste preview
    panel, which just needs to describe the video — unlike
    find_info_with_compatible_format, it doesn't care whether a specific
    format/quality is actually downloadable, so it uses the faster
    _extract_preview_info() rather than extract_info().

    Returns None if every client fails (invalid link, unsupported site,
    video removed, etc.) — the caller should just hide the preview
    silently in that case rather than showing an error, since this is a
    supplementary nicety, not a core flow.
    """
    for client in CLIENT_LIST:
        try:
            return _extract_preview_info(exe_path, url, client)
        except YtDlpError as e:
            logger.debug("Preview: client=%s failed: %s", client, e)
            continue
    return None


def find_info_with_compatible_format(exe_path: str, url: str, format_selector, collected_errors=None):
    """
    Tries each client in CLIENT_LIST until format_selector(formats) succeeds.
    Returns (info, client, result) on success, or (None, None, None) if all clients fail.
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

    return None, None, None