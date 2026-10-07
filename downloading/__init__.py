"""
Downloading a video or audio track: the yt-dlp download and the ffmpeg merge
or mp3 conversion.

Where to look (one concern per module):

  downloader.py       The two entry points, download_video() and
                      download_audio(). Each runs on a background thread and
                      reports through callbacks (on_progress, on_done,
                      on_error, on_cancelled, ...). Holds the orchestration:
                      format extraction, the download phases, the ffmpeg
                      step, the progress-bar weights and temp-file cleanup.
  process_runner.py   The subprocess engine: running yt-dlp and ffmpeg,
                      parsing their progress output, cancel / pause / stall
                      handling. No knowledge of formats, files or the UI.

Not in here: finding out what a video offers (formats, cookies, the yt-dlp
binary itself) is the `ytdlp` package, and turning failures into translated,
user-facing messages is core/error_classifier.py (it also defines the
exceptions the engine raises: DownloadCancelled, DownloadStalled,
YtDlpProcessError, ...). It lives in core/ because both this package and
`ytdlp` import it.

Other code imports the entry points from this package, not from the modules
above:

    from downloading import download_video, download_audio

The names are loaded on first use (see __getattr__) instead of being imported
here, so importing this package does not pull in the whole download stack
until a name is actually used.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # for editors and type checkers only; not executed
    from downloading.downloader import download_audio, download_video

__all__ = [
    "download_audio",
    "download_video",
]

_LAZY_EXPORTS = {
    "download_audio": "downloading.downloader",
    "download_video": "downloading.downloader",
}


def __getattr__(name):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value  # cache so __getattr__ runs once per name
    return value