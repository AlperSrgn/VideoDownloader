"""
Single source of truth for the app's quality/format options.

Before this, adding a quality option meant editing three places by hand:
RESOLUTION_MAP in downloader.py, three separate dicts/lists in main.py,
and the label in languages.py. This module collapses all of that except
translated labels (which have to stay in languages.py) into one list.

Most quality labels ("1080p ᴴᴰ", "720p", ...) are the same text in every
language, so they're just written directly as `label` below — no need to
touch languages.py for those. Only options whose label actually differs by
language (like "audio") use `lang_field` to look the label up from the
current language dict at display time. Give an option `label` OR
`lang_field`, not both.

To add a new option:
  1. Add one entry to QUALITY_OPTIONS below, with a `label` if the text is
     the same in every language, or a `lang_field` if it needs translation
     (in which case also add that field to every language dict in
     languages.py).
The dropdown order, the resolution lookup used for video
downloads, and the format tag (mp4/mp3) shown next to each option in the
dropdown are all derived from this list automatically.
"""

QUALITY_OPTIONS = [
    # key:    internal, language-independent id stored with each queue item
    # height: video pixel height passed to yt-dlp's format selection
    #         (None for audio-only — it has no resolution)
    # format: container format shown next to the label in the dropdown
    # label / lang_field: see module docstring above
    {"key": "4K",    "height": 2160, "format": "MP4    ", "label": "2160p ⁴ᴷ"},
    {"key": "2K",    "height": 1440, "format": "MP4    ", "label": "1440p ²ᴷ"},
    {"key": "1080p", "height": 1080, "format": "MP4    ", "label": "1080p ᴴᴰ"},
    {"key": "720p",  "height": 720,  "format": "MP4    ", "label": "720p"},
    {"key": "audio", "height": None, "format": "MP3    ", "lang_field": "audio"},
]

# Derived views used by downloader.py and main.py
QUALITY_OPTION_BY_KEY = {opt["key"]: opt for opt in QUALITY_OPTIONS}
RESOLUTION_MAP = {
    opt["key"]: opt["height"] for opt in QUALITY_OPTIONS if opt["height"] is not None
}
DROPDOWN_QUALITY_ORDER = [opt["key"] for opt in QUALITY_OPTIONS]
QUALITY_KEY_TO_FORMAT_TAG = {opt["key"]: opt["format"] for opt in QUALITY_OPTIONS}


# ---------------------------------------------------------------------------
# Display helpers (moved from main.py)
# ---------------------------------------------------------------------------
# The dropdown shows language-specific labels, but each queue item stores its
# selection as a language-independent key, so it stays valid if the language
# changes. `lang` is the current language dict from languages.py — passed in
# explicitly rather than read from a global, so this module has no dependency
# on main.py's state.

def quality_label(quality_key: str, lang: dict) -> str:
    """Turn a stored quality key back into a label in the given language,
    for display in the queue list.

    Most options have a fixed `label` (same text in every language); a few
    (like "audio") have a `lang_field` instead and are looked up from `lang`.
    """
    opt = QUALITY_OPTION_BY_KEY.get(quality_key)
    if not opt:
        return quality_key
    if "label" in opt:
        return opt["label"]
    return lang.get(opt.get("lang_field"), quality_key)


def quality_dropdown_text(quality_key: str, lang: dict) -> str:
    """Format tag (mp4/mp3) plus the label, as shown in the dropdown itself."""
    label = quality_label(quality_key, lang)
    tag = QUALITY_KEY_TO_FORMAT_TAG.get(quality_key, "")
    return f"{tag}    {label}" if tag else label


# Reverse lookup: exact composed dropdown text -> quality key. The display
# text is language-dependent (see quality_dropdown_text above), so this map
# is rebuilt every time the dropdown is repopulated in a new language, via
# build_dropdown_options() — called from main.py's change_language().
_dropdown_display_to_key: dict = {}


def build_dropdown_options(lang: dict) -> list:
    """Returns the dropdown's display strings, in DROPDOWN_QUALITY_ORDER, for
    the given language — and refreshes the reverse lookup used by
    resolve_quality_key() to match."""
    options = [quality_dropdown_text(key, lang) for key in DROPDOWN_QUALITY_ORDER]
    _dropdown_display_to_key.clear()
    _dropdown_display_to_key.update(zip(options, DROPDOWN_QUALITY_ORDER))
    return options


def resolve_quality_key(selection: str):
    """Turn the dropdown's current display text into a stable quality key,
    or None if it doesn't match anything (shouldn't normally happen)."""
    return _dropdown_display_to_key.get(selection)