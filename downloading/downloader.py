"""
The two download entry points, download_video() and download_audio(), and the
orchestration behind them. Each runs on a background thread and reports back
through callbacks (on_progress, on_done, on_error, on_cancelled, ...), which
are bundled internally in DownloadCallbacks.

What happens, in order:

  1. _run_in_worker() starts the thread: checks ffmpeg exists, makes sure
     yt-dlp is available, runs the download steps, and always cleans up the
     temp files afterwards.
  2. The video's formats are looked up (see the `ytdlp` package), retried with
     cookies + Deno only for age-restricted / members-only videos.
  3. download_video() either downloads one combined (muxed) file -- the
     fallback when YouTube offers no separate streams -- or downloads video
     and audio separately and merges them with ffmpeg; download_audio()
     downloads the raw audio and converts it to mp3.
  4. Every phase feeds one progress bar through fixed weights (see the
     *_WEIGHT constants), not file sizes, because some formats report none.

Error flow: the steps never report a failure themselves. A failing step
raises -- an engine exception from process_runner, or _DownloadFailed carrying
a ready, user-facing message -- and _run_in_worker() is the one place that
turns it into on_error / on_cancelled. If the steps return normally it calls
on_done. So exactly one of on_done, on_error and on_cancelled is called per
download.

Not in here: building the yt-dlp / ffmpeg command lines is ytdlp/commands.py
and ffmpeg_commands.py; running them, parsing their output (progress, pause,
stall) and retrying an HTTP 403 is process_runner.py; turning failures into
user-facing messages is core/error_classifier.py. Other code should import
the entry points from the package:
`from downloading import download_video, download_audio`.
"""

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from settings import get_appdata_path
from utils import (
    cleanup_temp_files,
    get_ffmpeg_path,
    sanitize_filename,
    unique_filename,
    update_file_timestamp,
    find_glob_file,
)
from core.quality_options import RESOLUTION_MAP
from ytdlp import (
    build_download_cmd,
    ensure_ytdlp,
    find_info_with_access_fallback,
    find_progressive_audio_format,
    find_progressive_format,
    find_suitable_audio_format,
    find_suitable_format,
)
from ytdlp.formats import resolution_of
from ytdlp.info import Extraction
from downloading.ffmpeg_commands import build_ffmpeg_merge_cmd, build_ffmpeg_mp3_cmd
from downloading.process_runner import (
    known_size_mb,
    run_download_with_retry,
    run_ffmpeg_merge,
)
from core.error_classifier import (
    DenoNotFoundError,
    DownloadCancelled,
    DownloadStalled,
    YtDlpProcessError,
    FfmpegProcessError,
    classify_ytdlp_error,
    classify_ffmpeg_error,
    classify_extraction_failure,
    classify_generic_exception,
)

logger = logging.getLogger(__name__)

# Every temporary download file starts with this prefix (followed by a
# per-download UUID), including yt-dlp's own .part/.ytdl side files.
TEMP_PREFIX = ".ytdlp_tmp_"

# Fixed weights combine video download, audio download and ffmpeg merge into
# one progress bar. They are fixed (not derived from file sizes) because some
# DASH/adaptive formats report no filesize, which left progress stuck at 0%,
# and fragmented downloads made a size-based total fluctuate.
VIDEO_PHASE_WEIGHT = 75
AUDIO_PHASE_WEIGHT = 15
MERGE_PHASE_WEIGHT = 10

# Audio-only flow: download the raw audio track, then convert it to mp3
# ourselves (see download_audio) so the conversion step reports progress
# instead of running invisibly inside yt-dlp's own postprocessor.
AUDIO_DOWNLOAD_WEIGHT = 85
AUDIO_CONVERT_WEIGHT = 15


# ---------------------------------------------------------------------------
# Callbacks and per-download context
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DownloadCallbacks:
    """Everything a download reports back through, bundled so the phase
    helpers take one argument instead of six.

    All callbacks are invoked from the worker thread. Exactly one of
    on_done, on_error and on_cancelled is called per download. on_cancelled
    and on_notice are optional; if on_cancelled is None a cancellation is
    reported through on_error instead.
    """
    on_progress: Callable
    on_cancel_check: Callable[[], bool]
    on_done: Callable[[], None]
    on_error: Callable[[str], None]
    on_merge_progress: Optional[Callable] = None
    on_pause_check: Optional[Callable[[], bool]] = None
    on_cancelled: Optional[Callable[[], None]] = None
    on_notice: Optional[Callable[[str], None]] = None


