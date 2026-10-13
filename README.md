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
- 🍪 **Cookie support** — download videos that require signing in, using your own signed-in session

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

### Run the Application

After installing the dependencies and activating your virtual environment, run the application with:

```bash
python main.py
```


### yt-dlp

Video Downloader uses the official standalone `yt-dlp.exe` binary instead of the `yt-dlp` Python package.

On first launch, the application downloads `yt-dlp.exe` to:

```text
%LOCALAPPDATA%\VideoDownloader
```

The application checks for `yt-dlp` updates every 12 hours. The last check is saved in `config.json`, so restarting won’t trigger another check. Failed checks are retried on the next launch.

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

# Cookie Support (Videos That Require Sign-In)

Some videos (e.g., age-restricted, members-only) may require you to be signed in to access them. Video Downloader can use your existing browser session to download these videos. so you don't need to enter your account password in the app.


**Note:** You only need cookie support for videos that require you to sign in. Public videos can still be downloaded normally without configuring cookies or installing Deno.

## Before You Start

Make sure you have:

- A browser with an active session on the website containing the video, with permission to access that content.
- [Deno](#deno-requirement) installed on your computer.

## Choose a Cookie Method

Open the settings sidebar and select a cookie mode from the dropdown.

| Mode | When to use it |
| --- | --- |
| **None** (default) | For public videos that don't require you to sign in. |
| **Browser** | To use cookies directly from a supported browser. Choose your browser from the second dropdown. **(Recommended first option for Firefox users.)** |
| **File** | To use a `cookies.txt` file you've exported yourself using a browser extension. |
| **Firefox export** | To automatically extract the relevant cookies from your Firefox profile. Use this if the Browser method doesn't work. |

**🚨 Important:** Your `cookies.txt` may give others access to your account. Keep it private and never share or publicly upload it.

## How to Set Up Each Method

### Browser

1. Select **Browser** as the cookie mode.
2. Choose your browser from the dropdown (Firefox, Edge, Chrome, Brave, Opera).
3. Download the video as usual.

**Having trouble?** Close your browser and try again if the app cannot read its cookie database. Recent versions of Chrome, Edge, and Brave use additional cookie encryption protections that may prevent direct access. If the problem persists, [download Firefox](https://www.mozilla.org/firefox/) and try again.


### File

1. Export your cookies to a **Netscape-format cookies.txt** file using a browser extension that supports cookie export.
2. Select **File** as the cookie mode.
3. Choose your exported `cookies.txt` file.
4. Download the video as usual.

The app creates and uses its own copy of the selected file. Your original file is not modified or deleted.

### Firefox Export

1. Open Firefox and sign in to the website you want to download from.
2. Select **Firefox export** as the cookie mode and run the export.
3. Download the video as usual.

The app checks your Firefox profiles for an active session on the website. It exports the relevant cookies to its own `cookies.txt` file.

If your session expires or you sign in with a different account, export the cookies again to refresh them.


## Deno Requirement

Deno is an additional component that helps `yt-dlp` handle JavaScript challenges when downloading certain sign-in-protected videos. Video Downloader uses Deno to enable these downloads. For more information, visit the [official Deno website](https://deno.com/) or check out the [GitHub page](https://github.com/denoland/deno).

**Note:** Deno is only required for videos that need sign-in. You don't need to install it to download ordinary public videos. 
To download sign-in-protected videos, you need both a working cookie configuration and Deno installed.

### Install Deno

Open PowerShell or Windows Terminal and run the following command:

```powershell
winget install DenoLand.Deno
```

The app automatically looks for Deno in your system's `PATH` and common installation locations, so you don't need to configure its path manually.


---

# Screenshots

<img src="https://github.com/user-attachments/assets/dbe48762-fea8-496e-bac5-8def1f33ca94" alt="Cancel download" width="700"> 
<img src="https://github.com/user-attachments/assets/c1c2facb-2c54-4a02-a9e0-f87f462efcae" alt="Dark mode" width="700"> 
<img src="https://github.com/user-attachments/assets/d642988a-a1bc-49b2-a024-1bdde84326b4" alt="Sidebar" width="700">



---

# Notes

- The application requires internet access to download the standalone yt-dlp binary when it is not already available.
- `yt-dlp` is updated through its **nightly** channel to receive fixes for website-side changes more quickly.
- The application does not ask for or store your login credentials. Content that requires signing in can be downloaded by using your browser's cookies — see [Cookie Support](#cookie-support-videos-that-require-sign-in).