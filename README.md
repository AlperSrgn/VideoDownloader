# Video Downloader

A Windows desktop application for downloading videos and audio from supported websites.

Video Downloader uses a standalone `yt-dlp.exe` backend for downloads and FFmpeg for media processing. The application can automatically update its yt-dlp binary in the background so it can keep up with changes on supported websites.

## Features

- Download videos in up to **4K**:
  - 2160p (4K)
  - 1440p (2K)
  - 1080p
  - 720p
- Download video audio as **MP3**
- **Choose your download location** — select any folder from the sidebar; the app remembers it between sessions
- **Download queue** — add multiple URLs with different quality/format settings and download them sequentially
- Add new downloads to the queue while another download is in progress
- **Dark mode**
- **System notifications** with notification preview
- Download videos directly from their URLs
- Automatically selects the best available format according to the selected quality
- Uses a standalone `yt-dlp.exe` that downloads on first launch and self-updates once per app run on the **nightly** channel

Based on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

---

# Installation

## For Users

### 1. Download the Installer

Download the latest `VideoDownloaderSetup.exe` from the project's GitHub Releases page.

[![Download](https://github.com/user-attachments/assets/8d8adf06-7013-4017-8434-51984f624e3b)](https://github.com/AlperSrgn/VideoDownloader/releases/download/v3.1.0/VideoDownloaderSetup.exe)

### 2. Run the Installer

Video Downloader includes FFmpeg, which is used when video and audio streams need to be merged.

No additional FFmpeg installation is required when using the setup installer.

> ### ⚠️ Windows SmartScreen Warning
>
> Windows may display a blue **"Windows protected your PC"** warning when you run the installer.
>
> This can happen because the executable is not signed with a paid code-signing certificate. The project is open source, and its source code is available for review.
>
> If you trust the project and downloaded the installer from the official release page:
>
> 1. Click **More info**
> 2. Click **Run anyway**
>
> ### Antivirus / yt-dlp Warning
>
> On its first launch, the application downloads the standalone `yt-dlp.exe` binary.
>
> Because this executable is downloaded at runtime and is not digitally signed by the application developer, some antivirus software may inspect or flag it.
>
> The binary is downloaded from the official [yt-dlp nightly releases](https://github.com/yt-dlp/yt-dlp-nightly-builds/releases).

---

# Development Setup

This section is for developers who want to clone the repository, run the project from source, or build the application themselves.

## Requirements

- Windows
- Python
- A Python virtual environment
- `imageio-ffmpeg`
- Internet access on first launch so the application can download `yt-dlp.exe`

## Clone the Repository

```bash
git clone https://github.com/AlperSrgn/VideoDownloader.git
```

Create and activate a virtual environment using your preferred method.

## Install FFmpeg Dependency

Install `imageio-ffmpeg` from the virtual environment:

```bash
pip install imageio-ffmpeg
```

If the project cannot find the FFmpeg binary because your environment uses a different installation path, update the `get_ffmpeg_path()` function in `utils.py`.

The current project expects the FFmpeg binary under a path similar to:

```text
.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe
```

## yt-dlp

The application **does not use the `yt-dlp` Python package**.

Instead, `ytdlp_manager.py` downloads the official standalone `yt-dlp.exe` from the nightly channel into:

```text
%LOCALAPPDATA%\VideoDownloader
```

The application checks for updates once per app run.

Therefore, there is no separate `pip install` step for yt-dlp.

> **Internet access is required on first launch** so the application can download the standalone yt-dlp binary.

---

# Build the Executable

The project is built with PyInstaller.

## 1. Install PyInstaller

Install PyInstaller into the project's virtual environment:

```bash
pip install pyinstaller
```

If you prefer to call the virtual environment directly on Windows:

```bash
C:\path\to\project\.venv\Scripts\pip.exe install pyinstaller
```

## 2. Build

The current build command is:

```bash
pyinstaller --onefile --noconsole --add-binary "C:\path\to\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --hidden-import=plyer.platforms.win.notification main.py
```

Replace the paths with the paths used by your own environment.

> **🚨 Important:** Build the application using the Python and PyInstaller installation from the project's virtual environment. This helps ensure that the expected package versions and dependencies are included in the executable.

> **🚨 Important:** The FFmpeg and PyInstaller paths in the example above are placeholders. Update them for your local environment before running the command.

---

# Project Structure

| File | Description |
| --- | --- |
| `main.py` | UI layer — builds and manages the interface, including the download queue |
| `downloader.py` | Download logic — runs `yt-dlp.exe` as a subprocess, handles format selection, FFmpeg merging, and audio downloads |
| `error_classifier.py` | Converts raw `yt-dlp` / FFmpeg errors and process results into clear, localized, user-facing messages |
| `ytdlp_manager.py` | Manages the standalone `yt-dlp.exe` binary, including first-run download and per-session updates |
| `utils.py` | General file helpers — filename sanitization, FFmpeg path handling, icon copying, and URL cleaning |
| `settings.py` | Configuration — reads and writes application settings to `AppData\Local\VideoDownloader\config.json` |
| `languages.py` | Localization strings for Turkish and English |

---

# Screenshots

![Light mode](https://github.com/user-attachments/assets/6c79828f-1b69-4c82-8855-b9cd7806790b)


![Dark mode](https://github.com/user-attachments/assets/ae49438b-c9c5-45a4-a945-3aa16c7eb6b5)


![Sidebar](https://github.com/user-attachments/assets/ea224b48-ee9b-4e57-885b-144dd9548aff)


![Cancel download](https://github.com/user-attachments/assets/a6ecdc98-0427-4e31-be08-a724378a4f02)

---

# Notes

- The application requires internet access to download the standalone yt-dlp binary when it is not already available.
- yt-dlp is updated through its **nightly** channel to receive fixes for website-side changes more quickly.
- Download and format support ultimately depends on the current capabilities of yt-dlp and the target website.
- The installer already includes FFmpeg, so end users do not need to install FFmpeg separately.
