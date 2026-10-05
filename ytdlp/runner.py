"""
Launching yt-dlp.exe for the --dump-json "info" commands, plus the one piece
of command line that info and download commands have in common.

  - run_hidden():             subprocess.run without a console window (Windows)
  - run_info_command():       runs an info command, returns stdout, and on failure
                              logs the full diagnostics before raising YtDlpError
  - youtube_extractor_args(): the `--extractor-args` part of a command line
                              (used by ytdlp/info.py and downloading/downloader.py)

Download processes (progress parsing, pause/resume) are not started from here;
that is downloading/downloader.py.
"""

import logging
import os
import subprocess
import time

from cookie import describe_cookies

logger = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class YtDlpError(Exception):
    """Raised when yt-dlp.exe cannot be obtained or run, or returns no usable data."""


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
# On failure the FULL yt-dlp output (including `-v` debug lines, WARNING lines
# and the ERROR line) is written to the log together with the exact command
# and a summary of the cookies that were configured. The YtDlpError that
# callers/classifiers see carries the output WITHOUT the "[debug]" lines, so
# error classification is not confused by verbose noise.

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


def _cookie_summary_for(cmd: list) -> str:
    """Cookie summary for the log, but only if this command really sent cookies."""
    if "--cookies" in cmd or "--cookies-from-browser" in cmd:
        return describe_cookies()
    return "not sent (normal pass)"


def run_info_command(cmd: list, timeout: int, label: str) -> str:
    """Runs a yt-dlp info command and returns its stdout.
    Raises YtDlpError on failure/timeout, after logging full diagnostics."""
    started = time.monotonic()
    try:
        result = run_hidden(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",  # avoid cp125x decode crashes on Windows
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "[%s] yt-dlp timed out after %ss\n  command: %s\n  cookies: %s\n  partial output:\n%s",
            label, timeout, subprocess.list2cmdline(cmd), _cookie_summary_for(cmd),
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
            _cookie_summary_for(cmd), _indent(stderr.strip()),
        )
        raise YtDlpError(_strip_debug_lines(stderr) or "yt-dlp returned no data")

    for line in stderr.splitlines():
        if line.startswith("WARNING"):
            logger.warning("[%s] %s", label, line)
    logger.debug("[%s] yt-dlp ok (%.1fs)", label, elapsed)
    return stdout
