"""Cookie support: language-independent keys <-> dropdown texts.
Same idea as core/quality_options.py: settings store the key, the
dropdown shows the translated text."""

COOKIE_MODES = ("none", "browser", "file", "firefox_export")

# The modes that send the app's own cookies.txt to yt-dlp: "file" (a cookies.txt
# the user picked) and "firefox_export" (one the app created from Firefox).
FILE_MODES = ("file", "firefox_export")

# key (as passed to yt-dlp) -> display name
COOKIE_BROWSERS = {
    "firefox": "Firefox",
    "edge": "Edge",
    "chrome": "Chrome",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
    "chromium": "Chromium",
}


def cookie_mode_label(key: str, lang: dict) -> str:
    return lang.get(f"cookie_mode_{key}", key)


def build_cookie_mode_options(lang: dict) -> list:
    return [cookie_mode_label(k, lang) for k in COOKIE_MODES]


def resolve_cookie_mode_key(text: str, lang: dict):
    """Dropdown text -> mode key, or None if it doesn't match (e.g. the
    var is still empty at startup)."""
    for key in COOKIE_MODES:
        if cookie_mode_label(key, lang) == text:
            return key
    return None


def resolve_cookie_browser_key(text: str):
    key = (text or "").lower()
    return key if key in COOKIE_BROWSERS else None