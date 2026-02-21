# VIDEO DOWNLOADER

Download videos from websites. Provides the following features:

- Download videos up to 4K resolution [ 2160P(4K), 1440P(2K), 1080P, 720P ]
- Download the audio of the video as MP3
- Dark mode feature
- System notification support with preview
- Download videos by URL
- Automatically selects the best video format based on your quality preference
- Automatically handles SABR-protected YouTube videos by trying multiple clients

Based on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

---

# INSTALLATION

## Download VideoDownloaderSetup.exe

### [![İNDİR](https://github.com/user-attachments/assets/8d8adf06-7013-4017-8434-51984f624e3b)](https://github.com/AlperSrgn/VideoDownloader/releases/download/v2.0/VideoDownloaderSetup.exe)

<br>

**Note:** Video Downloader comes bundled with FFmpeg which is used for merging video and audio streams. When you download it as a setup file, you do not need to take any action.
You can complete the installation process by running the setup file.

---

## Install in IDE

If you want to install into the IDE with the `git clone` command from Github, you need to install [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) from the terminal after installation.

**Install using:**

`$ pip install imageio-ffmpeg`

After running this command, the _imageio-ffmpeg_ installation will be completed.  
<br><br>

**Note:** If you have a problem with the directory where _imageio-ffmpeg_ is installed, edit the `get_ffmpeg_path()` function in **utils.py** according to your own _imageio-ffmpeg_ file path:

`$ return os.path.join(project_dir, ".venv", "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe")`

---

## Convert to Exe

The project must be built using the **virtual environment's** Python and PyInstaller to ensure the correct versions of all packages (especially yt-dlp) are bundled.

**Step 1 — Install PyInstaller into the virtual environment:**

`$ C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Scripts\pip.exe install pyinstaller`

**Step 2 — Build the exe:**

`$ pyinstaller --onefile --noconsole --add-binary "C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --add-data "languages.py;." --add-data "settings.py;." --add-data "utils.py;." --add-data "downloader.py;." --hidden-import=plyer.platforms.win.notification main.py`

<br>

> ⚠️ **Important:** Always use the virtual environment's `python.exe` and `pip.exe` directly (as shown above) instead of the global `python` or `pip` commands. Using the global commands may cause an older or different version of yt-dlp to be bundled, which can break video downloads.

> ⚠️ **Important:** Don't forget to replace the _imageio-ffmpeg_ and the _pyinstaller_ file path in the PyInstaller command with your own path!

---

## Project Structure

| File            | Description                                                                       |
| --------------- | --------------------------------------------------------------------------------- |
| `main.py`       | UI layer — builds and manages all interface components                            |
| `downloader.py` | Download logic — yt-dlp format selection, ffmpeg merge, audio download            |
| `utils.py`      | File helpers — filename sanitization, ffmpeg path, icon copy, URL cleaning        |
| `settings.py`   | Config — reads and writes settings to `AppData\Local\VideoDownloader\config.json` |
| `languages.py`  | Language strings for Turkish and English                                          |

---

# SCREENSHOTS

![light](https://github.com/user-attachments/assets/9ac1b144-e211-46a9-8372-5c16926c38da)

![dark](https://github.com/user-attachments/assets/649260b1-45c8-46b3-a837-fcffbc007278)

![sidebar](https://github.com/user-attachments/assets/15486dc0-f65a-4317-b65e-2d466a6de46e)

![cancel](https://github.com/user-attachments/assets/8204f73e-0ed2-4df3-a762-a4a536916d54)
