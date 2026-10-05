"""
Everything that talks to the standalone yt-dlp.exe binary.

  - Binary management: the exe is stored in the AppData folder, downloaded
    and SHA-256-verified on first run, and checked for updates at regular
    intervals (ensure_ytdlp).
  - Info extraction: --dump-json wrappers for a full extraction
    (extract_info / find_info_with_compatible_format) and a faster
    preview-only one (fetch_preview_info).
  - Format selection: picking the video/audio format for a requested
    quality out of the extracted 'formats' list.
"""


import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.request

from cookie.cookie_options import COOKIE_BROWSERS
from settings import load_setting, save_setting, get_appdata_path

logger = logging.getLogger(__name__)

YT_DLP_EXE_NAME = "yt-dlp.exe"
COOKIE_FILE_NAME = "cookies.txt"

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

# Player clients to try in order when extracting video info.
# None uses yt-dlp's built-in default clients.
# yt-dlp is kept up to date, so its defaults stay current.
# Add fallbacks only if needed, e.g.:
#   CLIENT_LIST = [None, "tv"]
# None is always tried first.

CLIENT_LIST = [None]


def cookie_file_path() -> str:
    return os.path.join(get_appdata_path(), COOKIE_FILE_NAME)


def cookie_args() -> list:
    """According to the settings, yt-dlp cookie arguments ([] = do not use cookies)."""
    mode = load_setting("cookie_mode", "none")
    args = []
    if mode == "browser":
        browser = load_setting("cookie_browser", "firefox")
        if browser in COOKIE_BROWSERS:
            args = ["--cookies-from-browser", browser]
        else:
            logger.warning("cookie_mode=browser but browser %r is not supported; no cookies sent", browser)
    elif mode == "file":
        path = cookie_file_path()
        if os.path.isfile(path):
            args = ["--cookies", path]
        else:
            logger.warning("cookie_mode=file but %s does not exist; no cookies sent", path)
    logger.debug("cookie_args: mode=%s -> %s", mode, args)
    return args

