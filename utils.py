import glob
import logging
import os
import re
import shutil
import sys
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from settings import get_appdata_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

def copy_icons() -> None:
    """Copy icon files to AppData folder on first run."""
    dst_dir = get_appdata_path()
    src_dir = os.path.dirname(os.path.abspath(__file__))
    icons = ["notificationIcon.ico", "previewIcon.ico", "appIcon.ico"]

    for icon in icons:
        dst = os.path.join(dst_dir, icon)
        src = os.path.join(src_dir, icon)
        try:
            if not os.path.exists(dst) and os.path.exists(src):
                shutil.copy2(src, dst)
        except Exception as e:
            logger.error("Icon copy error (%s): %s", icon, e)


def get_icon_path(name: str) -> str:
    return os.path.join(get_appdata_path(), name)


# ---------------------------------------------------------------------------
# FFmpeg
# ---------------------------------------------------------------------------

def get_ffmpeg_path() -> str:
    """Return the correct ffmpeg binary path for both dev and packaged modes."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "ffmpeg-win-x86_64-v7.1.exe")
    project_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(
        project_dir, ".venv", "Lib", "site-packages",
        "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe"
    )


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

# Windows device names that are illegal as a filename stem, regardless of
# extension (e.g. "CON.mp4" is just as invalid as "CON").
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Characters Windows forbids in filenames, plus ASCII control characters.
# Unicode letters (Turkish, etc.) are deliberately left untouched — modern
# NTFS/Windows handles them fine, no need to transliterate to ASCII.
_WINDOWS_FORBIDDEN_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Conservative cap that leaves headroom for a " (n)" uniqueness suffix, the
# file extension, and the rest of the path (Windows' legacy MAX_PATH=260
# limit still bites unless long-path support is explicitly enabled).
MAX_FILENAME_LENGTH = 150


def sanitize_filename(name: str) -> str:
    """
    Make `name` safe to use as a Windows filename while preserving
    non-ASCII characters (Turkish, etc.) instead of transliterating them.
    Handles forbidden characters, reserved device names, trailing dots/
    spaces, and overly long names.
    """
    if not name:
        return "video"

    # Strip characters Windows forbids in filenames (also covers path
    # separators, so no directory traversal via the title).
    name = _WINDOWS_FORBIDDEN_CHARS_RE.sub("", name)

    # Collapse whitespace/newlines, then use underscores for readability.
    name = re.sub(r"\s+", " ", name).strip()
    name = name.replace(" ", "_")

    # Windows silently strips trailing dots/spaces from filenames — do it
    # ourselves so behavior is explicit rather than OS-dependent.
    name = name.rstrip(". ")

    # Guard against empty results and "." / ".." (special directory entries).
    if not name or set(name) <= {"."}:
        name = "video"

    # Reserved device names are invalid even with an extension attached
    # (e.g. "CON.mp4"), so check the stem only, case-insensitively.
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        name = f"_{name}"

    if len(name) > MAX_FILENAME_LENGTH:
        name = name[:MAX_FILENAME_LENGTH].rstrip(". _")
        if not name:
            name = "video"

    return name


def unique_filename(directory: str, filename: str) -> str:
    """Return a filename that does not conflict with existing files."""
    base, ext = os.path.splitext(filename)
    counter = 1
    candidate = filename
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base} ({counter}){ext}"
        counter += 1
    return candidate


def update_file_timestamp(filepath: str) -> None:
    if os.path.exists(filepath):
        now = time.time()
        os.utime(filepath, (now, now))


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def clean_playlist_url(url: str) -> str:
    """Strip playlist/radio parameters from a YouTube URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in ["list", "start_radio", "rv"]:
            params.pop(key, None)
        new_query = urlencode(params, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
    except Exception as e:
        logger.warning("URL cleaning failed, returning original. Error: %s", e)
        return url


def find_glob_file(pattern: str) -> str:
    """Return first glob match or raise FileNotFoundError with a clear message."""
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"No file matched pattern: {pattern}")
    return matches[0]