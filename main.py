import glob
import re
import shutil
import subprocess
import sys
import webbrowser
import unicodedata
import os
from tkinter import messagebox
import threading
import time
import json
import yt_dlp
from plyer import notification
import customtkinter as ctk
from languages import LANGUAGES
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


# exe
# pyinstaller --onefile --noconsole --add-binary "C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --add-data "languages.py;." --hidden-import=plyer.platforms.win.notification main.py

# Get yt-dlp version
def get_yt_dlp_version(callback):
    def worker():
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            output = subprocess.check_output(
                ["yt-dlp", "--version"],
                text=True,
                startupinfo=startupinfo
            )
            version_str = f"yt-dlp v{output.strip()}"
        except Exception as e:
            version_str = "Failed to retrieve yt-dlp version"

        # Update the label via the main thread
        callback(version_str)

    threading.Thread(target=worker, daemon=True).start()



# Uygulamayı kaldır
def uninstall_app():
    # Uygulamanın bulunduğu dizini al
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    uninstall_path = os.path.join(app_dir, "unins000.exe")

    # Kullanıcıya onay penceresi göster
    answer = messagebox.askyesno(current_language["uninstall_app_title"], current_language["uninstall_app_message"])

    # No
    if not answer:
        return

    # Yes
    if os.path.exists(uninstall_path):
        subprocess.Popen([uninstall_path])
        sys.exit()  # Uygulamayı sonlandır
    else:
        messagebox.showerror(current_language["error_title"], current_language["file_not_found_error"])



# EXE ve script için doğru klasörü bul
def get_appData_path(app_name="VideoDownloader"):
    local_appdata = os.getenv('LOCALAPPDATA')  # C:\Users\KullaniciAdi\AppData\Local
    app_folder = os.path.join(local_appdata, app_name)
    os.makedirs(app_folder, exist_ok=True)  # klasör yoksa oluştur
    return app_folder



# iconları AppData klasörüne kopyala
def copy_icon():
    exe_dizin = get_appData_path()
    kaynak_dizin = os.path.dirname(os.path.abspath(__file__))

    hedef_notificationIcon_yolu = os.path.join(exe_dizin, "notificationIcon.ico")
    hedef_previewIcon_yolu = os.path.join(exe_dizin, "previewIcon.ico")
    hedef_appIcon_yolu = os.path.join(exe_dizin, "appIcon.ico")

    kaynak_notificationIcon_yolu = os.path.join(kaynak_dizin, "notificationIcon.ico")
    kaynak_previewIcon_yolu = os.path.join(kaynak_dizin, "previewIcon.ico")
    kaynak_appIcon_yolu = os.path.join(kaynak_dizin, "appIcon.ico")

    try:
        os.makedirs(exe_dizin, exist_ok=True)
        if not os.path.exists(hedef_notificationIcon_yolu):
            shutil.copy2(kaynak_notificationIcon_yolu, hedef_notificationIcon_yolu)
        if not os.path.exists(hedef_previewIcon_yolu):
            shutil.copy2(kaynak_previewIcon_yolu, hedef_previewIcon_yolu)
        if not os.path.exists(hedef_appIcon_yolu):
            shutil.copy2(kaynak_appIcon_yolu, hedef_appIcon_yolu)
    except Exception as e:
        print(f"Icon copy error: {e}")

copy_icon()
notificationIcon_path = os.path.join(get_appData_path(), "notificationIcon.ico")
previewIcon_path = os.path.join(get_appData_path(), "previewIcon.ico")
appIcon_path = os.path.join(get_appData_path(), "appIcon.ico")



# ffmpeg path
def get_ffmpeg_path():
    # PyInstaller ile paketlenmişse ffmpeg dosyası geçici dizine çıkarılır
    if getattr(sys, 'frozen', False):
        # PyInstaller ile çalışıyorsa geçici dizine bak
        return os.path.join(sys._MEIPASS, 'ffmpeg-win-x86_64-v7.1.exe')
    else:
        # Geliştirme ortamında çalışıyorsa proje dizinindeki ffmpeg'i al
        project_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(project_dir, ".venv", "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe")