class _DownloadFailed(Exception):
    """A step failed and the user-facing message is already final (ffmpeg or
    Deno missing, no usable format, downloaded file gone, ...). Raised by the
    steps and turned into on_error by _run_in_worker; str(exc) is the
    message. Engine failures (YtDlpProcessError, FfmpegProcessError, ...)
    are not wrapped in this: _run_in_worker classifies those itself."""


@dataclass(frozen=True)
class _DownloadJob:
    """State shared by the steps of one download once extraction succeeded."""
    url: str
    save_location: str
    exe_path: str
    client: Optional[str]
    restricted: bool
    temp_base: str  # save_location/TEMP_PREFIX+uuid, no suffix or extension
    safe_title: str
    info: dict
    cb: DownloadCallbacks
    lang: dict

    def ytdlp_cmd(self, fmt: dict, output_template: str, use_ffmpeg: bool = False) -> list:
        return build_download_cmd(
            self.exe_path, fmt["format_id"], self.client, output_template, self.url,
            restricted=self.restricted, use_ffmpeg=use_ffmpeg,
        )

    def run_ytdlp(self, cmd: list, progress_fn, known_total_mb=None) -> None:
        """One yt-dlp download phase, with the HTTP 403 retry (see
        run_download_with_retry). Raises on failure, stall or cancellation."""
        run_download_with_retry(
            cmd, progress_fn, self.cb.on_cancel_check,
            self.lang["download_canceled_message"], self.lang["error_download_stalled"],
            known_total_mb=known_total_mb, on_pause_check=self.cb.on_pause_check,
        )

    def run_ffmpeg(self, cmd: list, progress_fn, output_path: str) -> None:
        """The ffmpeg merge / mp3 conversion step. Raises on failure or
        cancellation, first removing `output_path`: a killed or failed ffmpeg
        run can leave a partial, unplayable file behind."""
        try:
            run_ffmpeg_merge(
                cmd, self.info.get("duration"), progress_fn, self.cb.on_cancel_check,
                self.lang["download_canceled_message"], on_pause_check=self.cb.on_pause_check,
            )
        except Exception:
            _remove_if_exists(output_path)
            raise

    def find_file(self, tag: str = "") -> str:
        """Path of the file a yt-dlp phase wrote: temp_base + tag + any
        extension. Raises _DownloadFailed if it is gone."""
        pattern = f"{self.temp_base}{tag}.*"
        try:
            return find_glob_file(pattern)
        except FileNotFoundError:
            logger.error("Downloaded file not found: %s", pattern)
            raise _DownloadFailed(self.lang.get(
                "error_downloaded_file_missing",
                "The downloaded file could not be found. Please try again.",
            ))


# ---------------------------------------------------------------------------
# Shared helpers for download_video / download_audio
# ---------------------------------------------------------------------------
# Both download_video and download_audio run one or more yt-dlp download
# phases followed by one ffmpeg phase (see _DownloadJob.run_ytdlp /
# run_ffmpeg). The exception -> callback mapping for all of them is in
# _run_in_worker.

def _weighted(report: Callable, offset: float, weight: float) -> Callable:
    """Maps one phase's 0-100 percent onto its slice of the overall bar:
    offset + weight * percent / 100. downloaded_mb/total_mb/eta (or
    elapsed/total seconds/eta for ffmpeg) pass through unchanged as
    phase-specific values."""

    def progress(percent, a, b, eta):
        report(offset + weight * (percent / 100), a, b, eta)

    return progress


def _report_cancelled(cb: DownloadCallbacks, exc) -> None:
    """A user cancellation is not an error. If the caller supplied
    on_cancelled it gets a plain notification; otherwise the cancellation
    is reported through on_error."""
    if cb.on_cancelled is not None:
        cb.on_cancelled()
    else:
        cb.on_error(str(exc))


