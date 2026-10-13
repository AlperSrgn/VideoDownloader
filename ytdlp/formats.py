"""
Format selection: picking the video/audio format for a requested quality out
of the 'formats' list that yt-dlp's --dump-json produces.

Every selector returns a `Selection` (or None when nothing usable exists), so
callers never have to guess what a tuple like (video, None) means.

Pure functions (no I/O, no yt-dlp process), so they are easy to unit test with
a hand-written list of format dicts.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Literal, Optional

logger = logging.getLogger(__name__)

SelectionKind = Literal["separate", "muxed", "audio_only"]


def resolution_of(f: dict) -> int:
    """Quality label of a format in pixels: the SHORTER side.

    Platforms label quality by the short side ("720p" is 1280x720 landscape and
    720x1280 portrait), so portrait videos (Shorts, Reels, TikTok) must not be
    judged by `height`, which is their long side. Falls back to whichever side
    is known; 0 if neither is (e.g. audio-only formats).
    """
    sides = [v for v in (f.get("height"), f.get("width")) if v]
    return min(sides) if sides else 0


@dataclass(frozen=True)
class Selection:
    """What to download, as decided by a selector.

    kind == "separate":  `video` and `audio` are separate streams; download both
                         and merge them with ffmpeg.
    kind == "muxed":     `video` is ONE file that already contains video + audio
                         (progressive https, or HLS); no merge needed. `audio`
                         is None.
    kind == "audio_only": `audio` is the track to download; `video` is None.
                         It may itself be a muxed format when no audio-only
                         stream exists (see `audio_from_muxed`).

    Build one with Selection.separate / .muxed / .audio_only; the constructor
    rejects combinations that do not fit `kind`.
    """
    kind: SelectionKind
    video: Optional[dict] = None
    audio: Optional[dict] = None

    def __post_init__(self):
        valid = {
            "separate": self.video is not None and self.audio is not None,
            "muxed": self.video is not None and self.audio is None,
            "audio_only": self.audio is not None and self.video is None,
        }.get(self.kind, False)
        if not valid:
            raise ValueError(
                f"Selection(kind={self.kind!r}) has an inconsistent "
                f"video/audio combination"
            )

    @classmethod
    def separate(cls, video: dict, audio: dict) -> "Selection":
        return cls("separate", video=video, audio=audio)

    @classmethod
    def muxed(cls, video: dict) -> "Selection":
        return cls("muxed", video=video)

    @classmethod
    def audio_only(cls, audio: dict) -> "Selection":
        return cls("audio_only", audio=audio)

    @property
    def height(self) -> int:
        """Video quality in pixels (short side, see resolution_of); 0 for
        audio-only selections. Name kept for existing callers."""
        return resolution_of(self.video) if self.video else 0

    @property
    def primary(self) -> dict:
        """The format that determines quality: the video, else the audio."""
        return self.video or self.audio

    @property
    def audio_from_muxed(self) -> bool:
        """True for an audio_only selection whose format also carries video
        (the audio has to be extracted from it afterwards)."""
        return (
            self.kind == "audio_only"
            and self.audio.get("vcodec") not in (None, "none")
        )


# A selector takes yt-dlp's 'formats' list and returns a Selection or None.
FormatSelector = Callable[[list], Optional[Selection]]


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


def find_suitable_format(formats: list, video_height: int) -> Optional[Selection]:
    """
    Separate video + audio streams for the best available resolution at or
    below video_height; if nothing at or below exists, the highest resolution
    available. Within a resolution the highest-tbr video and the
    original-language audio track are chosen.
    Returns None if there are no usable (url-bearing) video or audio formats
    -- e.g. SABR-protected videos, whose formats come without a direct URL.
    """
    video_formats = [
        f for f in formats
        if f.get("url") and f.get("vcodec") != "none" and resolution_of(f) > 0
    ]
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]

    if not video_formats or not audio_formats:
        return None

    heights = {resolution_of(f) for f in video_formats}
    at_or_below = [h for h in heights if h <= video_height]
    height = max(at_or_below) if at_or_below else max(heights)

    chosen_video = max(
        (f for f in video_formats if resolution_of(f) == height),
        key=lambda x: x.get("tbr") or 0,
    )
    chosen_audio = _select_original_audio(audio_formats)

    logger.debug(
        "Compatible formats found — Video: %s (%dp), Audio: %s",
        chosen_video["format_id"], height, chosen_audio["format_id"],
    )
    return Selection.separate(chosen_video, chosen_audio)


def find_suitable_audio_format(formats: list) -> Optional[Selection]:
    """The original audio track as an audio_only Selection, or None if no
    usable audio-only stream exists (so the next client can be tried)."""
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]
    chosen = _select_original_audio(audio_formats)
    return Selection.audio_only(chosen) if chosen else None


# ---------------------------------------------------------------------------
# Fallback: muxed (single-file, video+audio) formats
# ---------------------------------------------------------------------------
# When YouTube forces SABR streaming (common for age-restricted videos and
# some accounts), the separate DASH video/audio streams come back without a
# URL. What remains are muxed formats: the plain-https 18 (360p mp4) and,
# with the web_safari client, HLS streams (m3u8_native) up to 1080p. These
# selectors let callers use them as a last resort instead of failing.
#
# NOTE: HLS downloads are raw MPEG-TS until yt-dlp's ffmpeg fixup remuxes
# them, so the download command must be given --ffmpeg-location.

_HTTP_PROTOCOLS = ("https", "http")
_MUXED_PROTOCOLS = (*_HTTP_PROTOCOLS, "m3u8_native")


def _muxed_formats(formats: list) -> list:
    return [
        f for f in formats
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("protocol") in _MUXED_PROTOCOLS
    ]


def find_progressive_format(formats: list, video_height: int) -> Optional[Selection]:
    """Fallback selector for video downloads: the best muxed format at or
    below video_height (or the lowest-above if nothing fits). At equal height
    plain https wins over HLS, then the higher bitrate. Returns None if there
    is no muxed format at all."""
    candidates = [f for f in _muxed_formats(formats) if resolution_of(f) > 0]
    if not candidates:
        return None
    pool = [f for f in candidates if resolution_of(f) <= video_height] or candidates
    best = max(pool, key=lambda f: (
        resolution_of(f), f.get("protocol") in _HTTP_PROTOCOLS, f.get("tbr") or 0,
    ))
    return Selection.muxed(best)


def find_progressive_audio_format(formats: list) -> Optional[Selection]:
    """Fallback selector for audio-only downloads: the smallest muxed format
    (least data to download), preferring plain https because the HLS ones
    carry low-bitrate HE-AAC. The audio is extracted from it later."""
    candidates = _muxed_formats(formats)
    if not candidates:
        return None
    pool = [f for f in candidates if f.get("protocol") in _HTTP_PROTOCOLS] or candidates
    return Selection.audio_only(min(pool, key=lambda f: resolution_of(f) or 10 ** 9))