# Aynı isimde dosya inerse adını değiştirme
def unique_filename(directory, filename):
    base, ext = os.path.splitext(filename)
    counter = 1
    new_filename = filename
    while os.path.exists(os.path.join(directory, new_filename)):
        new_filename = f"{base} ({counter}){ext}"
        counter += 1
    return new_filename



# Dosyanın indirilme tarihini güncelleme
def update_file_timestamp(filepath):
    if os.path.exists(filepath):
        current_time = time.time()
        os.utime(filepath, (current_time, current_time))



# İndirme durumunu takip et
def progress_hook(d):

    global cancel_download
    if cancel_download:
        raise Exception(current_language["download_canceled_message"])

    if d['status'] == 'downloading':
        try:
            percent = float(d['_percent_str'].strip('%'))
            downloaded = d.get('downloaded_bytes', 0) / (1024 * 1024)  # MB
            total_size = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            total_size_mb = total_size / (1024 * 1024) if total_size else 0
            eta = d.get('_eta_str', '00:00:00')

            # Progress bar güncelle
            progress_bar.set(percent / 100)

            # Bilgi label'ı güncelle
            progress_label.configure(
                text=f"{percent:.1f}%   |   {downloaded:.2f} / {total_size_mb:.2f}MB    |   {eta}\n"
                     f"{current_language['operation_in_progress_message']}"
            )

            root.update_idletasks()

        except Exception as e:
            print("Progress Hook Error:", e)



# Türkçe karakterleri değiştirerek dosya adlarını temizleme
def sanitize_filename(file_name):
    file_name = file_name.replace("ı", "i")
    file_name = unicodedata.normalize("NFKD", file_name).encode("ascii", "ignore").decode("utf-8")
    file_name = re.sub(r"[^\w\s.-]", "", file_name)     # Remove invalid characters
    file_name = file_name.replace(" ", "_")

    return file_name



# Find a format suitable for SABR
def find_suitable_format(formats, video_height):
    """Finds a video+audio pair matching the target resolution and validates the URL."""
    video_formats  = [
        f for f in formats
        if f.get("url") and f.get("vcodec") != "none" and (f.get("height") is not None)
    ]
    audio_formats = [
        f for f in formats
        if f.get("url") and f.get("acodec") != "none" and f.get("vcodec") == "none"
    ]

    if not video_formats  or not audio_formats:
        return None, None

    heights = sorted({f["height"] for f in video_formats  if f["height"] <= video_height}, reverse=True)
    if not heights:
        heights = sorted({f["height"] for f in video_formats }, reverse=True)

    for h in heights:
        candidates_v = [f for f in video_formats  if f.get("height") == h]
        if not candidates_v:
            continue
        chosen_video = sorted(candidates_v, key=lambda x: x.get("tbr") or 0, reverse=True)[0]
        chosen_audio = max(audio_formats, key=lambda x: x.get("abr", 0), default=None)

        # URL validation
        if chosen_video and chosen_audio:
            if chosen_video.get("url") and chosen_audio.get("url"):
                print(
                    f"[DEBUG] Compatible files found:\n "
                    f"Video: {chosen_video['format_id']} ({chosen_video.get('height')}p)\n "
                    f"Audio: {chosen_audio['format_id']}"
                )
                return chosen_video, chosen_audio
            else:
                print(
                    f"[DEBUG] URL missing due to SABR protection -> "
                    f"Video: {chosen_video['format_id']} ({chosen_video.get('height')}p), "
                    f"Audio: {chosen_audio['format_id']}"
                )

                return None, None



