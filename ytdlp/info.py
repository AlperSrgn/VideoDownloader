"""
Reading a video's metadata with `yt-dlp --dump-json`.

Two flavours:
  - fetch_preview_info():             the quick one for the URL-paste preview
                                      (title / duration / thumbnail only)
  - find_info_with_access_fallback(): the full extraction a download needs,
                                      including the 'formats' list

Both go through the player clients in CLIENT_LIST (RESTRICTED_CLIENT_LIST for
videos that need a login), and both retry with cookies and Deno when the video
needs one; that decision is made by ytdlp/access.py (run_with_access_fallback),
not here.
"""

import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from core.error_classifier import DenoNotFoundError
from ytdlp.access import run_with_access_fallback
from ytdlp.commands import build_info_cmd
from ytdlp.formats import FormatSelector, Selection
from ytdlp.runner import YtDlpError, run_info_command

logger = logging.getLogger(__name__)

# Player clients to try in order when extracting video info.
# None uses yt-dlp's built-in default clients.
# yt-dlp is kept up to date, so its defaults stay current.
# Add fallbacks only if needed, e.g.:
#   CLIENT_LIST = [None, "tv"]
# None is always tried first.
CLIENT_LIST = [None]

# Clients for the restricted pass (age-restricted / members-only videos, with
# cookies). With a signed-in account the default client often gets SABR-only
# streams without URLs; web_safari still returns HLS formats up to 1080p.
RESTRICTED_CLIENT_LIST = [None, "web_safari"]

# The restricted client that worked last (in any restricted pass this session)
# is tried first next time, so a signed-in account whose default client is
# SABR-only does not pay for the failing client on every video (each client
# costs ~6-7 s). [] = none known yet; [None] = the default client worked.
# In-memory only: nothing is persisted.
_restricted_client_hint: list = []
_hint_lock = threading.Lock()


def _restricted_clients() -> list:
    """RESTRICTED_CLIENT_LIST, with the client that worked last moved first."""
    with _hint_lock:
        hint = list(_restricted_client_hint)
    if not hint or hint[0] not in RESTRICTED_CLIENT_LIST:
        return list(RESTRICTED_CLIENT_LIST)
    return [hint[0]] + [c for c in RESTRICTED_CLIENT_LIST if c != hint[0]]


def _remember_restricted_client(client) -> None:
    with _hint_lock:
        _restricted_client_hint[:] = [client]


@dataclass(frozen=True)
class Extraction:
    """A successful info extraction together with what to download from it."""
    info: dict                # yt-dlp's info dict (incl. 'formats')
    client: Optional[str]     # player client that produced it (None = default)
    selection: Selection      # the formats chosen from info["formats"]
    restricted: bool = False  # True: build download commands with access_args(True)


def extract_info(exe_path: str, url: str, client: str, restricted: bool = False) -> dict:
    """
    Run `yt-dlp --dump-json` for a given player client and return the parsed
    info dict (same shape as yt_dlp's Python `extract_info`, including the
    'formats' list). Raises YtDlpError on failure.
    """
    cmd = build_info_cmd(exe_path, url, client, restricted)
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
    cmd = build_info_cmd(exe_path, url, client, restricted, preview=True)
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
                errors.append(e)
        return None

    try:
        # log_failure=False: a failed preview is silent; if the video really
        # cannot be downloaded, the download logs the full diagnostics itself.
        return run_with_access_fallback(url, attempt, log_failure=False).value
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


def find_info_with_compatible_format(exe_path: str, url: str, selector: FormatSelector,
                                     collected_errors=None,
                                     fallback_selector: FormatSelector | None = None,
                                     fallback_good_enough: Callable[[Selection], bool] | None = None,
                                     restricted: bool = False) -> Extraction | None:
    """
    Tries each client until `selector(formats)` returns a Selection, and
    returns that as an Extraction. Returns None if every client fails.

    If fallback_selector is given, it is only used when NO client satisfied
    `selector`: the fallback Selection with the greatest video height wins
    (the first client wins ties), so a better client is never skipped just
    because an earlier one only offered a lower-quality fallback.
    If fallback_good_enough is also given and the best fallback so far
    satisfies it (e.g. it already reaches the requested resolution), the
    remaining clients are skipped: each costs several seconds and cannot
    improve on it.

    In the restricted pass the clients are tried in the order of
    _restricted_clients() (the one that worked last first), and the client of
    the returned Extraction is remembered for next time.

    If collected_errors is provided, the YtDlpError of each failed client is
    appended to it (str() gives the message) so the caller can identify the
    actual failure reason instead of showing a generic “no compatible format”
    error, and log the full diagnostics if the failure is final.
    """
    clients = _restricted_clients() if restricted else CLIENT_LIST
    fallback: Extraction | None = None

    for client in clients:
        logger.debug("Trying client=%s", client or "default")
        try:
            info = extract_info(exe_path, url, client, restricted)
        except YtDlpError as e:
            logger.debug("Client %s failed to extract info: %s", client or "default", e)
            if collected_errors is not None:
                collected_errors.append(e)
            continue

        formats = info.get("formats", [])
        selection = selector(formats)
        if selection is not None:
            logger.debug("Client %s: found compatible format(s)", client or "default")
            if restricted:
                _remember_restricted_client(client)
            return Extraction(info, client, selection, restricted)

        _log_format_summary(client, formats)
        logger.debug(
            "Client %s: extracted info but no compatible format among %d formats",
            client or "default", len(formats),
        )

        if fallback_selector is not None:
            candidate = fallback_selector(formats)
            if candidate is not None and (
                fallback is None or candidate.height > fallback.selection.height
            ):
                fallback = Extraction(info, client, candidate, restricted)

        if (fallback is not None and fallback_good_enough is not None
                and fallback_good_enough(fallback.selection)):
            logger.debug(
                "Fallback from client %s is good enough; skipping remaining clients",
                fallback.client or "default",
            )
            break

    if fallback is not None:
        if restricted:
            _remember_restricted_client(fallback.client)
        logger.warning(
            "No separate streams from any client; falling back to %s format %s "
            "(client=%s, %sp)",
            fallback.selection.kind, fallback.selection.primary.get("format_id"),
            fallback.client or "default", fallback.selection.height,
        )
        return fallback

    return None


def find_info_with_access_fallback(exe_path: str, url: str, selector: FormatSelector,
                                   collected_errors=None,
                                   fallback_selector: FormatSelector | None = None,
                                   fallback_good_enough: Callable[[Selection], bool] | None = None
                                   ) -> Extraction | None:
    """Full info extraction for a download, with the cookies + Deno retry for
    age-restricted / members-only videos (see run_with_access_fallback for the
    order of passes).

    Returns an Extraction, or None on failure. `Extraction.restricted` tells
    the caller to build its download commands with access_args(True) too.
    Raises DenoNotFoundError if the restricted pass is needed but Deno is not
    installed. If collected_errors is given, the error messages (strings) of
    the last pass are appended to it. When the whole extraction fails, the full
    yt-dlp diagnostics of the last pass are logged once (see
    run_with_access_fallback).
    """
    def attempt(restricted: bool, errors: list):
        return find_info_with_compatible_format(
            exe_path, url, selector,
            collected_errors=errors, fallback_selector=fallback_selector,
            fallback_good_enough=fallback_good_enough, restricted=restricted,
        )

    outcome = run_with_access_fallback(url, attempt)
    if collected_errors is not None:
        collected_errors.extend(str(e) for e in outcome.errors)
    return outcome.value