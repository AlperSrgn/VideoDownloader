"""
ffmpeg command lines for the post-download steps (merge video + audio, convert
audio to mp3). Both pass `-progress pipe:1` so
downloading/process_runner.run_ffmpeg_merge can report progress. yt-dlp command
lines are in ytdlp/commands.py.
"""

from utils import get_ffmpeg_path


def build_ffmpeg_merge_cmd(video_path: str, audio_path: str, output_path: str) -> list:
    """Muxes separate video + audio tracks into one mp4 (video is copied,
    audio re-encoded to AAC). -progress pipe:1 feeds run_ffmpeg_merge."""
    return [
        get_ffmpeg_path(), "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-progress", "pipe:1",
        "-nostats",
        output_path,
    ]


def build_ffmpeg_mp3_cmd(raw_audio_path: str, output_path: str) -> list:
    """Converts a raw audio (or muxed video, via -vn) file to mp3."""
    return [
        get_ffmpeg_path(), "-y",
        "-i", raw_audio_path,
        "-vn",
        "-c:a", "libmp3lame",
        "-q:a", "2",
        "-progress", "pipe:1",
        "-nostats",
        output_path,
    ]