# Download and merge video and audio
def download_merge_video(url, save_location, target_resolution):

    if not url or not url.startswith(("http://", "https://")):
        messagebox.showwarning(current_language["warning_title"], current_language["invalid_url_warning"])
        return

    resolution_map = {
        "720p": 720,
        "1080p": 1080,
        "2K": 1440,
        "4K": 2160
    }

    if target_resolution not in resolution_map:
        messagebox.showerror("Error", f"Invalid resolution: {target_resolution}")
        return

    video_height = resolution_map[target_resolution]

    client_list = ["android", "web", "ios", "tv", "web_mobile"]

    video_info = None
    selected_client = None
    video_format = None
    audio_format = None

    for client in client_list:
        try:
            print(f"[DEBUG] Trying client: {client}")
            with yt_dlp.YoutubeDL({"quiet": True, "player_client": client}) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get("formats", [])
                v_fmt, a_fmt = find_suitable_format(formats, video_height)
                if v_fmt and a_fmt:
                    video_info = info
                    selected_client = client
                    video_format = v_fmt
                    audio_format = a_fmt
                    break
                else:
                    print(f"[DEBUG] Client {client}: No compatible format found or URL missing due to SABR protection.")
        except Exception as e:
            print(f"[DEBUG] Client {client} raised an error: {e}")
            continue


    if not video_info:
        messagebox.showerror(current_language["error_title"], current_language["download_video_format_error"])
        return


    video_title = video_info.get("title", "indirilen_video")
    sanitized_video_title = sanitize_filename(video_title)
    base_filename = os.path.join(save_location, sanitized_video_title)

    progress_bar.set(0)
    progress_bar.pack(pady=10)
    progress_label.pack()

    common_opts = {
        "quiet": True,
        "progress_hooks": [progress_hook],
        "player_client": selected_client,
    }

    ydl_opts_video = {
        **common_opts,
        "format": video_format["format_id"],
        "outtmpl": f"{base_filename}_(Video).%(ext)s",
    }
    ydl_opts_audio = {
        **common_opts,
        "format": audio_format["format_id"],
        "outtmpl": f"{base_filename}_(Audio).%(ext)s",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
            ydl.download([url])
        with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
            ydl.download([url])
    except Exception as e:
        messagebox.showerror("Error", f"Download error:\n{e}")
        return

    try:
        video_path = glob.glob(f"{base_filename}_(Video).*")[0]
        audio_path = glob.glob(f"{base_filename}_(Audio).*")[0]
    except IndexError:
        messagebox.showerror("Error", "The downloaded files were not found.")
        return

    output_filename = unique_filename(save_location, f"{sanitized_video_title}.mp4")
    output_path = os.path.join(save_location, output_filename)

    ffmpeg_path = get_ffmpeg_path()
    ffmpeg_cmd = [
        ffmpeg_path, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        #"-strict", "experimental",
        "-shortest",
        output_path
    ]

    subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, creationflags=subprocess.CREATE_NO_WINDOW)

    os.remove(video_path)
    os.remove(audio_path)

    # Notify when completed
    if system_notification_enabled.get():
        notification.notify(
            title=current_language["operation_completed_message"],
            message=current_language["download_complete_message"],
            timeout=3,
            app_icon=notificationIcon_path
        )
    print(f"[DEBUG] Download completed: {output_path}")

    # Reset the progress bar
    progress_bar.pack_forget()
    progress_label.pack_forget()



# Download audio only
def download_audio(url, save_location):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_title = info.get("title", "downloaded_audio")

        sanitized_video_title = sanitize_filename(audio_title)
        output_filename = unique_filename(save_location, f"{sanitized_video_title}.mp3")

        ydl_opts_audio = {
            "format": "bestaudio",
            "outtmpl": os.path.join(save_location, output_filename),
            "progress_hooks": [progress_hook],
            "quiet": True
        }

        with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
            ydl.download([url])

        update_file_timestamp(os.path.join(save_location, output_filename))

        if system_notification_enabled.get():
            notification.notify(
                title=current_language["operation_completed_message"],
                message=current_language["audio_download_complete_message"],
                timeout=3,
                app_icon=notificationIcon_path
            )

    except Exception as e:
        messagebox.showerror("Error", f"Failed to download audio:\n{str(e)}")



