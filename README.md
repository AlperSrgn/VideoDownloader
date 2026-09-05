# Video Downloader

[![Release](https://img.shields.io/github/v/release/AlperSrgn/VideoDownloader?style=for-the-badge&color=blue)](https://github.com/AlperSrgn/VideoDownloader/releases)
[![Downloads](https://img.shields.io/github/downloads/AlperSrgn/VideoDownloader/total?style=for-the-badge&color=green)](https://github.com/AlperSrgn/VideoDownloader/releases)
[![Screenshots](https://img.shields.io/badge/Screenshots-View-yellow?style=for-the-badge)](https://github.com/AlperSrgn/VideoDownloader#screenshots)
[![License](https://img.shields.io/github/license/AlperSrgn/VideoDownloader?style=for-the-badge&color=purple)](https://github.com/AlperSrgn/VideoDownloader/blob/master/LICENSE)
[![Windows](https://img.shields.io/badge/Windows-10%2B-0078D4?style=for-the-badge&logo=windows)](https://github.com/AlperSrgn/VideoDownloader)
[![Download](https://img.shields.io/badge/Download-Latest%20Version-brightgreen?style=for-the-badge)](https://github.com/AlperSrgn/VideoDownloader#installation)

A simple and fast Windows desktop application powered by yt-dlp for downloading videos and audio from supported websites.

Video Downloader uses `yt-dlp.exe` for downloads and FFmpeg for media processing, with automatic yt-dlp updates.

# Features

- 🎥 Download videos in up to **4K**:
  - 2160p (4K)
  - 1440p (2K)
  - 1080p
  - 720p
- 🎵 Download video audio as **MP3**
- 📁 **Choose your download location** — select any folder from the sidebar; the app remembers it between sessions
- 📥 **Download queue** — add multiple URLs with different quality/format settings and download them sequentially
- 🌙 **Dark mode**
- 🔔 **System notifications** with notification preview
- 🔗 Download videos directly from their URLs
- 🎯 Automatically selects the best available format according to the selected quality
- 🔄 Automatically keeps `yt-dlp` up to date

Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and FFmpeg.

---

# Installation

## For Users

### 1. Download the Installer

Click the button below to download the latest version of `VideoDownloaderSetup.exe`.

[![CLICK HERE TO DOWNLOAD](https://github.com/user-attachments/assets/4e1d1739-ab90-4fdc-8645-133902ad6ea6)](https://github.com/AlperSrgn/VideoDownloader/releases/latest/download/VideoDownloaderSetup.exe)

To view previous releases and older versions, visit the [**Releases page**](https://github.com/AlperSrgn/VideoDownloader/releases).

### 2. Run the Installer

Video Downloader includes FFmpeg, which is used when video and audio streams need to be merged.

No additional FFmpeg installation is required when using the setup installer.

>  ### ⚠️ Windows SmartScreen
>
> Windows may display a **"Windows protected your PC"** warning because the installer is not digitally signed.
>
> If you downloaded the installer from this repository's official Releases page:
>
> 1. Click **More info**
> 2. Click **Run anyway**
>
> ### ℹ️ About the yt-dlp Download
>
> On first launch, Video Downloader downloads the official standalone `yt-dlp.exe` binary.
>
> The binary is downloaded directly from the [official yt-dlp nightly releases](https://github.com/yt-dlp/yt-dlp-nightly-builds/releases).
>
>
> Because the binary is downloaded at runtime, some antivirus software may inspect it when it is first downloaded.

---

## For Developers

This section is for developers who want to clone the repository, run the project from source, or build the application themselves.

### Requirements

- Windows 10+
- Python 3.x
- Internet connection
- A Python virtual environment

### Clone the Repository

```bash
git clone https://github.com/AlperSrgn/VideoDownloader.git
```

Create and activate a virtual environment using your preferred method.

### Install FFmpeg Dependency

Install `imageio-ffmpeg` from the virtual environment:

```bash
pip install imageio-ffmpeg
```

If the project cannot find the FFmpeg binary because your environment uses a different installation path, update the `get_ffmpeg_path()` function in `utils.py`.

The current project expects the FFmpeg binary under a path similar to:

```text
.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe
```

### yt-dlp

Video Downloader uses the official standalone `yt-dlp.exe` binary instead of the `yt-dlp` Python package.

On first launch, the application downloads `yt-dlp.exe` to:

```text
%LOCALAPPDATA%\VideoDownloader
```

The application checks for updates once per app run.

Therefore, there is no separate `pip install` step for yt-dlp.

> **Internet access is required on first launch** so the application can download the standalone yt-dlp binary.

---

### Build the Executable

The project is built with PyInstaller.

#### 1. Install PyInstaller

Make sure your project's virtual environment is activated, then run:

```bash
pip install pyinstaller
```

#### 2. Build

Run the following command:

```bash
pyinstaller --onefile --noconsole --add-binary "C:\path\to\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --hidden-import=plyer.platforms.win.notification main.py
```

> **🚨 Important**
>
> The FFmpeg path in the command is a placeholder. Replace it with the correct path from your local virtual environment before running the command.

---

# Project Structure

| File                  | Description                                                                                                       |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `main.py`             | UI layer — builds and manages the interface, including the download queue                                         |
| `downloader.py`       | Download logic — runs `yt-dlp.exe` as a subprocess, handles format selection, FFmpeg merging, and audio downloads |
| `error_classifier.py` | Converts raw `yt-dlp` / FFmpeg errors and process results into clear, localized, user-facing messages             |
| `ytdlp_manager.py`    | Manages the standalone `yt-dlp.exe` binary, including first-run download and per-session updates                  |
| `utils.py`            | General file helpers — filename sanitization, FFmpeg path handling, icon copying, and URL cleaning                |
| `settings.py`         | Configuration — reads and writes application settings to `AppData\Local\VideoDownloader\config.json`              |
| `languages.py`        | Localization strings for Turkish and English                                                                      |

---

# Screenshots

![Light mode](https://github.com/user-attachments/assets/6c79828f-1b69-4c82-8855-b9cd7806790b)

![Cancel download](https://github.com/user-attachments/assets/c71392ed-e9f1-476b-b0cd-734dc5c92dbb)

![Dark mode](https://github.com/user-attachments/assets/ae49438b-c9c5-45a4-a945-3aa16c7eb6b5)

![Sidebar](https://github.com/user-attachments/assets/ea224b48-ee9b-4e57-885b-144dd9548aff)



---

# Notes

- The application requires internet access to download the standalone yt-dlp binary when it is not already available.
- yt-dlp is updated through its **nightly** channel to receive fixes for website-side changes more quickly.
- Download and format support ultimately depends on the current capabilities of yt-dlp and the target website.
- The installer already includes FFmpeg, so end users do not need to install FFmpeg separately.
