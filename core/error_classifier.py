"""
User-facing error classification for yt-dlp/ffmpeg failures.

yt-dlp/ffmpeg exit codes and raw process output are meaningless to an end
user (e.g. "yt-dlp exited with code 1"). This module turns that raw text
(or an OSError from a file operation) into one of a small set of
localized, actionable messages — falling back to yt-dlp/ffmpeg's own
error text when nothing more specific is recognized, rather than a vague
generic message. The original raw text is only logged (logger.debug) for
troubleshooting; it is never shown to the user directly.

Split out of downloader.py, which was growing long with this being a
self-contained concern (parsing/classifying text) rather than part of the
actual download/merge process handling.
"""

import errno
import logging
import re
import socket

logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
    pass


class DownloadStalled(Exception):
    """Raised when yt-dlp produces no output during the stall timeout.
    Detects stuck local processing and prevents the app from hanging indefinitely.
    """
    pass


class DenoNotFoundError(Exception):
    """An age-restricted / members-only video needs cookies + Deno, but Deno
    could not be found on this machine. Deno is only required for those
    videos; normal videos never need it."""
    pass


class YtDlpProcessError(Exception):
    """yt-dlp.exe exited with a non-zero code. Carries the raw captured
    output (stdout+stderr merged) so the caller can classify *why* it
    failed into a user-facing message instead of just showing the exit
    code."""

    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output
        super().__init__(f"yt-dlp exited with code {returncode}")


class FfmpegProcessError(Exception):
    """ffmpeg exited with a non-zero code. Carries the raw captured stderr
    so the caller can classify *why* it failed (disk space, permissions,
    codec issues, etc.) into a user-facing message."""

    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = output
        super().__init__(f"ffmpeg exited with code {returncode}")


# ---------------------------------------------------------------------------
# User-facing error classification
# ---------------------------------------------------------------------------
# yt-dlp/ffmpeg exit codes and raw process output are meaningless to an end
# user (e.g. "yt-dlp exited with code 1"). These helpers turn the raw text
# yt-dlp/ffmpeg printed (or an OSError) into one of a small set of
# localized, actionable messages. The original raw text is only logged
# (logger.debug) for troubleshooting — it is not shown to the user.

def _build_error_message(lang: dict, friendly_text: str, technical_detail: str = "") -> str:
    if technical_detail:
        logger.debug("Underlying error detail: %s", technical_detail.strip())
    return friendly_text


_CONNECTIVITY_CHECK_TIMEOUT = 3  # seconds

def _has_internet_connection() -> bool:
    """Quick check to distinguish DNS-resolution failures:
    A mistyped/nonexistent domain (e.g. "a.com") can produce the same
    "getaddrinfo failed" error as an offline machine, so the error text alone
    isn't enough.
    Connects directly to Google's DNS server by IP (8.8.8.8:53), avoiding DNS
    lookup. If offline, it fails almost instantly, adding negligible delay.
    """
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=_CONNECTIVITY_CHECK_TIMEOUT).close()
        return True
    except OSError:
        return False


# DNS-resolution failures need the live check above before they can be
# classified — see _has_internet_connection(). Other network errors
# (refused/timed-out connections, "network unreachable") are kept
# separate: these come back from a host that DID resolve, so they're
# reliable "no internet / connection problem" signals on their own.
_DNS_FAILURE_PATTERNS = (
    "getaddrinfo failed", "failed to resolve", "name or service not known",
    "temporary failure in name resolution",
)
_OTHER_NETWORK_ERROR_PATTERNS = (
    "network is unreachable", "connection refused",
    "urlopen error", "connection timed out",
)

# yt-dlp's message for channel-membership videos, e.g. "Join this channel to
# get access to members-only content like this video, and other exclusive
# perks." or "This video is available to this channel's members on level: ...".
_MEMBERS_ONLY_PATTERNS = (
    "members-only", "members only", "join this channel",
    "available to this channel's members",
)

# HTTP status codes are only trusted when they appear in an HTTP-error
# context. A bare "404"/"429" substring would also match video IDs, URL
# fragments, byte counts or titles that yt-dlp prints (e.g. "watch?v=ab404xQ").
# Covers yt-dlp ("HTTP Error 404: Not Found") and ffmpeg ("Server returned
# 404 Not Found", "HTTP error 404").
_HTTP_STATUS_RE = re.compile(
    r"(?:http error|server returned|returned http status|status code:?)\s*(\d{3})\b"
)


def _http_status(text: str):
    """Return the HTTP status code (int) mentioned in an HTTP-error context
    in the lowercased error text, or None."""
    m = _HTTP_STATUS_RE.search(text)
    return int(m.group(1)) if m else None