#URL'den list parametresini temizle
def clear_playlist_parameter(url):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    # Kaldırılacak parametreler listesi
    remove_keys = ['list', 'start_radio', 'rv']

    # Bu parametreleri temizle
    for key in remove_keys:
        query_params.pop(key, None)

    # Yeni query string oluştur
    new_query = urlencode(query_params, doseq=True)

    # Temiz URL
    clean_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))

    return clean_url



# download butonuna ait fonksiyon
def download():
    global cancel_download
    cancel_download = False     # Reset on every new operation
    url = clear_playlist_parameter(url_entry.get())
    selection = option_var.get()
    save_location = os.path.join(os.path.expanduser("~"), "Downloads")

    if not url:
        messagebox.showwarning(
            current_language["warning_title"],
            current_language["empty_url_warning"]
        )
        return

    # disabled
    for widget in [
        preview_notification_button,
        download_button,
        url_entry,
        quality_options_menu,
        playlist_checkbox,
        uninstall_button
    ]:
        widget.configure(state="disabled")

    cancel_button .pack(pady=5)

    # Show the progress bar and label
    progress_bar.set(0)
    progress_bar.pack(pady=10)
    progress_label.configure(text=current_language["download_starting_message"])
    progress_label.pack()

    def download_process():
        try:
            if selection == current_language["audio"]:
                download_audio(url, save_location)
            else:
                resolution_map = {
                    "720p": "720p",
                    "1080p ᴴᴰ": "1080p",
                    "1440p ²ᴷ": "2K",
                    "2160p ⁴ᴷ": "4K"
                }
                target_resolution = resolution_map.get(selection)
                if target_resolution:
                    download_merge_video(url, save_location, target_resolution)
                else:
                    messagebox.showerror(
                        current_language["error_title"],
                        current_language["quality_error_message"]
                    )
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred:\n{str(e)}")
        finally:

            # normal
            for widget in [
                preview_notification_button,
                download_button,
                url_entry,
                quality_options_menu,
                playlist_checkbox,
                uninstall_button
            ]:
                widget.configure(state="normal")

            cancel_button .pack_forget()  # Hide
            progress_bar.pack_forget()
            progress_label.pack_forget()

    threading.Thread(target=download_process, daemon=True).start()



# Cancel function
def cancel_download_task():
    global cancel_download
    cancel_download = True
    progress_label.configure(text=current_language["download_canceling_message"])


# Show checkbox based on URL list parameter check
def url_changed(*args):
    url = url_var.get()
    if "list=" in url:
        return
        #playlist_checkbox.grid()  # Show the checkbox
    else:
        playlist_checkbox.grid_remove()  # Hide the checkbox


#######################################################################################################################
#######################################################################################################################


# Arayüz oluşturma
root = ctk.CTk()
root.title("Video Downloader")
root.geometry("800x370")

# Ana çerçeve
frame = ctk.CTkFrame(root, fg_color="#ebebeb")
frame.pack(pady=30, padx=30)

# İndirme seçenekleri
option_var = ctk.StringVar(value="1080p ᴴᴰ")
#dropdown_options = ["720p", "1080p ᴴᴰ", "1440p ²ᴷ", "2160p ⁴ᴷ", "Ses"]

# 'Kalite' etiketi
download_option_label = ctk.CTkLabel(frame, font=ctk.CTkFont(size=16))
download_option_label.grid(row=0, column=0, padx=10, pady=5)

# Seçim menüsü (Combobox eşdeğeri)
quality_options_menu = ctk.CTkOptionMenu(
    frame,
    variable=option_var,
    # values=dropdown_options,
    fg_color="#e0e0e0",         # Menü butonunun arka plan rengi
    text_color="#333333",       # Yazı rengi
    button_color="#d0d0d0",     # Açılır ok butonunun rengi
    button_hover_color="#c0c0c0"  # Hover sırasında ok butonu rengi
)
quality_options_menu.grid(row=0, column=1, padx=10, pady=5)