def js_runtime_args() -> list:
    """Passes Deno explicitly so yt-dlp does not depend on the PATH of this
    process (an IDE / app launched before Deno was installed has a stale PATH).
    Without a JS runtime YouTube formats come back without URLs."""
    deno = shutil.which("deno")
    if not deno:
        candidates = (
            os.path.join(os.path.expanduser("~"), ".deno", "bin", "deno.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "deno.exe"),
        )
        deno = next((p for p in candidates if os.path.isfile(p)), None)
    if not deno:
        logger.warning("Deno not found; YouTube formats may come back without URLs")
        return []
    logger.debug("js_runtime_args: deno=%s", deno)
    return ["--js-runtimes", f"deno:{deno}"]


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
    """Raised when yt-dlp.exe cannot be obtained or run, or returns no usable data."""


def _run_hidden(cmd, **kwargs):
    return subprocess.run(cmd, creationflags=_NO_WINDOW, **kwargs)


# ---------------------------------------------------------------------------
# Diagnostics for the --dump-json info commands
# ---------------------------------------------------------------------------
# On failure the FULL yt-dlp output (including `-v` debug lines, WARNING lines
# and the ERROR line) is written to the log together with the exact command
# and a summary of the cookies that were configured. The YtDlpError that
# callers/classifiers see carries the output WITHOUT the "[debug]" lines, so
# error classification is not confused by verbose noise.

_LOGIN_COOKIE_NAMES = {"SAPISID", "__Secure-3PSID", "SID", "LOGIN_INFO"}


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _indent(text: str, prefix: str = "    | ") -> str:
    lines = text.splitlines() or ["(empty)"]
    return "\n".join(prefix + line for line in lines)


def _strip_debug_lines(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("[debug]")
    ).strip()


def _cookie_summary() -> str:
    """One-line description of the configured cookies. Never includes values."""
    mode = load_setting("cookie_mode", "none")
    if mode == "browser":
        return f"mode=browser, browser={load_setting('cookie_browser', 'firefox')}"
    if mode != "file":
        return f"mode={mode} (no cookies sent)"

    path = cookie_file_path()
    try:
        age_min = int((time.time() - os.path.getmtime(path)) / 60)
        total = expired = 0
        login = set()
        now = time.time()
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\r\n")
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                elif not line.strip() or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                total += 1
                try:
                    exp = int(parts[4])
                except ValueError:
                    exp = 0
                if 0 < exp < now:
                    expired += 1
                if parts[5] in _LOGIN_COOKIE_NAMES:
                    login.add(parts[5])
    except OSError as e:
        return f"mode=file, cannot read {path}: {e}"

    return (
        f"mode=file, {total} cookies ({expired} expired), "
        f"login cookies present: {sorted(login) or 'NONE'}, "
        f"file modified {age_min} min ago"
    )


def _run_info_cmd(cmd: list, timeout: int, label: str) -> str:
    """Runs a yt-dlp info command and returns its stdout.
    Raises YtDlpError on failure/timeout, after logging full diagnostics."""
    started = time.monotonic()
    try:
        result = _run_hidden(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # avoid cp125x decode crashes on Windows
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "[%s] yt-dlp timed out after %ss\n  command: %s\n  cookies: %s\n  partial output:\n%s",
            label, timeout, subprocess.list2cmdline(cmd), _cookie_summary(),
            _indent(_to_text(e.stderr).strip()),
        )
        raise YtDlpError(f"yt-dlp timed out after {timeout}s") from e
    except OSError as e:
        logger.warning("[%s] could not launch yt-dlp: %s", label, e)
        raise YtDlpError(f"Could not run yt-dlp: {e}") from e

    elapsed = time.monotonic() - started
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0 or not stdout.strip():
        logger.warning(
            "[%s] yt-dlp failed (exit=%s, %.1fs)\n  command: %s\n  cookies: %s\n  yt-dlp output:\n%s",
            label, result.returncode, elapsed, subprocess.list2cmdline(cmd),
            _cookie_summary(), _indent(stderr.strip()),
        )
        raise YtDlpError(_strip_debug_lines(stderr) or "yt-dlp returned no data")

    for line in stderr.splitlines():
        if line.startswith("WARNING"):
            logger.warning("[%s] %s", label, line)
    logger.debug("[%s] yt-dlp ok (%.1fs)", label, elapsed)
    return stdout


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
        result = _run_hidden(
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
    # No --no-warnings and -v on purpose: warnings (e.g. "cookies are no longer
    # valid") and debug lines are only ever written to the log on failure.
    cmd = [
        exe_path,
        "--dump-json",
        "-v",
        *cookie_args(),
        *js_runtime_args(),
        *youtube_extractor_args(client),
        url,
    ]
    stdout = _run_info_cmd(cmd, timeout=60, label=f"info/{client or 'default'}")

    try:
        # --dump-json prints one JSON object per line; take the first.
        return json.loads(stdout.splitlines()[0])
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
        "-v",
        *cookie_args(),
        *js_runtime_args(),
        *youtube_extractor_args(client, extra="skip=hls,dash"),
        url,
    ]
    stdout = _run_info_cmd(cmd, timeout=30, label=f"preview/{client or 'default'}")

    try:
        return json.loads(stdout.splitlines()[0])
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
# Format selection: operates purely on the 'formats' list that
# --dump-json / extract_info() produces.
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
    at or below video_height. If nothing at or below video_height exists,
    falls back to the highest resolution available. Within a resolution the
    highest-tbr video and the original-language audio track are chosen.
    Returns (None, None) if there are no usable (url-bearing) video or audio
    formats — e.g. SABR-protected videos, whose formats come without a
    direct URL.
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


def _log_format_summary(client, formats: list) -> None:
    """Dumps what yt-dlp returned, so a 'no compatible format' failure can be
    diagnosed (formats with url=NO are SABR/n-challenge casualties)."""
    rows = [
        f"    {f.get('format_id')}: ext={f.get('ext')} v={f.get('vcodec')} "
        f"a={f.get('acodec')} h={f.get('height')} proto={f.get('protocol')} "
        f"url={'yes' if f.get('url') else 'NO'}"
        for f in formats
    ]
    logger.debug("Client %s returned %d formats:\n%s",
                 client or "default", len(formats), "\n".join(rows) or "    (none)")


# ---------------------------------------------------------------------------
# Fallback: progressive (single-file, video+audio) formats
# ---------------------------------------------------------------------------
# When YouTube forces SABR streaming (common for age-restricted videos and
# some accounts), the separate DASH video/audio streams come back without a
# URL and often only a progressive format (e.g. 18 = 360p mp4) remains. These
# helpers let callers use it as a last resort instead of failing outright.

def _progressive_formats(formats: list) -> list:
    return [
        f for f in formats
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("protocol") in ("https", "http")
    ]


def find_progressive_format(formats: list, video_height: int):
    """Fallback selector for video downloads. Returns (format, None); the
    None audio slot tells the caller this is a single-file download that
    needs no merge. Returns (None, None) if there is no progressive format."""
    candidates = [f for f in _progressive_formats(formats) if f.get("height")]
    if not candidates:
        return None, None
    pool = [f for f in candidates if f["height"] <= video_height] or candidates
    best = max(pool, key=lambda f: (f["height"], f.get("tbr") or 0))
    return best, None


def find_progressive_audio_format(formats: list):
    """Fallback selector for audio-only downloads: the smallest progressive
    format (least data to download); the audio is extracted from it later."""
    candidates = _progressive_formats(formats)
    if not candidates:
        return (None,)
    return (min(candidates, key=lambda f: f.get("height") or 10 ** 9),)


def find_info_with_compatible_format(exe_path: str, url: str, format_selector,
                                     collected_errors=None, fallback_selector=None):
    """
    Tries each client in CLIENT_LIST until format_selector(formats) succeeds,
    i.e. returns a non-empty tuple with no None in it (as
    find_suitable_format / find_suitable_audio_format do).
    Returns (info, client, result) on success, or (None, None, None) if all clients fail.
    If fallback_selector is given, it is only used when NO client satisfied
    format_selector: the first client whose formats satisfy it (its first
    element must be truthy) is returned instead, so a better client is never
    skipped just because an earlier one only had the fallback.
    If collected_errors is provided,
    it stores each YtDlpError message so the caller can identify the actual failure reason
    instead of showing a generic “no compatible format” error.
    """
    fallback = None
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

        _log_format_summary(client, formats)
        logger.debug(
            "Client %s: extracted info but no compatible format among %d formats",
            client or "default", len(formats),
        )

        if fallback is None and fallback_selector is not None:
            fb = fallback_selector(formats)
            if fb and fb[0]:
                fallback = (info, client, fb)

    if fallback is not None:
        logger.warning(
            "No separate streams from any client; falling back to progressive format %s",
            fallback[2][0].get("format_id"),
        )
        return fallback

    return None, None, None