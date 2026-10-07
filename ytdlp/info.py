"""
Reading a video's metadata with `yt-dlp --dump-json`.

Two flavours:
  - fetch_preview_info():             the quick one for the URL-paste preview
                                      (title / duration / thumbnail only)
  - find_info_with_access_fallback(): the full extraction a download needs,
                                      including the 'formats' list

Both go through the player clients in CLIENT_LIST, and both retry with
cookies and Deno when the video needs a login; that decision is made by
ytdlp/access.py (run_with_access_fallback), not here.
"""

import json
import logging

from core.error_classifier import DenoNotFoundError
from ytdlp.access import access_args, run_with_access_fallback
from ytdlp.runner import YtDlpError, run_info_command, youtube_extractor_args

logger = logging.getLogger(__name__)

# Player clients to try in order when extracting video info.
# None uses yt-dlp's built-in default clients.
# yt-dlp is kept up to date, so its defaults stay current.
# Add fallbacks only if needed, e.g.:
#   CLIENT_LIST = [None, "tv"]
# None is always tried first.
CLIENT_LIST = [None]


def extract_info(exe_path: str, url: str, client: str, restricted: bool = False) -> dict:
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
        *access_args(restricted),
        *youtube_extractor_args(client),
        url,
    ]
    suffix = "/restricted" if restricted else ""
    stdout = run_info_command(cmd, timeout=60, label=f"info/{client or 'default'}{suffix}")

    try:
        # --dump-json prints one JSON object per line; take the first.
        return json.loads(stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        raise YtDlpError(f"Could not parse yt-dlp output: {e}")


def _extract_preview_info(exe_path: str, url: str, client: str, restricted: bool = False) -> dict:
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
        *access_args(restricted),
        *youtube_extractor_args(client, extra="skip=hls,dash"),
        url,
    ]
    suffix = "/restricted" if restricted else ""
    stdout = run_info_command(cmd, timeout=30, label=f"preview/{client or 'default'}{suffix}")

    try:
        return json.loads(stdout.splitlines()[0])
    except (json.JSONDecodeError, IndexError) as e:
        raise YtDlpError(f"Could not parse yt-dlp output: {e}")


def fetch_preview_info(exe_path: str, url: str) -> dict | None:
    """
    Tries each client in CLIENT_LIST until one returns *any* usable info
    dict (title/duration/thumbnail/...). Used for the URL-paste preview
    panel, which just needs to describe the video -- unlike
    find_info_with_compatible_format, it doesn't care whether a specific
    format/quality is actually downloadable, so it uses the faster
    _extract_preview_info() rather than extract_info().

    Age-restricted / members-only videos are retried with cookies + Deno when
    both are set up (see ytdlp/access.py).

    Returns None if every client fails (invalid link, unsupported site,
    video removed, Deno missing for a restricted video, etc.) -- the caller
    should just hide the preview silently in that case rather than showing an
    error, since this is a supplementary nicety, not a core flow.
    """
    def attempt(restricted: bool, errors: list):
        for client in CLIENT_LIST:
            try:
                return _extract_preview_info(exe_path, url, client, restricted=restricted)
            except YtDlpError as e:
                logger.debug(
                    "Preview%s: client=%s failed: %s",
                    " (restricted)" if restricted else "", client or "default", e,
                )
                errors.append(str(e))
        return None

    try:
        return run_with_access_fallback(url, attempt).value
    except DenoNotFoundError:
        # Needs a login but Deno isn't installed: hide the preview. The
        # download itself tells the user what is missing.
        return None


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



def find_info_with_compatible_format(exe_path: str, url: str, format_selector,
                                     collected_errors=None, fallback_selector=None,
                                     restricted: bool = False):
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
            info = extract_info(exe_path, url, client, restricted)
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


def find_info_with_access_fallback(exe_path: str, url: str, format_selector,
                                   collected_errors=None, fallback_selector=None):
    """Full info extraction for a download, with the cookies + Deno retry for
    age-restricted / members-only videos (see run_with_access_fallback for the
    order of passes).

    Returns (info, client, result, restricted); `restricted` tells the caller
    to build its download commands with access_args(True) too. On failure
    info is None. Raises DenoNotFoundError if the restricted pass is needed
    but Deno is not installed. If collected_errors is given, the error
    messages of the last pass are appended to it.
    """
    def attempt(restricted: bool, errors: list):
        found = find_info_with_compatible_format(
            exe_path, url, format_selector,
            collected_errors=errors, fallback_selector=fallback_selector,
            restricted=restricted,
        )
        return found if found[0] else None

    outcome = run_with_access_fallback(url, attempt)
    if collected_errors is not None:
        collected_errors.extend(outcome.errors)
    info, client, result = outcome.value or (None, None, None)
    return info, client, result, outcome.restricted