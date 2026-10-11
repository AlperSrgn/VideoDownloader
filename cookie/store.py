"""
The user's cookie settings and the app's own copy of cookies.txt.

Everything the rest of the app needs to know about cookies goes through here
(re-exported by cookie/__init__.py):

  - the settings keys and their defaults (cookie_mode, cookie_browser,
    cookie_file_name) -- nobody else reads or writes those keys directly
  - where the app's cookies.txt lives (cookie_file_path)
  - turning the user's choice into yt-dlp arguments (cookie_args)
  - importing / exporting / deleting that file
  - a one-line description for the log (describe_cookies), never with values

There is no UI in here. Failures are raised (OSError, CookieExportError) and
the caller decides which dialog to show.
"""

import logging
import os
import shutil
import time

from cookie.firefox import ExportResult, export_firefox_cookies
from cookie.netscape import summarize_cookie_file
from cookie.options import COOKIE_BROWSERS, FILE_MODES
from settings import get_appdata_path, load_setting, save_setting

logger = logging.getLogger(__name__)

COOKIE_FILE_NAME = "cookies.txt"

# config.json keys
_MODE_KEY = "cookie_mode"
_BROWSER_KEY = "cookie_browser"
_FILE_LABEL_KEY = "cookie_file_name"  # name shown in the sidebar, not a path

DEFAULT_MODE = "none"
DEFAULT_BROWSER = "firefox"
NO_FILE_LABEL = "\u2014"  # em dash: "no file chosen yet"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_cookie_mode() -> str:
    """Raw saved mode key; one of options.COOKIE_MODES unless config.json was edited by hand."""
    return load_setting(_MODE_KEY, DEFAULT_MODE)


def set_cookie_mode(mode: str) -> None:
    save_setting(_MODE_KEY, mode)


def get_cookie_browser() -> str:
    """Raw saved browser key (see options.COOKIE_BROWSERS)."""
    return load_setting(_BROWSER_KEY, DEFAULT_BROWSER)


def set_cookie_browser(browser: str) -> None:
    save_setting(_BROWSER_KEY, browser)


def get_cookie_file_label() -> str:
    """File name to show in the sidebar (NO_FILE_LABEL if there is none)."""
    return load_setting(_FILE_LABEL_KEY, NO_FILE_LABEL)


# ---------------------------------------------------------------------------
# The app's own cookies.txt
# ---------------------------------------------------------------------------

def cookie_file_path() -> str:
    return os.path.join(get_appdata_path(), COOKIE_FILE_NAME)


def cookie_file_exists() -> bool:
    return os.path.isfile(cookie_file_path())


def import_cookie_file(src_path: str) -> None:
    """Copies a cookies.txt the user picked into the app's own cookies.txt.
    Raises OSError if the copy fails.

    The app works on the copy, never on the original: yt-dlp overwrites the
    cookie file when it exits, and the user's file must stay untouched."""
    shutil.copy2(src_path, cookie_file_path())
    save_setting(_FILE_LABEL_KEY, os.path.basename(src_path))


def export_cookies_from_firefox() -> ExportResult:
    """Exports the YouTube/Google cookies of the user's Firefox into the app's
    own cookies.txt. Raises CookieExportError if that is not possible."""
    result = export_firefox_cookies(cookie_file_path())
    save_setting(_FILE_LABEL_KEY, os.path.basename(result.path))
    return result


def remove_cookie_file() -> None:
    """Deletes the app's own cookies.txt (a file the user imported is only a
    copy, so their original is never touched). Raises OSError on failure."""
    os.remove(cookie_file_path())
    save_setting(_FILE_LABEL_KEY, NO_FILE_LABEL)


# ---------------------------------------------------------------------------
# For yt-dlp
# ---------------------------------------------------------------------------

def cookie_args() -> list:
    """yt-dlp command-line arguments for the user's cookie settings
    ([] = do not use cookies)."""
    mode = get_cookie_mode()
    args = []
    if mode == "browser":
        browser = get_cookie_browser()
        if browser in COOKIE_BROWSERS:
            args = ["--cookies-from-browser", browser]
        else:
            logger.warning("cookie_mode=browser but browser %r is not supported; no cookies sent", browser)
    elif mode in FILE_MODES:
        path = cookie_file_path()
        if os.path.isfile(path):
            args = ["--cookies", path]
        else:
            logger.warning("cookie_mode=%s but %s does not exist; no cookies sent", mode, path)
    return args


def describe_cookies() -> str:
    """One-line description of the configured cookies for the log.
    Never includes cookie values."""
    mode = get_cookie_mode()
    if mode == "browser":
        return f"mode=browser, browser={get_cookie_browser()}"
    if mode not in FILE_MODES:
        return f"mode={mode} (no cookies sent)"

    path = cookie_file_path()
    try:
        age_min = int((time.time() - os.path.getmtime(path)) / 60)
        summary = summarize_cookie_file(path)
    except OSError as e:
        return f"mode={mode}, cannot read {path}: {e}"

    return (
        f"mode={mode}, {summary.total} cookies ({summary.expired} expired), "
        f"login cookies present: {sorted(summary.login_names) or 'NONE'}, "
        f"file modified {age_min} min ago"
    )