# 'Video URL' etiketi
video_url_label = ctk.CTkLabel(frame, text="Video URL:", font=ctk.CTkFont(size=16))
video_url_label.grid(row=0, column=2, padx=10, pady=5)


# URL giriş alanı için StringVar ve Entry
url_var = ctk.StringVar()
url_var.trace_add("write", url_changed)  # Her değişiklikte tetiklenir
url_entry = ctk.CTkEntry(frame, width=300, textvariable=url_var)
url_entry.grid(row=0, column=3, padx=10, pady=5)


# Checkbox (başta gizli)
frame.grid_rowconfigure(1, minsize=50)
playlist_checkbox_var = ctk.BooleanVar()
playlist_checkbox = ctk.CTkCheckBox(
    frame,
    variable=playlist_checkbox_var,
    font=ctk.CTkFont(size=15),
    checkbox_height=20,
    checkbox_width=20,
    border_width=2,
    fg_color="#333333",
    hover_color="#cccccc",
    corner_radius=4
)
playlist_checkbox.grid(row=1, column=3, sticky="w", padx=10, pady=5)
playlist_checkbox.grid_remove()  # Başlangıçta gizle


# download butonu
download_button = ctk.CTkButton(
    root,
    command=download,
    width=120,
    height=45,
    #image=download_icon,
    font=("Helvetica", 14, "bold"),
    fg_color="#458bc6",         # Normal arka plan rengi
    hover_color="#1f567a",      # Hover (üstüne gelince) rengi
    text_color="#fbfbfb" ,       # Yazı rengi
    corner_radius=5
)
download_button.pack(pady=20)


# İptal butonu
cancel_button  = ctk.CTkButton(
    root,
    command=lambda: cancel_download_task(),
    width=120,
    height=45,
    #image=cancel_icon,
    font=("Helvetica", 14, "bold"),
    fg_color="#ebebeb",
    hover_color="#dddddd",
    text_color="#d9534f",
    border_color="#d9534f",
    border_width=2,
    corner_radius=5

)
cancel_button .pack(pady=0)
cancel_button .pack_forget()   # Don't show initially

# ProgressBar
progress_bar = ctk.CTkProgressBar(master=root, orientation="horizontal", width=300, height=15)
progress_bar.set(0)
progress_bar.pack(pady=10)
progress_bar.pack_forget()  # Hidden at start

# ProgressLabel
progress_label = ctk.CTkLabel(master=root, text="", font=("Helvetica", 13))
progress_label.pack()
progress_label.pack_forget()


# Function to open the Downloads folder
def open_downloads_folder():
    downloads_folder_path  = os.path.expanduser("~/Downloads")
    if os.name == "nt":  # Windows
        os.startfile(downloads_folder_path )
    elif os.name == "posix":  # macOS & Linux
        webbrowser.open(downloads_folder_path )

# 📁 Button to open the downloads folder
downloads_button = ctk.CTkButton(
    master=root,
    text="📂",
    #image=folder_icon,
    command=open_downloads_folder,
    width=50,
    height=50,
    font=("Helvetica", 30, "bold"),
    fg_color="#dddddd",            # Arka plan rengi
    hover_color="#bbbbbb",         # Üzerine gelince rengi
    text_color="black",            # Yazı rengi
    corner_radius=8,               # Buton köşe yuvarlaklığı
)
downloads_button.place(relx=0, rely=1, anchor="sw", x=10, y=-10)


