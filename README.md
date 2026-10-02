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
- Python 3.10+
- Internet connection
- A Python virtual environment

### Clone the Repository

```bash
git clone https://github.com/AlperSrgn/VideoDownloader.git
```

Create and activate a virtual environment using your preferred method.

### Install Dependencies

Install all runtime dependencies from `requirements.txt`:

```bash
pip install -r requirements.txt
```

### yt-dlp

Video Downloader uses the official standalone `yt-dlp.exe` binary instead of the `yt-dlp` Python package.

On first launch, the application downloads `yt-dlp.exe` to:

```text
%LOCALAPPDATA%\VideoDownloader
```

The application checks for `yt-dlp` updates every 12 hours. The last check is saved in `config.json`, so restarting won’t trigger another check. Failed checks are retried on the next launch, so no separate `pip install` step is required.

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
| `main.py`             | Application entry point — builds the window via `ui/app_window.py`, constructs `core/app_state.py` and `core/download_controller.py`, and wires the remaining top-level UI behavior (theme/language switching, sidebar, save location, updater, uninstall) to their callbacks; applies language, icon and theme changes by looping over the widget registry |
| `core/app_state.py`        | Groups application-wide status flags (cancel/pause requests, closing state, current language, sidebar position, save location) that would otherwise be separate global variables |
| `core/download_controller.py` | Owns the full download lifecycle on top of the queue — starting the next queued item, wiring `yt-dlp` progress into the progress bar, and reacting to a download pausing, being cancelled (shown as a brief toast), finishing, or failing |
| `core/download_queue.py`   | Pure download-queue state (items waiting to download, plus the one currently in flight) — no GUI or threading dependencies, so it can be tested on its own |
| `downloading/downloader.py`       | Download logic — runs `yt-dlp.exe` as a subprocess, handles FFmpeg merging, and orchestrates video/audio downloads |
| `system/process_manager.py`  | Windows process/window management — Job Object lifecycle for child processes, pause/resume, process-tree termination, background pipe reading, and single-instance mutex + window-focus handling |
| `system/updater.py`          | Checks GitHub for new releases and handles downloading, verifying, and launching the installer                    |
| `core/quality_options.py`  | Centralizes available quality and format options, including resolutions, container formats, and dropdown labels   |
| `downloading/error_classifier.py` | Converts raw `yt-dlp` / FFmpeg errors and process results into clear, localized, user-facing messages             |
| `downloading/ytdlp_manager.py`    | Manages the standalone `yt-dlp.exe` binary — first-run download, rate-limited update checks, and selecting the best available video/audio format from extracted info |
| `ui/app_window.py`       | Builds every widget of the main window and the settings sidebar, and registers each one that needs a translated label, icon or theme colors in the registry |
| `ui/registry.py`         | `UiRegistry` — the single place where a widget declares its language key, button icon and theme key |
| `ui/queue_view.py`       | Renders the download queue (on top of `core/download_queue.py`) into widgets, and fetches per-item preview info (title, duration, thumbnail) |
| `ui/theme.py`            | Light/dark theme definitions and the `ThemeManager` that applies them to the widget set                |
| `ui/notifications.py`    | User notifications — a thin wrapper around Windows system notifications (via `plyer`, respecting the user's notification setting), plus `ToastNotifier`, which animates the in-app toast (e.g. the "download cancelled" notice) |
| `utils.py`            | General helpers — filename sanitization, temp file cleanup, video URL validation/cleaning, duration/path display formatting, FFmpeg path handling, and icon copying                |
| `settings.py`         | Configuration — reads and writes application settings to `AppData\Local\VideoDownloader\config.json`              |
| `build.py`            | Builds the Windows executable with PyInstaller and automatically resolves the local FFmpeg binary path            |
| `languages.py`        | Localization strings and language support for the application                                                     |


---

# Screenshots

<img src="https://github.com/user-attachments/assets/dbe48762-fea8-496e-bac5-8def1f33ca94" alt="Cancel download" width="700"> 
<img src="https://github.com/user-attachments/assets/c1c2facb-2c54-4a02-a9e0-f87f462efcae" alt="Dark mode" width="700"> 
<img src="https://github.com/user-attachments/assets/d642988a-a1bc-49b2-a024-1bdde84326b4" alt="Sidebar" width="700">



---

# Notes

- The application requires internet access to download the standalone yt-dlp binary when it is not already available.
- `yt-dlp` is updated through its **nightly** channel to receive fixes for website-side changes more quickly.
- The application does not currently support login, so restricted content may not be downloadable.