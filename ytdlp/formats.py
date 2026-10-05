"""
Format selection: picking the video/audio format for a requested quality out
of the 'formats' list that yt-dlp's --dump-json produces.

Pure functions (no I/O, no yt-dlp process), so they are easy to unit test with
a hand-written list of format dicts.
"""

import logging

logger = logging.getLogger(__name__)


def _select_original_audio(audio_formats: list):
    """
    Selects the *original* audio track instead of an auto-dubbed one.

    yt-dlp tags audio formats with language and language_preference.
    The original track usually has the highest language_preference value.

    First, formats with the highest language_preference are selected;
    ties are then resolved by bitrate.
    """
    if not audio_formats:
        return None

    max_pref = max((f.get("language_preference") or -1) for f in audio_formats)
    original_candidates = [
        f for f in audio_formats
        if (f.get("language_preference") or -1) == max_pref
    ]
    chosen = max(original_candidates, key=lambda x: x.get("abr") or 0)

    logger.debug(
        "Original audio track selected: format=%s language=%s language_preference=%s abr=%s",
        chosen.get("format_id"), chosen.get("language"),
        chosen.get("language_preference"), chosen.get("abr"),
    )
    return chosen


def find_suitable_format(formats: list, video_height: int):
    """
    Return (video_format, audio_format) for the best available resolution
    at or below video_height. If nothing at or below video_height exists,
    falls back to the highest resolution available. Within a resolution the
    highest-tbr video and the original-language audio track are chosen.
    Returns (None, None) if there are no usable (url-bearing) video or audio
    formats — e.g. SABR-protected videos, whose formats come without a
    direct URL.
    """
    video_formats = [
        f for f in formats
        if f.get("url") and f.get("vcodec") != "none" and f.get("height") is not None
    ]
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]

    if not video_formats or not audio_formats:
        return None, None

    available_heights = sorted(
        {f["height"] for f in video_formats if f["height"] <= video_height},
        reverse=True
    )
    if not available_heights:
        available_heights = sorted({f["height"] for f in video_formats}, reverse=True)

    for h in available_heights:
        candidates = [f for f in video_formats if f.get("height") == h]
        if not candidates:
            continue

        chosen_video = max(candidates, key=lambda x: x.get("tbr") or 0)
        chosen_audio = _select_original_audio(audio_formats)

        if chosen_video.get("url") and chosen_audio and chosen_audio.get("url"):
            logger.debug(
                "Compatible formats found — Video: %s (%dp), Audio: %s",
                chosen_video["format_id"], h, chosen_audio["format_id"]
            )
            return chosen_video, chosen_audio
        else:
            logger.debug(
                "SABR protection detected for %s (%dp)", chosen_video["format_id"], h
            )
            return None, None

    return None, None


def find_suitable_audio_format(formats: list):
    """
    Returns the original audio track as (audio_format,) so it can be passed
    directly to find_info_with_compatible_format.

    Returns (None,) if no usable audio track is available, allowing the next
    client to be tried.
    """
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    return (_select_original_audio(audio_formats),)


# ---------------------------------------------------------------------------
# Fallback: progressive (single-file, video+audio) formats
# ---------------------------------------------------------------------------
# When YouTube forces SABR streaming (common for age-restricted videos and
# some accounts), the separate DASH video/audio streams come back without a
# URL and often only a progressive format (e.g. 18 = 360p mp4) remains. These
# helpers let callers use it as a last resort instead of failing outright.

def _progressive_formats(formats: list) -> list:
    return [
        f for f in formats
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("protocol") in ("https", "http")
    ]


def find_progressive_format(formats: list, video_height: int):
    """Fallback selector for video downloads. Returns (format, None); the
    None audio slot tells the caller this is a single-file download that
    needs no merge. Returns (None, None) if there is no progressive format."""
    candidates = [f for f in _progressive_formats(formats) if f.get("height")]
    if not candidates:
        return None, None
    pool = [f for f in candidates if f["height"] <= video_height] or candidates
    best = max(pool, key=lambda f: (f["height"], f.get("tbr") or 0))
    return best, None


def find_progressive_audio_format(formats: list):
    """Fallback selector for audio-only downloads: the smallest progressive
    format (least data to download); the audio is extracted from it later."""
    candidates = _progressive_formats(formats)
    if not candidates:
        return (None,)
    return (min(candidates, key=lambda f: f.get("height") or 10 ** 9),)