# Dark mode toggle function
dark_mode = False
def toggle_theme():
    global dark_mode

    # Theme definitions
    theme = {
        True: {  # Dark mode
            "root": {"fg_color": "#333333"},
            "frame": {"fg_color": "#333333"},
            "video_url_label": {"text_color": "#ebebeb"},
            "download_option_label": {"text_color": "#ebebeb"},
            "light_dark": {"text": "🔆"},
            "downloads_button": {"fg_color": "#565656"},
            "menu_button": {"fg_color": "#333333", "text_color": "#d0d0d0", "hover_color": "#565656"},
            "progress_label": {"text_color": "#ebebeb", "bg_color": "#333333"},
            "cancel_button ": {"fg_color": "#333333", "hover_color": "#565656"},
            "url_entry": {"fg_color": "#565656", "text_color": "#ebebeb"},
            "playlist_checkbox": {
                "text_color": "#ebebeb", "bg_color": "#333333", "border_color": "#ebebeb",
                "fg_color": "#ebebeb", "checkmark_color": "#333333"
            },
            "quality_options_menu": {
                "fg_color": "#565656", "text_color": "#ebebeb",
                "button_color": "#444444", "button_hover_color": "#666666"
            },
        },
        False: {  # Light mode
            "root": {"fg_color": "#ebebeb"},
            "frame": {"fg_color": "#ebebeb"},
            "video_url_label": {"text_color": "#333333"},
            "download_option_label": {"text_color": "#333333"},
            "light_dark": {"text": "🌙"},
            "downloads_button": {"fg_color": "#dddddd"},
            "menu_button": {"fg_color": "#ebebeb", "text_color": "#333333", "hover_color": "#d0d0d0"},
            "progress_label": {"text_color": "#333333", "bg_color": "#ebebeb"},
            "cancel_button ": {"fg_color": "#ebebeb", "hover_color": "#dddddd"},
            "url_entry": {"fg_color": "#ffffff", "text_color": "#333333"},
            "playlist_checkbox": {
                "text_color": "#333333", "bg_color": "#ebebeb", "border_color": "#333333",
                "fg_color": "#333333", "checkmark_color": "#ebebeb"
            },
            "quality_options_menu": {
                "fg_color": "#e0e0e0", "text_color": "#333333",
                "button_color": "#d0d0d0", "button_hover_color": "#c0c0c0"
            },
        }
    }

    # Update components based on theme data
    current_theme = theme[not dark_mode]

    component_map = {
        "root": root,
        "frame": frame,
        "video_url_label": video_url_label,
        "download_option_label": download_option_label,
        "light_dark": light_dark,
        "downloads_button": downloads_button,
        "menu_button": menu_button,
        "progress_label": progress_label,
        "cancel_button ": cancel_button ,
        "url_entry": url_entry,
        "playlist_checkbox": playlist_checkbox,
        "quality_options_menu": quality_options_menu,
    }

    for key, widget in component_map.items():
        widget.configure(**current_theme[key])

    dark_mode = not dark_mode


# Sidebar ayarları
sidebar_acik = False
sidebar_x = -250  # Başlangıçta sidebar dışarıda
sidebar_genislik = 250  # Sidebar genişliği

# Sidebar frame
sidebar_frame = ctk.CTkFrame(
    master=root,
    width=sidebar_genislik,
    fg_color="#95aec9",  # Sidebar'ın arka plan rengi
    corner_radius=0
)
sidebar_frame.place(x=sidebar_x, y=0, relheight=1)

# Sidebar içeriği (içerik eklemek için)
sidebar_content = ctk.CTkFrame(sidebar_frame, fg_color="#95aec9")
sidebar_content.pack(padx=0, pady=0, anchor="nw", fill="both", expand=True)


# Sidebar'ı açıp kapatmak için animasyon fonksiyonu
def animate_sidebar(target_x, step):
    global sidebar_x
    if sidebar_x != target_x:
        sidebar_x += step
        sidebar_frame.place(x=sidebar_x, y=0)  # Sidebar'ı yer değiştir
        root.after(5, lambda: animate_sidebar(target_x, step))
    else:
        sidebar_frame.place(x=target_x, y=0)  # Hedef konumda dur

