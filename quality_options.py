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
    {"key": "4K",    "height": 2160, "format": "mp4", "label": "2160p ⁴ᴷ"},
    {"key": "2K",    "height": 1440, "format": "mp4", "label": "1440p ²ᴷ"},
    {"key": "1080p", "height": 1080, "format": "mp4", "label": "1080p ᴴᴰ"},
    {"key": "720p",  "height": 720,  "format": "mp4", "label": "720p"},
    {"key": "audio", "height": None, "format": "mp3", "lang_field": "audio"},
]

# Derived views used by downloader.py and main.py
QUALITY_OPTION_BY_KEY = {opt["key"]: opt for opt in QUALITY_OPTIONS}
RESOLUTION_MAP = {
    opt["key"]: opt["height"] for opt in QUALITY_OPTIONS if opt["height"] is not None
}
DROPDOWN_QUALITY_ORDER = [opt["key"] for opt in QUALITY_OPTIONS]
QUALITY_KEY_TO_FORMAT_TAG = {opt["key"]: opt["format"] for opt in QUALITY_OPTIONS}