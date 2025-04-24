# VIDEO DOWNLOADER
Download videos from websites. Provides the following features:
+ Download videos up to 4k resolution [ 2160P(4K), 1440P(2K), 1080P, 720P, Audio ]
+ Download the audio of the video
+ Dark mode feature
+ Choose notification type
+ Download videos by URL
+ Automatically selects a video format based on your quality demands
  
Based on [yt-dlp](https://github.com/yt-dlp/yt-dlp).



# INSTALLATION
If you want to install into the IDE with the `git clone` command from Github, you need to install [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) from the terminal.  
Install using:  

`$ pip install imageio-ffmpeg`  

After running this command, the *imageio-ffmpeg* installation will be completed.  


**Note:** If you have a problem with the directory where *imageio-ffmpeg* is installed, Edit the code below, which belongs to the `get_ffmpeg_path()` function in the **main.py**, according to your own *imageio-ffmpeg* file path.

`$ return os.path.join(project_dir, ".venv", "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe")`  


---
After downloading to the IDE, you can use this command to convert it to **exe file** with [**pyinstaller**](https://github.com/pyinstaller/pyinstaller):  

`$ pyinstaller --onefile --noconsole --add-binary "C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --add-data "languages.py;." --hidden-import=plyer.platforms.win.notification main.py`


**Note:** Don't forget to replace the *imageio-ffmpeg* file path in this pyinstaller command with your own *imageio-ffmpeg* file path!


---
## [**CLICK HERE**](https://github.com/AlperSrgn/X-Youtube-Video-Downloader/releases/tag/v1.0.0) to see versions available for download. (VideoDownloaderSetup.exe)

**Note:** Video Downloader comes bundled with FFmpeg which is used for processing videos. When you download it as a setup file, you do not need to take any action. 
You can complete the installation process by running the setup file.  


# SCREENSHOTS

![light](https://github.com/user-attachments/assets/5cb8211b-ba49-456e-aa0f-8f99e4d9db72)

![dark](https://github.com/user-attachments/assets/a23b70d5-48b5-4d22-8923-c187d0ea0a6f)

![sidebar](https://github.com/user-attachments/assets/d44efd5a-65fe-4d32-97fb-3d2e9c0c6b96)

![cancel](https://github.com/user-attachments/assets/0bc69bef-ef59-4151-918d-16478f066c6a)