def _contains_any(*patterns: str):
    """Build a rule predicate that matches if any pattern is a substring."""
    return lambda text: any(p in text for p in patterns)


def _resolve_dns_failure() -> str:
    """A DNS failure is ambiguous: offline machine vs. a mistyped/nonexistent
    domain. Only evaluated when a DNS rule actually matched, so the (up to
    3 s) connectivity check is never run for unrelated errors."""
    if _has_internet_connection():
        return "error_unsupported_url"
    return "error_no_internet"


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------
# Ordered table of (key, predicate). The FIRST matching rule wins, so the
# order here IS the priority — no need to track it in comments. To support a
# new error: add one line at the right position. `key` is either a lang-dict
# key (str) or a zero-arg callable that returns one (resolved lazily, only
# when the rule matches). `predicate` receives the lowercased error text.
#
# Ordering notes:
#   * Network/DNS first: when the connection is the problem, everything else
#     in the output is noise.
#   * members-only is before the access-blocked (429/bot) and not-found
#     rules so a members-only error is never mistaken for them.
_RULES = (
    # --- connectivity ---
    (_resolve_dns_failure,       _contains_any(*_DNS_FAILURE_PATTERNS)),
    ("error_no_internet",        _contains_any(*_OTHER_NETWORK_ERROR_PATTERNS)),

    # --- needs a signed-in account / cookies ---
    ("error_cookies_unreadable", lambda t: ("could not copy" in t and "cookie" in t)
                                           or "failed to decrypt" in t
                                           or "dpapi" in t
                                           or "cookie database" in t),
    ("error_age_restricted",     _contains_any("sign in to confirm your age", "age-restricted")),
    ("error_members_only",       _contains_any(*_MEMBERS_ONLY_PATTERNS)),

    # --- blocked / rate-limited ---
    ("error_access_blocked",     lambda t: "sign in to confirm you're not a bot" in t
                                           or "too many requests" in t
                                           or _http_status(t) == 429),

    # --- video itself ---
    ("error_video_private",      _contains_any("private video", "this video is private")),
    ("error_video_not_found",    lambda t: "video unavailable" in t
                                           or "no longer available" in t
                                           or "content isn't available" in t
                                           or _http_status(t) == 404),
    ("error_unsupported_url",    _contains_any("unsupported url")),
    ("error_format_not_found",   _contains_any("requested format is not available",
                                               "no video formats found")),

    # --- local file system ---
    ("error_disk_full",          _contains_any("no space left on device")),
    ("error_permission",         _contains_any("permission denied")),
)


def _match_error_key(text: str):
    """Return the lang-dict key that best describes this raw yt-dlp/ffmpeg
    error text (lowercased), or None if nothing matches. Shared by every
    classification helper below so the same patterns are recognized
    whether they show up in a failed download process, a failed ffmpeg
    merge, or a failed --dump-json info extraction.

    The first matching rule in _RULES wins (see the table above)."""
    if not text:
        return None
    for key, predicate in _RULES:
        if predicate(text):
            return key() if callable(key) else key
    return None


# Errors that justify the "restricted" retry: cookies + Deno are only brought
# in when yt-dlp reports one of these (videos that need a signed-in account).
# Add keys here if more cases should escalate.
_COOKIE_ESCALATION_KEYS = ("error_age_restricted", "error_members_only", "error_video_private")


def is_access_restricted_error(errors) -> bool:
    """True if yt-dlp's error text(s) say the video is age-restricted or
    members-only, i.e. a retry with cookies (+ Deno) may succeed."""
    if isinstance(errors, str):
        errors = [errors]
    combined = "\n".join(e for e in (errors or []) if e).lower()
    return _match_error_key(combined) in _COOKIE_ESCALATION_KEYS


# yt-dlp prefixes errors with the extractor name and content ID.
# This is unnecessary for users, so we strip it and use yt-dlp's
# original message when _match_error_key finds no known error.
_YTDLP_ERROR_PREFIX_RE = re.compile(r"^error:\s*(?:\[[^\]]+\]\s*[^:]+:\s*)?", re.IGNORECASE)


def _extract_ytdlp_reason(output: str) -> str:
    """Return the first unique human-readable reason from yt-dlp "ERROR: ..." lines,
    stripping the "[extractor] id:" prefix. Returns "" if none is found."""
    if not output:
        return ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.upper().startswith("ERROR:"):
            continue
        reason = _YTDLP_ERROR_PREFIX_RE.sub("", line, count=1).strip()
        if reason:
            return reason
    return ""


