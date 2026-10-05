"""
Cookie support: lets yt-dlp download age-restricted / members-only videos
by sending the user's signed-in YouTube session.

Where to look:

  options.py   What the dropdowns offer: the cookie modes and browsers, and
               the language-independent key <-> translated text mapping.
  store.py     The user's cookie settings and the app's own cookies.txt:
               import / export / delete, cookie_args() for yt-dlp, log summary.
  firefox.py   Reads Firefox's cookie database (finding the profile, copying
               the sqlite file, filtering to YouTube/Google).
  netscape.py  The cookies.txt file format, reading and writing.

Other code imports from this package, not from the modules above:

    from cookie import cookie_args, import_cookie_file, CookieExportError

Dependencies: only `settings` and the standard library. The yt-dlp side
(when cookies are actually used, and with Deno) is in ytdlp/access.py.
"""

from cookie.firefox import CookieExportError, ExportResult
from cookie.options import (
    COOKIE_BROWSERS,
    COOKIE_MODES,
    build_cookie_mode_options,
    cookie_mode_label,
    resolve_cookie_browser_key,
    resolve_cookie_mode_key,
)
from cookie.store import (
    cookie_args,
    cookie_file_exists,
    cookie_file_path,
    describe_cookies,
    export_cookies_from_firefox,
    get_cookie_browser,
    get_cookie_file_label,
    get_cookie_mode,
    import_cookie_file,
    remove_cookie_file,
    set_cookie_browser,
    set_cookie_mode,
)

__all__ = [
    "build_cookie_mode_options",
    "cookie_args",
    "COOKIE_BROWSERS",
    "cookie_file_exists",
    "cookie_file_path",
    "cookie_mode_label",
    "COOKIE_MODES",
    "CookieExportError",
    "describe_cookies",
    "export_cookies_from_firefox",
    "ExportResult",
    "get_cookie_browser",
    "get_cookie_file_label",
    "get_cookie_mode",
    "import_cookie_file",
    "remove_cookie_file",
    "resolve_cookie_browser_key",
    "resolve_cookie_mode_key",
    "set_cookie_browser",
    "set_cookie_mode",
]
