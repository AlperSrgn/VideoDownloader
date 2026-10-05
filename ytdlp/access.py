"""
Signed-in access for age-restricted / members-only videos.

Normal videos are handled without cookies and without Deno. Only a video that
yt-dlp reports as age-restricted or members-only (and only if the user has
cookies configured) is retried with the user's cookies plus Deno -- Deno is
the JavaScript runtime yt-dlp needs for those videos.

This module owns that whole story:
  - access_args():              the extra yt-dlp arguments (cookies + Deno)
  - find_deno():                where Deno is installed
  - run_with_access_fallback(): the single place that decides WHEN a video gets
                                them; the preview and the download both use it
"""

import logging
import os
import re
import shutil
import threading
from typing import NamedTuple

from cookie import cookie_args
from downloading.error_classifier import DenoNotFoundError, is_access_restricted_error

logger = logging.getLogger(__name__)


def find_deno():
    """Path to deno.exe, or None. Looks at PATH first, then at the usual install
    locations so a stale PATH (app launched before Deno was installed) does not
    matter."""
    deno = shutil.which("deno")
    if not deno:
        candidates = (
            os.path.join(os.path.expanduser("~"), ".deno", "bin", "deno.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "deno.exe"),
        )
        deno = next((p for p in candidates if os.path.isfile(p)), None)
    return deno


def js_runtime_args() -> list:
    """Passes Deno explicitly so yt-dlp does not depend on the PATH of this
    process. Only used for the "restricted" pass (see access_args)."""
    deno = find_deno()
    if not deno:
        logger.warning("Deno not found; age-restricted / members-only videos need it")
        return []
    return ["--js-runtimes", f"deno:{deno}"]


def access_args(restricted: bool) -> list:
    """Extra yt-dlp arguments for videos that need a signed-in session.

    restricted=False (normal videos): [] -> no cookies, no Deno.
    restricted=True (age-restricted / members-only): cookies + Deno.
    """
    if not restricted:
        return []
    cookies, runtime = cookie_args(), js_runtime_args()
    logger.debug("restricted pass: cookies=%s js_runtime=%s", cookies, runtime)
    return [*cookies, *runtime]

# Videos already found to be age-restricted / members-only in this session.
# The preview, the info extraction and a later retry for the same video go
# straight to the cookies + Deno pass instead of failing the normal one first
# (~3 s each). In-memory only: nothing is persisted.
_restricted_videos: set = set()
_restricted_lock = threading.Lock()
_VIDEO_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([\w-]{11})")


def _video_key(url: str) -> str:
    m = _VIDEO_ID_RE.search(url or "")
    return f"yt:{m.group(1)}" if m else (url or "").strip()


def _mark_restricted(url: str) -> None:
    with _restricted_lock:
        _restricted_videos.add(_video_key(url))


def _forget_restricted(url: str) -> None:
    with _restricted_lock:
        _restricted_videos.discard(_video_key(url))


def _is_known_restricted(url: str) -> bool:
    """True if this video was already seen as restricted AND the restricted
    pass is usable right now (cookies configured, Deno installed)."""
    with _restricted_lock:
        known = _video_key(url) in _restricted_videos
    return known and bool(cookie_args()) and find_deno() is not None


class AccessResult(NamedTuple):
    """Outcome of run_with_access_fallback()."""
    value: object     # what `attempt` returned on success, else None
    restricted: bool  # True if the last pass that ran was the restricted one
    errors: list      # error messages collected by that last pass


def run_with_access_fallback(url: str, attempt) -> AccessResult:
    """Runs `attempt` with the normal pass first, and with cookies + Deno only
    when the video turns out to need them.

    `attempt(restricted: bool, errors: list)` does ONE extraction pass.
    restricted=True means "use access_args(True)". On failure it appends the
    error message(s) to `errors` and returns None; on success it returns
    anything that is not None.

    Order of passes:
      1. If this video was already seen needing a login in this session (and
         the restricted pass is usable right now), go straight to the
         restricted pass instead of failing the normal one first. If that no
         longer works (cookies expired?), forget the video and continue.
      2. The normal pass: no cookies, no Deno.
      3. Only if pass 2 failed BECAUSE the video is age-restricted or
         members-only, and cookies are configured: the restricted pass.
         On success the video is remembered for step 1 next time.

    Raises DenoNotFoundError if step 3 is needed but Deno is not installed;
    callers decide whether to tell the user or just give up.

    `errors` in the result belong to the last pass that ran, which is the
    one worth showing the user.
    """
    if _is_known_restricted(url):
        errors = []
        value = attempt(True, errors)
        if value is not None:
            return AccessResult(value, True, errors)
        _forget_restricted(url)  # stale (cookies expired?): start over normally

    errors = []
    value = attempt(False, errors)
    if value is not None or not is_access_restricted_error(errors) or not cookie_args():
        # Success, an unrelated failure, or cookies are turned off: nothing to escalate.
        return AccessResult(value, False, errors)

    if not find_deno():
        raise DenoNotFoundError("Deno is required for age-restricted / members-only videos")

    logger.info("Restricted video detected; retrying with cookies + Deno")
    errors = []
    value = attempt(True, errors)
    if value is not None:
        _mark_restricted(url)
    return AccessResult(value, True, errors)