def classify_ytdlp_error(output: str, returncode: int, lang: dict) -> str:
    """Map yt-dlp's raw output text to a localized, user-facing message."""
    text = (output or "").lower()
    key = _match_error_key(text)
    if key:
        friendly = lang.get(key, "An unknown error occurred during download.")
    else:
        friendly = _extract_ytdlp_reason(output) or lang.get(
            "error_unknown_ytdlp", "An unknown error occurred during download."
        )
    technical = output.strip() or f"exit code {returncode}"
    return _build_error_message(lang, friendly, technical)


def _extract_ffmpeg_reason(output: str) -> str:
    """ffmpeg doesn't use an "ERROR:" prefix like yt-dlp; its actual error is
    usually the last non-empty line written to stderr. Used as a fallback when
    the error doesn't match a known category."""

    lines = [l.strip() for l in (output or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def classify_ffmpeg_error(output: str, returncode: int, lang: dict) -> str:
    """Map ffmpeg's raw stderr text to a localized, user-facing message."""
    text = (output or "").lower()
    key = _match_error_key(text)
    if key:
        friendly = lang.get(key, "An error occurred while merging the video and audio.")
    else:
        friendly = _extract_ffmpeg_reason(output) or lang.get(
            "error_ffmpeg_generic", "An error occurred while merging the video and audio."
        )
    technical = output.strip() or f"exit code {returncode}"
    return _build_error_message(lang, friendly, technical)


def classify_extraction_failure(errors: list, lang: dict, fallback_key: str) -> str:
    """Translate known format errors to clear messages; otherwise use yt-dlp's
    original error text. If no error is raised, use `fallback_key` for the
    generic invalid-link/platform-protection message."""

    combined = "\n".join(e for e in errors if e)

    if combined:
        logger.debug("Format extraction failed across all clients: %s", combined)

    key = _match_error_key(combined.lower())
    if key:
        return lang.get(key, lang[fallback_key])

    reason = _extract_ytdlp_reason(combined)
    if reason:
        return reason

    return lang[fallback_key]


def classify_generic_exception(exc: Exception, lang: dict) -> str:
    """Fallback classification for non-yt-dlp/ffmpeg errors,
    such as OSError from file operations (disk full, permissions, etc.).
    """

    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return _build_error_message(
                lang, lang.get("error_disk_full", "Not enough disk space."), str(exc)
            )
        if isinstance(exc, PermissionError) or exc.errno == errno.EACCES:
            return _build_error_message(
                lang, lang.get("error_permission", "Permission denied while writing the file."), str(exc)
            )

    friendly = lang.get("unexpected_error_message", "An unexpected error occurred. Please try again.")
    technical = str(exc) or exc.__class__.__name__
    return _build_error_message(lang, friendly, technical)


def _is_network_error(exc: Exception) -> bool:
    """True if this exception looks like a lack-of-connectivity failure
    (DNS resolution, connection refused/reset, timeout, etc.) rather than
    something else."""
    text = str(exc).lower()
    return any(p in text for p in (
        "getaddrinfo failed", "failed to resolve", "name or service not known",
        "network is unreachable", "connection refused", "urlopen error",
        "temporary failure in name resolution", "timed out", "connection reset",
    ))


def _short_detail(exc: Exception, max_len: int = 160) -> str:
    """Short, length-capped exception text for fallback messages, giving users a concrete error to report."""
    text = str(exc).strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[:max_len - 1].rstrip() + "…"
    return text or exc.__class__.__name__


def classify_ytdlp_download_error(exc: Exception, lang: dict) -> str:
    """Maps a first-run yt-dlp.exe download error to a user-friendly message.
    Clearly identifies no internet connection; for other errors (permissions, disk, GitHub, antivirus, etc.),
    shows the actual error. The download button remains disabled until a successful retry.
    """
    if _is_network_error(exc):
        return _build_error_message(
            lang, lang.get("error_no_internet", "No internet connection."), str(exc)
        )

    friendly = lang.get(
        "ytdlp_setup_failed_generic_message",
        "Couldn't download yt-dlp. Please try again. Error: {error}",
    )
    return _build_error_message(lang, friendly.replace("{error}", _short_detail(exc)), str(exc))


def classify_ytdlp_update_error(exc: Exception, lang: dict) -> str:
    """ Show errors from the yt-dlp.exe update check as a localized NOTICE, not a blocking error.
    Continue using the existing yt-dlp.exe and keep the download button enabled.
    If there’s no internet, just inform the user; otherwise, include the actual error message.
    """
    if _is_network_error(exc):
        return _build_error_message(
            lang, lang.get("ytdlp_update_failed_network_message",
                            "yt-dlp couldn't be updated (no internet). Using the existing version."),
            str(exc),
        )

    friendly = lang.get(
        "ytdlp_update_failed_generic_message",
        "yt-dlp couldn't be updated. Using the existing version. Error: {error}",
    )
    return _build_error_message(lang, friendly.replace("{error}", _short_detail(exc)), str(exc))