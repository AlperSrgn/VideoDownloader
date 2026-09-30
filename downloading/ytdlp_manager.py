"""
Uses the standalone yt-dlp.exe binary.
The binary is stored in the AppData folder and checked for updates
at regular intervals.
"""


import hashlib
import json
import logging
import os
import re
import subprocess
import time
import urllib.request

from settings import load_setting, save_setting

logger = logging.getLogger(__name__)

YT_DLP_EXE_NAME = "yt-dlp.exe"
# Using nightly instead of stable; YouTube-side issues are usually fixed faster.
# Nightly is an official yt-dlp channel and is released more frequently.

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
# yt-dlp.exe. urllib.request.urlretrieve has no timeout support on its own,
# so without this a dropped/stalled connection would hang forever instead
# of failing promptly.
_DOWNLOAD_TIMEOUT = 30  # seconds

# Player clients to try in order when extracting video info.
# None uses yt-dlp's built-in default clients.
# yt-dlp is kept up to date, so its defaults stay current.
# Add fallbacks only if needed, e.g.:
#   CLIENT_LIST = [None, "tv"]
# None is always tried first.

CLIENT_LIST = [None]


def youtube_extractor_args(client, extra=None) -> list:
    """Builds the `--extractor-args` part of a yt-dlp command.

    client=None -> no player_client key, so yt-dlp picks its own defaults.
    `extra` is an additional youtube: option such as "skip=hls,dash".
    Returns [] when there is nothing to pass.
    """
    parts = []
    if client:
        parts.append(f"player_client={client}")
    if extra:
        parts.append(extra)
    if not parts:
        return []
    return ["--extractor-args", "youtube:" + ";".join(parts)]

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
    """Downloads the latest yt-dlp.exe from GitHub and verifies it before
    installing it. If on_progress is provided, it reports download progress
    from 0-100%; otherwise, progress is indeterminate.

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


def _is_runnable(exe_path: str) -> bool:
    """True if the exe starts and answers --version. Used to detect a corrupt
    yt-dlp.exe (e.g. one left over from an earlier truncated download) that
    merely *exists*. A timeout is not treated as corruption."""
    try:
        result = _run_hidden(
            [exe_path, "--version"],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return True
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


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

    needs_download = not os.path.exists(exe_path)
    if not needs_download and not _session_checked and not _is_runnable(exe_path):
        # File exists but doesn't run (corrupt/truncated) - os.path.exists()
        # alone would keep it forever, so re-download it. Checked once per process.
        logger.warning("Existing yt-dlp.exe is not runnable; re-downloading")
        needs_download = True

    if needs_download:
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
        *youtube_extractor_args(client),
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
        *youtube_extractor_args(client, extra="skip=hls,dash"),
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
            logger.debug("Preview: client=%s failed: %s", client or "default", e)
            continue
    return None


# ---------------------------------------------------------------------------
# Format selection (moved from downloader.py — operates purely on the
# 'formats' list shape that --dump-json / extract_info() produces, with no
# download-specific logic, so it belongs next to the client-list/extraction
# code above rather than in the download-orchestration module).
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


def find_info_with_compatible_format(exe_path: str, url: str, format_selector, collected_errors=None):
    """
    Tries each client in CLIENT_LIST until format_selector(formats) succeeds.
    Returns (info, client, result) on success, or (None, None, None) if all clients fail.
    If collected_errors is provided,
    it stores each YtDlpError message so the caller can identify the actual failure reason
    instead of showing a generic “no compatible format” error.
    """
    for client in CLIENT_LIST:
        logger.debug("Trying client=%s", client or "default")
        try:
            info = extract_info(exe_path, url, client)
        except YtDlpError as e:
            logger.debug("Client %s failed to extract info: %s", client or "default", e)
            if collected_errors is not None:
                collected_errors.append(str(e))
            continue

        formats = info.get("formats", [])
        result = format_selector(formats)
        if result and all(result):
            logger.debug("Client %s: found compatible format(s)", client or "default")
            return info, client, result

        logger.debug(
            "Client %s: extracted info but no compatible format among %d formats",
            client or "default", len(formats),
        )

    return None, None, None