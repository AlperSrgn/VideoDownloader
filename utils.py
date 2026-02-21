import glob
import logging
import os
import re
import shutil
import sys
import time
import unicodedata
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

def sanitize_filename(name: str) -> str:
    """Remove Turkish chars and special symbols unsafe for filenames."""
    name = name.replace("ı", "i")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("utf-8")
    name = re.sub(r"[^\w\s.-]", "", name)
    name = name.replace(" ", "_")
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
