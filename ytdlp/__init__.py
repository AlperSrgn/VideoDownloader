"""
Everything that talks to the standalone yt-dlp.exe binary.

Where to look (one concern per module):

  binary.py   Getting yt-dlp.exe: first-run download (SHA-256 verified), the
              nightly self-update, version lookup. Entry point: ensure_ytdlp().
  runner.py   Launching yt-dlp.exe for the --dump-json info commands: no
              console window, timeouts, full diagnostics in the log on
              failure. Defines YtDlpError and youtube_extractor_args().
  access.py   Age-restricted / members-only videos: the cookies + Deno
              arguments, and run_with_access_fallback(), the one place that
              decides when a video is retried with them.
  info.py     Reading a video's metadata: the quick URL-paste preview and the
              full extraction a download needs. Holds CLIENT_LIST, the player
              clients that are tried.
  formats.py  Picking the video/audio format for the requested quality from
              that metadata. Pure functions, easy to unit test.

Not in here: the download itself (progress, pause/resume, ffmpeg merge) is
downloading/downloader.py, and the cookie settings and files are the `cookie`
package.

Other code imports from this package, not from the modules above:

    from ytdlp import ensure_ytdlp, find_info_with_access_fallback
"""

from ytdlp.access import access_args, find_deno
from ytdlp.binary import (
    YT_DLP_EXE_NAME,
    download_ytdlp_exe,
    ensure_ytdlp,
    get_ytdlp_path,
    get_ytdlp_version,
)
from ytdlp.formats import (
    find_progressive_audio_format,
    find_progressive_format,
    find_suitable_audio_format,
    find_suitable_format,
)
from ytdlp.info import (
    extract_info,
    fetch_preview_info,
    find_info_with_access_fallback,
    find_info_with_compatible_format,
)
from ytdlp.runner import YtDlpError, youtube_extractor_args

__all__ = [
    "YT_DLP_EXE_NAME",
    "YtDlpError",
    "access_args",
    "download_ytdlp_exe",
    "ensure_ytdlp",
    "extract_info",
    "fetch_preview_info",
    "find_deno",
    "find_info_with_access_fallback",
    "find_info_with_compatible_format",
    "find_progressive_audio_format",
    "find_progressive_format",
    "find_suitable_audio_format",
    "find_suitable_format",
    "get_ytdlp_path",
    "get_ytdlp_version",
    "youtube_extractor_args",
]
