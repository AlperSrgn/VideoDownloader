"""
Launching yt-dlp.exe for the --dump-json "info" commands, plus the one piece
of command line that info and download commands have in common.

  - run_hidden():             subprocess.run without a console window (Windows)
  - run_info_command():       runs an info command, returns stdout; on failure
                              raises YtDlpError carrying the full diagnostics
  - log_diagnostics():        writes those diagnostics to the log (callers do
                              this once the failure is final)
  - youtube_extractor_args(): the `--extractor-args` part of a command line
                              (used by ytdlp/info.py and downloading/downloader.py)

Download processes (progress parsing, pause/resume) are not started from here;
that is downloading/downloader.py.
"""

import logging
import os
import subprocess
import threading
import time

from cookie import describe_cookies

logger = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class YtDlpError(Exception):
    """Raised when yt-dlp.exe cannot be obtained or run, or returns no usable data.

    str(error) is the message classifiers and users see. `diagnostics` is the
    full multi-line report (command, cookie summary, complete yt-dlp output)
    for the log; it is empty for errors that have nothing more to say.
    """

    def __init__(self, message: str = "", diagnostics: str = ""):
        super().__init__(message)
        self.diagnostics = diagnostics


def run_hidden(cmd, **kwargs):
    return subprocess.run(cmd, creationflags=_NO_WINDOW, **kwargs)


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


# ---------------------------------------------------------------------------
# Diagnostics for the --dump-json info commands
# ---------------------------------------------------------------------------
# A failed info command is often EXPECTED: the normal pass of an age-restricted
# video fails on purpose before the cookies + Deno pass takes over. So a
# failure is not logged in full here. It only gets one short DEBUG line, and
# the full report (the exact command, a summary of the cookies that were
# configured, and ALL yt-dlp output including `-v` debug lines) travels on the
# YtDlpError as `.diagnostics`. Whoever knows the failure is final writes it
# out with log_diagnostics() (see ytdlp/access.py).
#
# The message of the YtDlpError carries the output WITHOUT the "[debug]" lines,
# so error classification is not confused by verbose noise.

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


def _error_summary(text: str, limit: int = 300) -> str:
    """One line for the short log message: yt-dlp's last ERROR line, else the
    last non-debug line."""
    lines = [l.strip() for l in _strip_debug_lines(text).splitlines() if l.strip()]
    errors = [l for l in lines if l.startswith("ERROR")]
    pick = errors[-1] if errors else (lines[-1] if lines else "no output")
    return pick if len(pick) <= limit else pick[: limit - 3] + "..."


def _cookie_summary_for(cmd: list) -> str:
    """Cookie summary for the log, but only if this command really sent cookies."""
    if "--cookies" in cmd or "--cookies-from-browser" in cmd:
        return describe_cookies()
    return "not sent (normal pass)"


def _diagnostics(label: str, headline: str, cmd: list, output: str) -> str:
    return (
        f"[{label}] {headline}\n"
        f"  command: {subprocess.list2cmdline(cmd)}\n"
        f"  cookies: {_cookie_summary_for(cmd)}\n"
        f"  yt-dlp output:\n{_indent(output.strip())}"
    )


def log_diagnostics(error: Exception) -> None:
    """Writes the full diagnostics of a YtDlpError to the log (WARNING).
    Does nothing for errors without any."""
    text = getattr(error, "diagnostics", "")
    if text:
        logger.warning("%s", text)


# yt-dlp WARNING lines (e.g. "formats skipped, SABR experiment") repeat on every
# extraction. The first occurrence is logged as a warning, repeats at DEBUG.
_seen_warnings: set = set()
_seen_warnings_lock = threading.Lock()


def _log_yt_dlp_warning(label: str, line: str) -> None:
    # The video id differs per video; the rest of the text identifies the warning.
    key = line.split(":", 2)[-1].strip() if line.count(":") >= 2 else line
    with _seen_warnings_lock:
        first = key not in _seen_warnings
        _seen_warnings.add(key)
    logger.log(logging.WARNING if first else logging.DEBUG, "[%s] %s", label, line)


def run_info_command(cmd: list, timeout: int, label: str) -> str:
    """Runs a yt-dlp info command and returns its stdout.
    Raises YtDlpError on failure/timeout; the error carries the full
    diagnostics, which the caller logs if the failure turns out to be final."""
    started = time.monotonic()
    try:
        result = run_hidden(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # avoid cp125x decode crashes on Windows
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        logger.debug("[%s] yt-dlp timed out after %ss", label, timeout)
        raise YtDlpError(
            f"yt-dlp timed out after {timeout}s",
            diagnostics=_diagnostics(
                label, f"yt-dlp timed out after {timeout}s", cmd, _to_text(e.stderr),
            ),
        ) from e
    except OSError as e:
        logger.debug("[%s] could not launch yt-dlp: %s", label, e)
        raise YtDlpError(
            f"Could not run yt-dlp: {e}",
            diagnostics=f"[{label}] could not launch yt-dlp: {e}\n"
                        f"  command: {subprocess.list2cmdline(cmd)}",
        ) from e

    elapsed = time.monotonic() - started
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0 or not stdout.strip():
        logger.debug(
            "[%s] yt-dlp failed (exit=%s, %.1fs): %s",
            label, result.returncode, elapsed, _error_summary(stderr),
        )
        raise YtDlpError(
            _strip_debug_lines(stderr) or "yt-dlp returned no data",
            diagnostics=_diagnostics(
                label, f"yt-dlp failed (exit={result.returncode}, {elapsed:.1f}s)",
                cmd, stderr,
            ),
        )

    for line in stderr.splitlines():
        if line.startswith("WARNING"):
            _log_yt_dlp_warning(label, line)
    logger.debug("[%s] yt-dlp ok (%.1fs)", label, elapsed)
    return stdout