def _remove_if_exists(path: str) -> None:
    """Best-effort delete. Used both to remove a partial, unplayable file
    ffmpeg may have written before being cancelled or before erroring out,
    and to remove the intermediate temp files (video/audio/raw audio) once
    they've been merged or converted."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _extract_with_access_fallback(exe_path, url, selector, fallback_selector,
                                  lang: dict,
                                  fallback_good_enough=None) -> Extraction:
    """Info extraction shared by download_video / download_audio.

    Normal videos are extracted without cookies and without Deno. Only an
    age-restricted / members-only video (with cookies configured) is retried
    with cookies + Deno -- see find_info_with_access_fallback.

    fallback_good_enough(selection) -> bool lets the extraction stop trying
    further player clients once a fallback is already good enough.

    Returns an Extraction (info, client, selection, restricted); raises
    _DownloadFailed with the user-facing message if there is none.
    """
    extraction_errors = []
    try:
        extraction = find_info_with_access_fallback(
            exe_path, url, selector, collected_errors=extraction_errors,
            fallback_selector=fallback_selector,
            fallback_good_enough=fallback_good_enough,
        )
    except DenoNotFoundError:
        raise _DownloadFailed(lang.get(
            "error_deno_required",
            "This video is age-restricted or members-only, which requires Deno. "
            "Please install Deno (e.g. run: winget install DenoLand.Deno) and try again.",
        ))

    if extraction is None:
        raise _DownloadFailed(classify_extraction_failure(
            extraction_errors, lang, fallback_key="download_video_format_error"
        ))
    return extraction


def _run_in_worker(name: str, save_location: str, cb: DownloadCallbacks, lang: dict, impl) -> None:
    """Shared skeleton of download_video / download_audio: starts a daemon
    thread that checks ffmpeg exists, makes sure yt-dlp is available, then
    calls impl(temp_id, exe_path) -- the part that differs per download.

    This is the one place that reports the outcome (see the module
    docstring): impl returning normally means success (on_done); anything it
    raises is mapped to on_cancelled / on_error here. on_done is called
    outside the try, so a failing callback can never produce a second
    terminal callback.

    temp_id is a fresh UUID per download, so repeated downloads of the same
    video only match their own temp files. It is created before the thread
    starts so the finally block cleans up `.ytdlp_tmp_*` files on every exit
    path: cancel, stall, yt-dlp error, missing file, unexpected exception.
    The catch-all turns an unexpected error into on_error instead of silently
    killing the thread and leaving the UI stuck.
    """
    temp_id = uuid.uuid4().hex

    def worker():
        try:
            if not os.path.exists(get_ffmpeg_path()):
                raise _DownloadFailed(lang["ffmpeg_not_found_error"])
            exe_path = ensure_ytdlp(get_appdata_path())
            impl(temp_id, exe_path)
        except DownloadCancelled as e:
            _report_cancelled(cb, e)
        except DownloadStalled as e:
            cb.on_error(str(e))
        except YtDlpProcessError as e:
            cb.on_error(classify_ytdlp_error(e.output, e.returncode, lang))
        except FfmpegProcessError as e:
            cb.on_error(classify_ffmpeg_error(e.output, e.returncode, lang))
        except _DownloadFailed as e:
            cb.on_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error in %s worker", name)
            cb.on_error(classify_generic_exception(e, lang))
        else:
            cb.on_done()
        finally:
            cleanup_temp_files(save_location, f"{TEMP_PREFIX}{temp_id}")

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Video download
# ---------------------------------------------------------------------------

def _download_muxed(job: _DownloadJob, video_format: dict, requested_height: int) -> None:
    """Muxed fallback: one file that already has video + audio (plain https,
    or HLS which yt-dlp remuxes with ffmpeg), so no merge step -- the finished
    file is just moved into place. The user is only told about a quality
    reduction if the stream is below the requested height."""
    cb = job.cb
    # Short side (e.g. 720 for a 720x1280 portrait video), matching the
    # quality labels the user picks from -- not the raw `height`.
    height = resolution_of(video_format)
    logger.warning(
        "Muxed fallback: client=%s format=%s (%sp, protocol=%s, vcodec=%s, acodec=%s)",
        job.client or "default", video_format.get("format_id"), height,
        video_format.get("protocol"), video_format.get("vcodec"),
        video_format.get("acodec"),
    )
    if cb.on_notice and (height or 0) < requested_height:
        cb.on_notice(job.lang.get(
            "notice_progressive_fallback",
            "Only a lower-resolution ({height}p) combined stream was available "
            "for this video, so it will be downloaded at that quality.",
        ).replace("{height}", str(height)))

    cmd = job.ytdlp_cmd(video_format, f"{job.temp_base}_video", use_ffmpeg=True)
    job.run_ytdlp(cmd, cb.on_progress, known_total_mb=known_size_mb(video_format))

    downloaded_path = job.find_file("_video")

    # Keep yt-dlp's real extension: the muxed file is already a
    # finished container, so renaming it to .mp4 could mislabel e.g. webm.
    extension = os.path.splitext(downloaded_path)[1] or ".mp4"
    output_filename = unique_filename(job.save_location, f"{job.safe_title}{extension}")
    output_path = os.path.join(job.save_location, output_filename)
    # An OSError here (disk, permissions) is classified by _run_in_worker.
    os.replace(downloaded_path, output_path)

    update_file_timestamp(output_path)
    logger.debug("Download completed (muxed): %s", output_path)


def _download_and_merge(job: _DownloadJob, video_format: dict, audio_format: dict) -> None:
    """Separate video and audio streams: download each, then mux with ffmpeg."""
    cb = job.cb
    logger.info(
        "Selected client=%s video_format=%s (vcodec=%s, tbr=%s) "
        "audio_format=%s (acodec=%s, abr=%s)",
        job.client or "default",
        video_format.get("format_id"), video_format.get("vcodec"), video_format.get("tbr"),
        audio_format.get("format_id"), audio_format.get("acodec"), audio_format.get("abr"),
    )

    video_cmd = job.ytdlp_cmd(video_format, f"{job.temp_base}_video")
    audio_cmd = job.ytdlp_cmd(audio_format, f"{job.temp_base}_audio")

    job.run_ytdlp(
        video_cmd, _weighted(cb.on_progress, 0, VIDEO_PHASE_WEIGHT),
        known_total_mb=known_size_mb(video_format),
    )
    job.run_ytdlp(
        audio_cmd, _weighted(cb.on_progress, VIDEO_PHASE_WEIGHT, AUDIO_PHASE_WEIGHT),
        known_total_mb=known_size_mb(audio_format),
    )

    video_path = job.find_file("_video")
    audio_path = job.find_file("_audio")

    output_filename = unique_filename(job.save_location, f"{job.safe_title}.mp4")
    output_path = os.path.join(job.save_location, output_filename)

    merge_progress = None
    if cb.on_merge_progress:
        merge_progress = _weighted(
            cb.on_merge_progress, VIDEO_PHASE_WEIGHT + AUDIO_PHASE_WEIGHT, MERGE_PHASE_WEIGHT,
        )
    try:
        job.run_ffmpeg(
            build_ffmpeg_merge_cmd(video_path, audio_path, output_path),
            merge_progress, output_path,
        )
    finally:
        # Always clean up temporary video/audio files, regardless of merge result.
        for path in (video_path, audio_path):
            _remove_if_exists(path)

    update_file_timestamp(output_path)
    logger.debug("Download completed: %s", output_path)


def download_video(
        url: str,
        save_location: str,
        target_resolution: str,
        on_progress,
        on_cancel_check,
        on_done,
        on_error,
        lang: dict,
        on_merge_progress=None,
        on_pause_check=None,
        on_cancelled=None,
        on_notice=None,
) -> None:
    """
    Downloads video and audio separately, then merges them with ffmpeg.
    If YouTube offers no separate streams (SABR) but does offer a lower-
    quality single-file format, that one is downloaded as-is (no merge) and
    on_notice(message) -- if supplied -- is called from the worker thread so
    the UI can tell the user the quality was reduced (marshal to the UI thread).
    Runs in a background thread. Calls on_done() on success, on_error(msg)
    on failure, or on_cancelled() if the user cancelled (falls back to
    on_error(msg) when on_cancelled isn't supplied).
    Merge progress is reported via on_merge_progress, based on processed
    seconds.

    on_pause_check: optional callable checked throughout every phase. The
    video and audio download phases pause by stopping yt-dlp and relaunching
    it on resume, so it continues the partial file (see run_download's
    docstring for why); the merge phase pauses by suspending ffmpeg in
    place, since it's local CPU work with no network buffering to worry
    about (see apply_pause_state).
    """
    cb = DownloadCallbacks(
        on_progress=on_progress, on_cancel_check=on_cancel_check, on_done=on_done,
        on_error=on_error, on_merge_progress=on_merge_progress,
        on_pause_check=on_pause_check, on_cancelled=on_cancelled, on_notice=on_notice,
    )

    def _impl(temp_id, exe_path):
        if target_resolution not in RESOLUTION_MAP:
            raise _DownloadFailed(f"Invalid resolution: {target_resolution}")

        video_height = RESOLUTION_MAP[target_resolution]
        extraction = _extract_with_access_fallback(
            exe_path, url,
            lambda formats: find_suitable_format(formats, video_height),
            lambda formats: find_progressive_format(formats, video_height),
            lang,
            # A muxed fallback that already reaches the requested resolution
            # cannot be beaten by trying more clients.
            fallback_good_enough=lambda selection: selection.height >= video_height,
        )
        selection = extraction.selection

        job = _DownloadJob(
            url=url, save_location=save_location, exe_path=exe_path,
            client=extraction.client, restricted=extraction.restricted,
            temp_base=os.path.join(save_location, f"{TEMP_PREFIX}{temp_id}"),
            safe_title=sanitize_filename(extraction.info.get("title", "video")),
            info=extraction.info, cb=cb, lang=lang,
        )
        if selection.kind == "muxed":
            _download_muxed(job, selection.video, video_height)
        else:
            _download_and_merge(job, selection.video, selection.audio)

    _run_in_worker("download_video", save_location, cb, lang, _impl)


# ---------------------------------------------------------------------------
# Audio-only download
# ---------------------------------------------------------------------------

def download_audio(
        url: str,
        save_location: str,
        on_progress,
        on_cancel_check,
        on_done,
        on_error,
        lang: dict,
        on_merge_progress=None,
        on_pause_check=None,
        on_cancelled=None,
) -> None:
    """Download audio only as mp3. Runs in a background thread. Completion,
    failure and cancellation are reported through on_done / on_error /
    on_cancelled exactly as in download_video.

    Downloads the raw audio track first, then converts it to mp3 with our
    own ffmpeg call (using -progress pipe:1, same as the video merge step).
    Doing the conversion ourselves, rather than via yt-dlp's -x/--audio-format
    postprocessor, lets us report its progress through on_merge_progress;
    the postprocessor runs invisibly after the [download] 100% line, which
    left the progress bar looking stuck.

    on_pause_check: optional callable checked throughout both phases. The
    download phase pauses by stopping yt-dlp and relaunching it on resume
    so it continues the partial file (see run_download's docstring); the
    mp3 conversion phase pauses by suspending ffmpeg in place, since it's
    local CPU work with no network buffering to worry about (see
    apply_pause_state).
    """
    cb = DownloadCallbacks(
        on_progress=on_progress, on_cancel_check=on_cancel_check, on_done=on_done,
        on_error=on_error, on_merge_progress=on_merge_progress,
        on_pause_check=on_pause_check, on_cancelled=on_cancelled,
    )

    def _impl(temp_id, exe_path):
        extraction = _extract_with_access_fallback(
            exe_path, url, find_suitable_audio_format, find_progressive_audio_format,
            lang,
        )
        info, client = extraction.info, extraction.client
        chosen_audio = extraction.selection.audio

        if extraction.selection.audio_from_muxed:
            # No audio-only stream: the audio is extracted from a muxed
            # file by the existing ffmpeg step (-vn), so nothing else changes.
            logger.warning(
                "No audio-only stream; extracting audio from muxed format %s",
                chosen_audio.get("format_id"),
            )
        logger.info(
            "Selected client=%s audio_format=%s (acodec=%s, abr=%s, language=%s)",
            client or "default", chosen_audio.get("format_id"), chosen_audio.get("acodec"),
            chosen_audio.get("abr"), chosen_audio.get("language"),
        )

        job = _DownloadJob(
            url=url, save_location=save_location, exe_path=exe_path,
            client=client, restricted=extraction.restricted,
            temp_base=os.path.join(save_location, f"{TEMP_PREFIX}{temp_id}"),
            safe_title=sanitize_filename(info.get("title", "audio")),
            info=info, cb=cb, lang=lang,
        )
        output_filename = unique_filename(save_location, f"{job.safe_title}.mp3")
        output_path = os.path.join(save_location, output_filename)

        # Download the raw audio track only — no -x/--audio-format here.
        # The mp3 conversion is done ourselves below so its progress can be
        # reported instead of running invisibly inside yt-dlp.
        job.run_ytdlp(
            job.ytdlp_cmd(chosen_audio, job.temp_base),
            _weighted(cb.on_progress, 0, AUDIO_DOWNLOAD_WEIGHT),
            known_total_mb=known_size_mb(chosen_audio),
        )

        raw_audio_path = job.find_file()

        convert_progress = None
        if cb.on_merge_progress:
            convert_progress = _weighted(
                cb.on_merge_progress, AUDIO_DOWNLOAD_WEIGHT, AUDIO_CONVERT_WEIGHT,
            )
        try:
            job.run_ffmpeg(
                build_ffmpeg_mp3_cmd(raw_audio_path, output_path),
                convert_progress, output_path,
            )
        finally:
            _remove_if_exists(raw_audio_path)

        update_file_timestamp(output_path)
        logger.debug("Download completed (audio): %s", output_path)

    _run_in_worker("download_audio", save_location, cb, lang, _impl)