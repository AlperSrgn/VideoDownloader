# VIDEO DOWNLOADER

Download videos from websites. Provides the following features:

- Download videos up to 4K resolution [ 2160P(4K), 1440P(2K), 1080P, 720P ]
- Download the audio of the video as MP3
- **Choose your download location** — pick any folder from the sidebar; the app remembers it between sessions
- **Download queue** — queue up multiple links, each with its own quality/format, and let them download one after another. You can keep adding more links while a download is already in progress
- Dark mode feature
- System notification support with preview
- Download videos by URL
- Automatically selects the best video format based on your quality preference
- Automatically handles SABR-protected YouTube videos by trying multiple clients
- Uses a standalone `yt-dlp.exe` that downloads and self-updates in the background (on the **nightly** channel, for faster fixes to YouTube-side breakage), so the app can keep up with YouTube changes without waiting on an app update

Based on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

---

# INSTALLATION

## Download VideoDownloaderSetup.exe

### [![İNDİR](https://github.com/user-attachments/assets/8d8adf06-7013-4017-8434-51984f624e3b)](https://github.com/AlperSrgn/VideoDownloader/releases/download/v3.0.2/VideoDownloaderSetup.exe)

<br>

**Note:** Video Downloader comes bundled with FFmpeg which is used for merging video and audio streams. When you download it as a setup file, you do not need to take any action.
You can complete the installation process by running the setup file.

> ⚠️ **Windows SmartScreen warning:** When you run the installer, Windows may show a blue **"Windows protected your PC"** screen. This is expected and **not a sign of malware** — it happens because the exe isn't signed with a paid code-signing certificate, which Microsoft uses as a trust signal regardless of what the app actually does. The project is fully open source, so you're welcome to review the code yourself before running it. To continue: click **"More info"**, then **"Run anyway"**.
>
> Your antivirus may also flag or scan `yt-dlp.exe` the first time the app downloads it — this is the same story: it's an unsigned executable that gets fetched at runtime (see [Project Structure](#project-structure) below), not malicious behavior. It's downloaded directly from the official [yt-dlp nightly builds GitHub releases](https://github.com/yt-dlp/yt-dlp-nightly-builds/releases) (the same yt-dlp project, just its more frequently-updated nightly channel).

---

## Install in IDE

If you want to install into the IDE with the `git clone` command from Github, you need to install [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) from the terminal after installation.

**Install using:**

`$ pip install imageio-ffmpeg`

After running this command, the _imageio-ffmpeg_ installation will be completed.  
<br><br>

**Note:** If you have a problem with the directory where _imageio-ffmpeg_ is installed, edit the `get_ffmpeg_path()` function in **utils.py** according to your own _imageio-ffmpeg_ file path:

`$ return os.path.join(project_dir, ".venv", "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe")`

**Note:** This app no longer depends on the `yt-dlp` Python package. Instead, `ytdlp_manager.py` downloads the official standalone `yt-dlp.exe` (nightly channel) into `%LOCALAPPDATA%\VideoDownloader` on first launch and asks it to self-update (staying on the nightly channel) once per app run — so there's nothing to `pip install` for yt-dlp itself, but the app does need internet access on first launch to fetch it.

---

## Convert to Exe

The project must be built using the **virtual environment's** Python and PyInstaller to ensure the correct versions of all packages are bundled.

**Step 1 — Install PyInstaller into the virtual environment:**

`$ C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Scripts\pip.exe install pyinstaller`

**Step 2 — Build the exe:**

`$ pyinstaller --onefile --noconsole --add-binary "C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --add-data "languages.py;." --add-data "settings.py;." --add-data "utils.py;." --add-data "downloader.py;." --add-data "ytdlp_manager.py;." --hidden-import=plyer.platforms.win.notification main.py`

<br>

> ⚠️ **Important:** Always use the virtual environment's `python.exe` and `pip.exe` directly (as shown above) instead of the global `python` or `pip` commands, to make sure the exe is built with the correct versions of all packages.

> ⚠️ **Important:** Don't forget to replace the _imageio-ffmpeg_ and the _pyinstaller_ file path in the PyInstaller command with your own path!

---

## Project Structure

| File               | Description                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------- |
| `main.py`           | UI layer — builds and manages all interface components, including the download queue        |
| `downloader.py`     | Download logic — runs `yt-dlp.exe` as a subprocess, format selection, ffmpeg merge, audio download |
| `ytdlp_manager.py`  | Manages the standalone `yt-dlp.exe` binary (nightly channel) — downloads it on first run and self-updates it once per app session |
| `utils.py`          | File helpers — filename sanitization, ffmpeg path, icon copy, URL cleaning                   |
| `settings.py`       | Config — reads and writes settings to `AppData\Local\VideoDownloader\config.json`            |
| `languages.py`      | Language strings for Turkish and English                                                     |

---

# SCREENSHOTS

![light](https://github.com/user-attachments/assets/6c79828f-1b69-4c82-8855-b9cd7806790b)

![dark](https://github.com/user-attachments/assets/ae49438b-c9c5-45a4-a945-3aa16c7eb6b5)

![sidebar](https://github.com/user-attachments/assets/ea224b48-ee9b-4e57-885b-144dd9548aff)

![cancel](https://github.com/user-attachments/assets/a6ecdc98-0427-4e31-be08-a724378a4f02)
