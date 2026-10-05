"""
Getting and updating yt-dlp.exe itself.

The exe is stored in the AppData folder, downloaded and SHA-256-verified on
first run, and checked for updates at regular intervals. Entry point:
ensure_ytdlp().
"""

import hashlib
import logging
import os
import re
import time
import urllib.request

from settings import load_setting, save_setting
from ytdlp.runner import YtDlpError, run_hidden

logger = logging.getLogger(__name__)

YT_DLP_EXE_NAME = "yt-dlp.exe"

# Using nightly instead of stable; YouTube-side issues are usually fixed faster.
# Nightly is an official yt-dlp channel and is released more frequently.
# The release URLs below and YT_DLP_UPDATE_CHANNEL must both stay on it.
#
# "latest" is resolved to a concrete release tag first, and both the binary and
# its SHA2-256SUMS are then fetched from that same tag. This avoids a race
# where a new nightly is published between the two requests.
_RELEASES_LATEST_URL = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest"
_RELEASE_ASSET_URL = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/download/{tag}/{name}"
YT_DLP_UPDATE_CHANNEL = "nightly"

# config.json key: Unix timestamp of the last GitHub update check.
# Persists the check time across app restarts until MIN_UPDATE_CHECK_INTERVAL passes.
_LAST_UPDATE_CHECK_SETTING_KEY = "ytdlp_last_update_check_ts"

# Minimum time to wait between two consecutive GitHub update checks.
MIN_UPDATE_CHECK_INTERVAL = 12 * 60 * 60  # 12 hours

# Applied to both connecting and each subsequent read while downloading
# yt-dlp.exe (and to the release-tag / checksum lookups before it).
# urllib.request.urlretrieve has no timeout support on its own,
# so without this a dropped/stalled connection would hang forever instead
# of failing promptly.
_DOWNLOAD_TIMEOUT = 30  # seconds

# In-process cache: After ensure_ytdlp runs once,
# update checks are skipped; subsequent downloads reuse the existing binary.
_session_checked = False
_cached_exe_path = None


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


def _resolve_latest_tag() -> str:
    """Follows the /releases/latest redirect and returns the release tag."""
    with urllib.request.urlopen(_RELEASES_LATEST_URL, timeout=_DOWNLOAD_TIMEOUT) as response:
        final_url = response.geturl()  # .../releases/tag/<tag>
    tag = final_url.rstrip("/").rsplit("/", 1)[-1]
    if tag == "latest" or not re.fullmatch(r"[0-9A-Za-z._-]+", tag):
        raise RuntimeError(f"Could not determine latest yt-dlp release tag from {final_url!r}")
    return tag


def _fetch_expected_sha256(tag: str, asset_name: str) -> str:
    """Reads the release's SHA2-256SUMS file and returns the hex digest for asset_name."""
    url = _RELEASE_ASSET_URL.format(tag=tag, name="SHA2-256SUMS")
    with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:
        text = response.read(1024 * 1024).decode("utf-8", "replace")
    for line in text.splitlines():
        parts = line.split()
        # Format: "<hex digest>  <file name>" (a leading "*" marks binary mode)
        if len(parts) == 2 and parts[1].lstrip("*") == asset_name:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    raise RuntimeError(f"No SHA-256 entry for {asset_name} in SHA2-256SUMS ({tag})")


def download_ytdlp_exe(dest_path: str, on_progress=None) -> None:
    """Downloads the latest nightly yt-dlp.exe from GitHub and verifies it
    before installing it. If on_progress is provided (and the server sends
    a Content-Length), it reports download progress from 0-100%; otherwise,
    progress is indeterminate.

    Verification (fails closed - nothing is installed if any step fails):
      * the byte count must match Content-Length (HTTPResponse.read(amt) does
        NOT raise on an early EOF, so a dropped connection would otherwise
        look like a normal end of file),
      * the SHA-256 must match the release's SHA2-256SUMS.

    Uses an explicit timeout (applied to connecting AND each subsequent read),
    so a dropped or stalled connection raises promptly instead of hanging
    forever - urlretrieve alone has no timeout support.
    """
    tmp_path = dest_path + ".tmp"
    try:
        tag = _resolve_latest_tag()
        expected_sha256 = _fetch_expected_sha256(tag, YT_DLP_EXE_NAME)
        url = _RELEASE_ASSET_URL.format(tag=tag, name=YT_DLP_EXE_NAME)

        sha256 = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:
            total_size = int(response.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha256.update(chunk)
                    downloaded += len(chunk)
                    if on_progress and total_size > 0:
                        on_progress(min(100.0, downloaded * 100 / total_size))

        if total_size > 0 and downloaded != total_size:
            raise IOError(
                f"Incomplete download: got {downloaded} of {total_size} bytes"
            )
        if sha256.hexdigest() != expected_sha256:
            raise IOError("SHA-256 mismatch for downloaded yt-dlp.exe")

        os.replace(tmp_path, dest_path)
        logger.info("yt-dlp.exe (%s) downloaded and verified: %s", tag, dest_path)
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

    If provided, on_status(stage, detail) is called with one of:
      "downloading"     detail = percent 0-100 (first run, exe missing)
      "checking_update" detail = None (running `--update-to`)
      "ready"           detail = None
      "error"           detail = the exception; the download failed and
                        YtDlpError is raised right after (fatal)
      "update_failed"   detail = the exception; non-fatal, the existing exe
                        is still returned and usable
    Returns the executable path."""

    global _session_checked, _cached_exe_path

    def _notify(stage, detail=None):
        if on_status:
            on_status(stage, detail)

    exe_path = get_ytdlp_path(appdata_dir)

    # Only the file's existence is checked here; yt-dlp.exe is not started
    # just to test it. A partial download can't end up at exe_path anyway:
    # download_ytdlp_exe() verifies size + SHA-256 on a .tmp file and only
    # then os.replace()s it into place.
    needs_download = not os.path.exists(exe_path)

    if needs_download:
        _notify("downloading", 0.0)
        try:
            download_ytdlp_exe(exe_path, on_progress=lambda p: _notify("downloading", p))
        except Exception as e:
            logger.error("Could not download yt-dlp.exe: %s", e)
            # There is no exe at exe_path — don't cache it or report
            # "ready" as if there were. Leaving _session_checked False means a
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
        result = run_hidden(
            [exe_path, "--update-to", YT_DLP_UPDATE_CHANNEL],
            capture_output=True, text=True, timeout=30,
        )
        logger.debug("yt-dlp self-update output: %s", result.stdout.strip())
        if result.returncode != 0:
            # The subprocess ran, but yt-dlp reported that the update
            # didn't go through (e.g. no internet, GitHub rate limit).
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
        result = run_hidden(
            [exe_path, "--version"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() or "unknown"
    except Exception as e:
        logger.warning("Could not read yt-dlp version: %s", e)
        return "unknown"
