"""
Downloading a video or audio track: the yt-dlp download, the ffmpeg merge or
mp3 conversion, and turning their failures into messages for the user.

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
  error_classifier.py The exceptions the engine raises (DownloadCancelled,
                      DownloadStalled, YtDlpProcessError, ...) and the
                      classify_* functions that map a failure to a
                      translated, user-facing message from the `lang` dict.

Not in here: finding out what a video offers (formats, cookies, the yt-dlp
binary itself) is the `ytdlp` package.

Other code imports the entry points from this package, not from the modules
above:

    from downloading import download_video, download_audio

The names are loaded on first use (see __getattr__) instead of being imported
here, so importing a light submodule such as downloading.error_classifier does
not pull in the whole download stack. That also keeps the `ytdlp` package and
this one from importing each other in a circle.
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