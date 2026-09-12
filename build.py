"""
Builds the Windows .exe with PyInstaller.

The old approach required pasting your local venv's ffmpeg path by hand
into the PyInstaller command before running it — different on every
machine, and easy to forget to update. This script asks imageio_ffmpeg
for that path itself (the same call utils.get_ffmpeg_path() uses at
runtime), so the command below never needs manual editing.

Usage:
    python build.py
"""
import subprocess
import sys

import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

CMD = [
    "pyinstaller",
    "--onefile",
    "--noconsole",
    "--add-binary", f"{FFMPEG_PATH};.",
    "--add-data", "icons\\notificationIcon.ico;icons",
    "--add-data", "icons\\previewIcon.ico;icons",
    "--add-data", "icons\\appIcon.ico;icons",
    "--hidden-import=plyer.platforms.win.notification",
    "main.py",
]

if __name__ == "__main__":
    print(f"Using ffmpeg binary: {FFMPEG_PATH}")
    sys.exit(subprocess.call(CMD))
