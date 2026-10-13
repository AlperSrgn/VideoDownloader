"""
Every yt-dlp command line the app builds, in one place:

  - build_info_cmd():      `--dump-json` for a video's metadata, either the full
                           extraction a download needs or the faster preview one
  - build_download_cmd():  one download phase (a video track, an audio track,
                           or an audio-only download)

ytdlp/info.py runs the info commands, downloading/downloader.py runs the
download ones; neither assembles a yt-dlp argument list itself. (ffmpeg
command lines are in downloading/ffmpeg_commands.py.)
"""

from typing import Optional

from utils import get_ffmpeg_path
from ytdlp.access import access_args
from ytdlp.runner import youtube_extractor_args


def build_info_cmd(exe_path: str, url: str, client: Optional[str],
                   restricted: bool = False, preview: bool = False) -> list:
    """Builds `yt-dlp --dump-json` for a given player client.

    preview=True tells yt-dlp to skip resolving the HLS/DASH adaptive-stream
    manifests (skip=hls,dash): each needs its own network round-trip to build
    the full 'formats' list, which the URL-paste preview never looks at (it
    only needs title/duration/thumbnail). A real download needs every format
    resolved, so it uses preview=False.

    No --no-warnings and -v on purpose: warnings (e.g. "cookies are no longer
    valid") and debug lines are only ever written to the log on failure.

    restricted=True (video that needs a login) adds the user's cookies, plus
    Deno on YouTube; normal videos get neither (see access_args).
    """
    # Pass `extra` only for the preview, so the full extraction calls
    # youtube_extractor_args exactly as before.
    extractor_kwargs = {"extra": "skip=hls,dash"} if preview else {}
    return [
        exe_path,
        "--dump-json",
        "-v",
        *access_args(restricted, url),
        *youtube_extractor_args(client, **extractor_kwargs),
        url,
    ]


def build_download_cmd(exe_path: str, format_id: str, client: Optional[str],
                       output_template: str, url: str,
                       restricted: bool = False,
                       use_ffmpeg: bool = False) -> list:
    """Builds a yt-dlp download command for one phase (a video track, an
    audio track, or an audio-only download) — only the format id and
    output template differ between call sites, so this is the one place
    that lists the flags all of them share.

    --continue is explicit even though it's yt-dlp's default: relaunching
    this exact command after a pause (see run_download's docstring in
    downloading/process_runner.py) relies on it resuming the partial file via
    an HTTP Range request instead of starting over, and this guards against a
    local yt-dlp config overriding that default.

    use_ffmpeg=True passes --ffmpeg-location: HLS (m3u8) segments arrive as
    raw MPEG-TS, which yt-dlp only turns into a real MP4 if it can find ffmpeg.

    restricted=True (video that needs a login) adds the user's cookies, plus
    Deno on YouTube; normal videos get neither (see access_args).
    """
    return [
        exe_path,
        "-f", format_id,
        *access_args(restricted, url),
        *youtube_extractor_args(client),
        *(["--ffmpeg-location", get_ffmpeg_path()] if use_ffmpeg else []),
        "--newline", "--no-warnings",
        "--continue",
        "-o", f"{output_template}.%(ext)s",
        url,
    ]