# Sidebar Kapatma butonu
close_button = ctk.CTkButton(
    master=sidebar_frame,
    text="✕",
    font=("Helvetica", 19),
    fg_color="#95aec9",  # Buton rengi
    text_color="black",
    width=35,
    height=35,
    command=lambda: toggle_sidebar(),  # Sidebar'ı kapatma
    hover_color="#6c8a9e"
)
close_button.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)  # Sağ üst köşeye yerleştir

# Sidebar'ı açma veya kapama fonksiyonu
def toggle_sidebar():
    global sidebar_acik
    if sidebar_acik:
        # Sidebar kapanacak
        animate_sidebar(-sidebar_genislik, -10)  # Kapatma animasyonu
        sidebar_frame.configure(fg_color="#ebebeb")  # Sidebar arka plan rengini eski haline döndür
        menu_button.place(x=10, y=10)  # Menü butonunu tekrar göster
    else:
        # Sidebar açılacak
        animate_sidebar(0, 10)  # Açma animasyonu
        sidebar_frame.configure(fg_color="#95aec9")  # Sidebar arka plan rengini değiştir
        menu_button.place_forget()  # Menü butonunu gizle
    sidebar_acik = not sidebar_acik  # Durum değiştirme


# Change language
def change_language(selected_language):
    global current_language
    current_language = LANGUAGES.get(selected_language, LANGUAGES["Tr"])  # fallback

    # Widgets to update
    widgets = {
        download_button: "download",
        cancel_button : "cancel",
        url_entry: "link_placeholder",  # placeholder_text özel olduğu için kontrol gerekir
        download_option_label: "kalite",
        system_notification_checkbox: "system_notification_checkbox",
        start_in_dark_mode_checkbox: "start_in_dark_mode_checkbox",
        preview_notification_button: "preview_notification_button",
        playlist_checkbox: "playlist_checkbox_text",
        uninstall_button: "uninstall_button",
    }

    for widget, key in widgets.items():
        if widget == url_entry:
            widget.configure(placeholder_text=current_language[key])
        else:
            widget.configure(text=current_language[key])

    # Dropdown options
    dropdown_options = [
        current_language["2160p"],
        current_language["1440p"],
        current_language["1080p"],
        current_language["720p"],
        current_language["audio"]
    ]
    quality_options_menu.configure(values=dropdown_options)

    save_setting("language", selected_language)


# Language options button
language_options = ["Tr", "En"]
language_enabled = ctk.StringVar(value=language_options[0])  # Default language is Turkish
language_menu_button = ctk.CTkOptionMenu(
    sidebar_content,
    variable=language_enabled,
    values=language_options,
    command=change_language,  # <==
    width=70,
    height=30,
    font=("Helvetica", 13),
    fg_color="#4c6a8c",
    button_color="#004566",
    text_color="#ebebeb"
)
language_menu_button.place(relx=1.0, rely=1.0, anchor="se", x=-85, y=-10)


# light-dark mode
light_dark = ctk.CTkButton(
    sidebar_content,
    text="🌙",
    font=("Helvetica", 30),
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    width=45,
    height=45,
    command=toggle_theme
)
light_dark.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)


# Toggle button (≡) to control the sidebar
menu_button = ctk.CTkButton(
    master=root,
    text="☰",
    font=("Helvetica", 30, "bold"),
    fg_color="#ebebeb",     # Light gray at startup
    text_color="#333333",
    width=50,
    height=50,
    command=toggle_sidebar,
    hover_color="#d0d0d0"
)
menu_button.place(x=10, y=10)


# config.json file operations
config_path = os.path.join(get_appData_path(), "config.json")

def load_setting(json_key, json_default=False):
    try:
        if os.path.exists(config_path) and os.path.getsize(config_path) > 0:
            with open(config_path, "r", encoding="utf-8") as json_file:
                json_settings = json.load(json_file)
                return json_settings.get(json_key, json_default)
    except Exception as e:
        print("Failed to load settings:", e)
    return json_default

