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

logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
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


def _match_error_key(text: str):
    """Return the lang-dict key that best describes this raw yt-dlp/ffmpeg
    error text (lowercased), or None if nothing matches. Shared by every
    classification helper below so the same patterns are recognized
    whether they show up in a failed download process, a failed ffmpeg
    merge, or a failed --dump-json info extraction."""
    if not text:
        return None

    if any(p in text for p in (
        "getaddrinfo failed", "failed to resolve", "name or service not known",
        "network is unreachable", "connection refused", "urlopen error",
        "temporary failure in name resolution", "connection timed out",
    )):
        return "error_no_internet"
    if "sign in to confirm your age" in text or "age-restricted" in text:
        return "error_age_restricted"
    if ("sign in to confirm you're not a bot" in text or "429" in text
            or "too many requests" in text):
        return "error_access_blocked"
    if "private video" in text or "this video is private" in text:
        return "error_video_private"
    if ("video unavailable" in text or "no longer available" in text
            or "content isn't available" in text or "404" in text):
        return "error_video_not_found"
    if "requested format is not available" in text or "no video formats found" in text:
        return "error_format_not_found"
    if "no space left on device" in text:
        return "error_disk_full"
    if "permission denied" in text:
        return "error_permission"
    return None


# yt-dlp prefixes every one of its own error lines with the extractor name
# and the video/tweet/etc. id, e.g.:
#   "ERROR: [youtube:truncated_id] 7o28a2W: Incomplete YouTube ID ..."
#   "ERROR: [twitter] 2090393104142528953: No video could be found in this tweet"
# That "[extractor] id:" part is meaningless to an end user; the text after
# it is usually already a perfectly readable sentence on its own. Rather
# than hand-writing a friendly message for every possible extractor error
# (there are hundreds of sites/edge-cases), we strip that prefix and use
# yt-dlp's own wording as the fallback whenever _match_error_key doesn't
# recognize the case as one of our known categories.
_YTDLP_ERROR_PREFIX_RE = re.compile(r"^error:\s*(?:\[[^\]]+\]\s*[^:]+:\s*)?", re.IGNORECASE)


def _extract_ytdlp_reason(output: str) -> str:
    """Return the first (de-duplicated) human-readable reason found in
    yt-dlp's raw "ERROR: ..." lines, with the "[extractor] id:" prefix
    stripped off. Returns "" if no ERROR line is present — e.g. the raw
    text was a plain traceback, in which case there's nothing readable to
    surface and the caller should fall back to a generic message instead.
    """
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
    """
    Called when no client can find a usable format.

    Known errors are translated into clear messages, while unknown errors
    fall back to yt-dlp's original error text.

    If no error is raised but no compatible format is found, `fallback_key`
    is used for the generic "invalid link or platform protection" message.
    """

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
