# Video Downloader

[![Release](https://img.shields.io/github/v/release/AlperSrgn/VideoDownloader?color=blue)](https://github.com/AlperSrgn/VideoDownloader/releases)
[![Downloads](https://img.shields.io/github/downloads/AlperSrgn/VideoDownloader/total?color=green)](https://github.com/AlperSrgn/VideoDownloader/releases)
[![Screenshots](https://img.shields.io/badge/Screenshots-View-yellow)](https://github.com/AlperSrgn/VideoDownloader#screenshots)
[![License](https://img.shields.io/github/license/AlperSrgn/VideoDownloader?color=purple)](https://github.com/AlperSrgn/VideoDownloader/blob/master/LICENSE)
[![Windows](https://img.shields.io/badge/Windows-10%2B-0078D4?logo=windows)](https://github.com/AlperSrgn/VideoDownloader)
[![Download](https://img.shields.io/badge/Download-Latest%20Version-brightgreen)](https://github.com/AlperSrgn/VideoDownloader#installation)


A simple and fast **Windows desktop application** for downloading videos and audio from supported websites.

> 🪟 **Currently available for Windows 10 and later.**

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
- 🎯 **Automatically selects the best available format** according to the selected quality
- 🔄 **Automatically keeps `yt-dlp` up to date**

Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [FFmpeg](https://github.com/imageio/imageio-ffmpeg).

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

> #### ⚠️ Windows SmartScreen
>
> Windows may display a **"Windows protected your PC"** warning because the installer is not digitally signed.
>
> If you downloaded the installer from an **official download link provided in this repository**, you can safely proceed:
>
> 1. Click **More info**
> 2. Click **Run anyway**
>
> #### ℹ️ About the yt-dlp Download
>
> On first launch, Video Downloader downloads the official standalone `yt-dlp.exe` binary.
>
> The binary is downloaded directly from the [official yt-dlp nightly releases](https://github.com/yt-dlp/yt-dlp-nightly-builds/releases).
>
> Some antivirus software may inspect the binary when it is first downloaded.
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

The application automatically locates the FFmpeg binary using `imageio_ffmpeg.get_ffmpeg_exe()`. No manual FFmpeg path configuration is required.
### yt-dlp

Video Downloader uses the official standalone `yt-dlp.exe` binary instead of the `yt-dlp` Python package.

On first launch, the application downloads `yt-dlp.exe` to:

```text
%LOCALAPPDATA%\VideoDownloader
```

The application checks for `yt-dlp` updates at most every 12 hours. The last check is saved in `config.json`, so restarting the app won’t trigger a new check. If the check fails, it will be retried on the next launch.
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

Run:

```bash
python build.py
```

The build script handles the PyInstaller build process and automatically resolves the local FFmpeg binary path through `imageio_ffmpeg`. No manual path configuration is required.

---

# Project Structure

| File                  | Description                                                                                                       |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `main.py`             | UI layer — builds and manages the interface, including the download queue                                         |
| `downloader.py`       | Download logic — runs `yt-dlp.exe` as a subprocess, handles format selection, FFmpeg merging, and audio downloads |
| `quality_options.py`  | Centralizes available quality and format options, including resolutions, container formats, and dropdown labels   |
| `error_classifier.py` | Converts raw `yt-dlp` / FFmpeg errors and process results into clear, localized, user-facing messages             |
| `ytdlp_manager.py`    | Manages the standalone `yt-dlp.exe` binary, including first-run download and rate-limited update checks           |
| `utils.py`            | General file helpers — filename sanitization, FFmpeg path handling, icon copying, and URL cleaning                |
| `settings.py`         | Configuration — reads and writes application settings to `AppData\Local\VideoDownloader\config.json`              |
| `build.py`            | Builds the Windows executable with PyInstaller and automatically resolves the local FFmpeg binary path            |
| `languages.py`        | Localization strings and language support for the application                                                     |
---

# Screenshots

<img src="https://github.com/user-attachments/assets/08ca5e47-c23e-44ca-b16d-ff59c947f299" alt="Cancel download" width="700"> 
<img src="https://github.com/user-attachments/assets/49781470-a1df-407c-92ee-8aeb780f59fa" alt="Dark mode" width="700"> 
<img src="https://github.com/user-attachments/assets/7b85fd50-4990-41d5-8402-676a7715e946" alt="Sidebar" width="700">



---

# Notes

- The application requires internet access to download the standalone yt-dlp binary when it is not already available.
- `yt-dlp` is updated through its **nightly** channel to receive fixes for website-side changes more quickly.
- The application does not currently support login, so restricted content may not be downloadable.