def save_setting(json_key, json_value):
    try:
        json_settings = {}
        if os.path.exists(config_path) and os.path.getsize(config_path) > 0:
            with open(config_path, "r", encoding="utf-8") as json_file:
                json_settings = json.load(json_file)

        json_settings[json_key] = json_value

        with open(config_path, "w", encoding="utf-8") as json_file:
            json.dump(json_settings, json_file, indent=4)
    except Exception as e:
        print("Failed to save settings:", e)
# config.json file operations

def system_notification_changed():
    save_setting("system_notification", system_notification_enabled.get())



# Send notification when the button is clicked
def preview_notification():
    if system_notification_enabled.get():
        notification.notify(
            title=current_language["preview_info_title"],
            message=current_language["system_notification_message"],
            timeout=3,
            app_icon=previewIcon_path
        )

# "Preview Notification" button
preview_notification_button = ctk.CTkButton(
    master=sidebar_content,
    font=("Helvetica", 13),
    #image= notification_icon,
    command=preview_notification,
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    width=35,
    height=35
)
preview_notification_button.place(x=10, y=-70, relx=0, rely=1, anchor="sw")


# Delete application button
uninstall_button = ctk.CTkButton(
    command=uninstall_app,
    master=sidebar_content,
    #image= trash_icon,
    font=("Helvetica", 13),
    width=70,
    height=30,
    fg_color="#cc3b3b",
    hover_color="#ff4c4c",
    text_color="#fbfbfb",
)
uninstall_button.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)


# Sidebar 1. checkbox
system_notification_enabled = ctk.BooleanVar()
system_notification_enabled.set(load_setting("system_notification", True))
system_notification_enabled.trace_add("write", lambda *args: save_setting("system_notification", system_notification_enabled.get()))

system_notification_checkbox = ctk.CTkCheckBox(
    master=sidebar_content,
    variable=system_notification_enabled,
    onvalue=True,
    offvalue=False,
    command=system_notification_changed,
    font=("Helvetica", 14),
    text_color="black",
    fg_color="#95aec9",
    hover_color="#6c8a9e",
    border_color="black",
    border_width=2,
    checkbox_width=20,
    checkbox_height=20,
    corner_radius=4,
    checkmark_color="black",
)
system_notification_checkbox.pack(anchor="w", pady=(60, 20), padx=10, fill="x")


# Sidebar 2. checkbox
dark_mode_enabled = ctk.BooleanVar()
dark_mode_enabled.set(load_setting("start_in_dark_mode", False))
dark_mode_enabled.trace_add("write", lambda *args: save_setting("start_in_dark_mode", dark_mode_enabled.get()))

start_in_dark_mode_checkbox = ctk.CTkCheckBox(
    master=sidebar_content,
    variable=dark_mode_enabled,
    command=lambda: save_setting("start_in_dark_mode", dark_mode_enabled.get()),
    onvalue=True,
    offvalue=False,
    font=("Helvetica", 14),
    text_color="black",
    fg_color="#95aec9",
    hover_color="#6c8a9e",
    border_color="black",
    border_width=2,
    checkbox_width=20,
    checkbox_height=20,
    corner_radius=4,
    checkmark_color="black",
)
start_in_dark_mode_checkbox.pack(anchor="w", pady=10, padx=10, fill="x")

# Apply if dark mode is enabled at startup
if dark_mode_enabled.get():
    toggle_theme()

# Language settings
current_language = load_setting("language", "Tr")
language_enabled.set(current_language)
change_language(current_language)       # Initialize the GUI according to the selected language


# yt-dlp version label
yt_dlp_version_text = get_yt_dlp_version(lambda text: yt_dlp_version_label.configure(text=text))
yt_dlp_version_label = ctk.CTkLabel(
    root,
    text=yt_dlp_version_text,
    font=ctk.CTkFont(size=10),
    text_color="#888888"
)
yt_dlp_version_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)


root.mainloop()




