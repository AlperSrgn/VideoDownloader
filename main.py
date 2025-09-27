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
        raise Exception(aktif_dil["indirme_iptal_edildi"])

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
                     f"{aktif_dil['islem_devam_ediyor']}"
            )

            root.update_idletasks()

        except Exception as e:
            print("Progress Hook Error:", e)



# Türkçe karakterleri değiştirerek dosya adlarını temizleme
def temizle_dosya_adi(dosya_adi):
    dosya_adi = dosya_adi.replace("ı", "i")  # 'ı' harflerini 'i' harfine çevir
    dosya_adi = unicodedata.normalize("NFKD", dosya_adi).encode("ascii", "ignore").decode("utf-8")
    dosya_adi = re.sub(r"[^\w\s.-]", "", dosya_adi)  # Geçersiz karakterleri kaldır
    dosya_adi = dosya_adi.replace(" ", "_")  # Boşlukları alt çizgiye çevir

    return dosya_adi



# Video indirme ve birleştirme
def youtube_video_indir_birlestir(url, kayit_yeri, hedef_cozunurluk):
    cozunurluk_haritasi = {
        "720p": 720,
        "1080p": 1080,
        "2K": 1440,
        "4K": 2160
    }

    if hedef_cozunurluk not in cozunurluk_haritasi:
        messagebox.showerror("Error", f"Invalid resolution: {hedef_cozunurluk}")
        return

    yukseklik = cozunurluk_haritasi[hedef_cozunurluk]

    # Video bilgilerini al
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        video_title = info.get("title", "indirilen_video")

    temiz_video_title = temizle_dosya_adi(video_title)
    base_filename = os.path.join(kayit_yeri, temiz_video_title)

    # Progress'i göstermek için global bar'ı sıfırla
    progress_bar.set(0)
    progress_bar.pack(pady=10)
    #progress_label.configure(text="Video indiriliyor...")
    progress_label.pack()

    # İndirme ayarları
    ydl_opts_video = {
        "format": f"bestvideo[height={yukseklik}]/bestvideo",
        "outtmpl": f"{base_filename}_(Video).%(ext)s",
        "progress_hooks": [progress_hook],
        "quiet": True
    }

    ydl_opts_audio = {
        "format": "bestaudio",
        "outtmpl": f"{base_filename}_(Ses).%(ext)s",
        "progress_hooks": [progress_hook],
        "quiet": True
    }

    # Video indir
    with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
        ydl.download([url])

    # Ses indir
    #progress_label.configure(text="Ses indiriliyor...")
    with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
        ydl.download([url])

    # Dosya yolları
    video_path = glob.glob(f"{base_filename}_(Video).*")[0]
    audio_path = glob.glob(f"{base_filename}_(Ses).*")[0]

    # Çıkış dosyası
    output_filename = unique_filename(kayit_yeri, f"{temiz_video_title}.mp4")
    output_path = os.path.join(kayit_yeri, output_filename)

    update_file_timestamp(video_path)
    update_file_timestamp(audio_path)

    # Dosyalar hazır mı kontrolü
    while not os.path.exists(video_path) or not os.path.exists(audio_path):
        time.sleep(1)

    try:
        # Birleştirme
        ffmpeg_path = get_ffmpeg_path()
        ffmpeg_cmd = [
            ffmpeg_path,
            "-loglevel", "quiet",
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-strict", "experimental",
            output_path
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        with open(os.devnull, 'w') as devnull:
            subprocess.run(
                ffmpeg_cmd,
                stdout=devnull,
                stderr=devnull,
                check=True,
                creationflags=creationflags
            )

        # Geçici dosyaları sil
        os.remove(video_path)
        os.remove(audio_path)

        if sistem_bildirim_var.get():
            notification.notify(
                title=aktif_dil["operation_completed"],
                message=aktif_dil["download_complete_message"],
                timeout=3,
                app_icon=notificationIcon_path
            )
        else:
            messagebox.showinfo(
                aktif_dil["info_title"],
                aktif_dil["download_complete_message"]
            )

    except Exception as e:
        messagebox.showerror("Error", f"Merge error:\n{str(e)}")

    finally:
        progress_bar.pack_forget()
        progress_label.pack_forget()



# Video sesini indirme
def youtube_ses_indir(url, kayit_yeri):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_title = info.get("title", "indirilen_ses")

        temiz_video_title = temizle_dosya_adi(audio_title)
        output_filename = unique_filename(kayit_yeri, f"{temiz_video_title}.mp3")

        ydl_opts_audio = {
            "format": "bestaudio",
            "outtmpl": os.path.join(kayit_yeri, output_filename),
            "progress_hooks": [progress_hook],
            "quiet": True
        }

        with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
            ydl.download([url])

        update_file_timestamp(os.path.join(kayit_yeri, output_filename))

        if sistem_bildirim_var.get():
            notification.notify(
                title=aktif_dil["operation_completed"],
                message=aktif_dil["audio_download_complete_message"],
                timeout=3,
                app_icon=notificationIcon_path
            )
        else:
            messagebox.showinfo(
                aktif_dil["info_title"],
                aktif_dil["audio_download_complete_message"]
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
    temiz_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))

    return temiz_url



# İndir butonuna ait fonksiyon
def indir():
    global cancel_download
    cancel_download = False  # Her yeni işlemde sıfırla
    url = clear_playlist_parameter(url_entry.get())
    secim = secenek_var.get()
    kayit_yeri = os.path.join(os.path.expanduser("~"), "Downloads")

    if not url:
        messagebox.showwarning(
            aktif_dil["warning_title"],
            aktif_dil["empty_url_warning"]
        )
        return

    indir_buton.configure(state="disabled")
    url_entry.configure(state="disabled")
    kalite_secenek_menu.configure(state="disabled")
    playlist_checkbox.configure(state="disabled")

    iptal_buton.pack(pady=5)

    # Progress bar ve label'ı göster
    progress_bar.set(0)
    progress_bar.pack(pady=10)
    progress_label.configure(text=aktif_dil["indirme_baslatiliyor"])
    progress_label.pack()

    def indirme_islemi():
        try:
            if secim == aktif_dil["audio"]:
                youtube_ses_indir(url, kayit_yeri)
            else:
                cozunurluk_haritasi = {
                    "720p": "720p",
                    "1080p ᴴᴰ": "1080p",
                    "1440p ²ᴷ": "2K",
                    "2160p ⁴ᴷ": "4K"
                }
                hedef_cozunurluk = cozunurluk_haritasi.get(secim)
                if hedef_cozunurluk:
                    youtube_video_indir_birlestir(url, kayit_yeri, hedef_cozunurluk)
                else:
                    messagebox.showerror(
                        aktif_dil["error_title"],
                        aktif_dil["quality_error_message"]
                    )
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred:\n{str(e)}")
        finally:
            bildirim_button.configure(state="normal")
            dil_menu_button.configure(state="normal")
            indir_buton.configure(state="normal")
            url_entry.configure(state="normal")
            kalite_secenek_menu.configure(state="normal")
            playlist_checkbox.configure(state="normal")

            iptal_buton.pack_forget()  # Gizle
            progress_bar.pack_forget()
            progress_label.pack_forget()

    threading.Thread(target=indirme_islemi, daemon=True).start()



# İptal fonksiyonu
def indirmeyi_iptal_et():
    global cancel_download
    cancel_download = True
    progress_label.configure(text=aktif_dil["indirme_iptal_ediliyor"])


# Url list parametre kontrolüne göre checkbox gizleme
def url_changed(*args):
    url = url_var.get()
    if "list=" in url:
        playlist_checkbox.grid()  # Checkbox'ı göster
    else:
        playlist_checkbox.grid_remove()  # Checkbox'ı gizle


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
secenek_var = ctk.StringVar(value="1080p ᴴᴰ")
#secenekler = ["720p", "1080p ᴴᴰ", "1440p ²ᴷ", "2160p ⁴ᴷ", "Ses"]

# 'Kalite' etiketi
indirme_secenegi_label = ctk.CTkLabel(frame, font=ctk.CTkFont(size=16))
indirme_secenegi_label.grid(row=0, column=0, padx=10, pady=5)

# Seçim menüsü (Combobox eşdeğeri)
kalite_secenek_menu = ctk.CTkOptionMenu(
    frame,
    variable=secenek_var,
    # values=secenekler,
    fg_color="#e0e0e0",         # Menü butonunun arka plan rengi
    text_color="#333333",       # Yazı rengi
    button_color="#d0d0d0",     # Açılır ok butonunun rengi
    button_hover_color="#c0c0c0"  # Hover sırasında ok butonu rengi
)
kalite_secenek_menu.grid(row=0, column=1, padx=10, pady=5)


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


# İndir butonu (customtkinter versiyonu)
indir_buton = ctk.CTkButton(
    root,
    command=indir,
    width=120,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#458bc6",         # Normal arka plan rengi
    hover_color="#1f567a",      # Hover (üstüne gelince) rengi
    text_color="#fbfbfb" ,       # Yazı rengi
    corner_radius=5
)
indir_buton.pack(pady=20)


# İptal butonu
iptal_buton = ctk.CTkButton(
    root,
    command=lambda: indirmeyi_iptal_et(),
    width=120,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#ebebeb",         # Arka plan rengi
    hover_color="#dddddd",      # Hover rengi
    text_color="#d9534f",
    border_color="#d9534f",  # Kenarlık rengi (aynı tonla uyumlu)
    border_width=1,            # Kenarlık kalınlığı
    corner_radius=5

)
iptal_buton.pack(pady=0)
iptal_buton.pack_forget()  # Başta görünmesin

# ProgressBar
progress_bar = ctk.CTkProgressBar(master=root, orientation="horizontal", width=300, height=15)
progress_bar.set(0)
progress_bar.pack(pady=10)
progress_bar.pack_forget()  # Başta gizli

progress_label = ctk.CTkLabel(master=root, text="", font=("Helvetica", 13))
progress_label.pack()
progress_label.pack_forget()



# İndirilenler klasörünü açma fonksiyonu
def open_downloads_folder():
    downloads_path = os.path.expanduser("~/Downloads")
    if os.name == "nt":  # Windows
        os.startfile(downloads_path)
    elif os.name == "posix":  # macOS & Linux
        webbrowser.open(downloads_path)

# 📁 İndirilenler klasörünü açma butonu
downloads_button = ctk.CTkButton(
    master=root,
    text="📁",
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


# Koyu mod geçiş fonksiyonu
koyu_mod = False  # Başlangıçta açık modda
def toggle_theme():
    global koyu_mod
    if koyu_mod:
        # Koyu moddan çık, açık moda geç
        root.configure(fg_color="#ebebeb")
        frame.configure(fg_color="#ebebeb")  # Frame'in arka planını şeffaf yap
        video_url_label.configure(text_color="#333333")  # Etiket rengini açığa döndür
        indirme_secenegi_label.configure(text_color="#333333")  # Etiket rengini açığa döndür
        downloads_button.configure(fg_color="#dddddd")
        theme_button.configure(text="🌙",fg_color="#dddddd")
        menu_button.configure(fg_color="#ebebeb", text_color="#333333", hover_color="#d0d0d0")
        progress_label.configure(text_color="#333333", bg_color="#ebebeb")
        url_entry.configure(fg_color="#ffffff", text_color="#333333")
        iptal_buton.configure(fg_color="#ebebeb", hover_color="#dddddd")
        playlist_checkbox.configure(text_color="#333333", bg_color="#ebebeb", border_color="#333333", fg_color="#333333", checkmark_color="#ebebeb")
        kalite_secenek_menu.configure(fg_color="#e0e0e0",  text_color="#333333",  button_color="#d0d0d0",  button_hover_color="#c0c0c0")
        koyu_mod = False
    else:
        # Koyu moda geç
        root.configure(fg_color="#333333")
        frame.configure(fg_color="#333333")  # Frame'in arka planını koyu yap
        video_url_label.configure(text_color="#ebebeb")  # Etiket rengini beyaza çevir
        indirme_secenegi_label.configure(text_color="#ebebeb")  # Etiket rengini beyaza çevir
        downloads_button.configure(fg_color="#565656")
        theme_button.configure(text="🌞", fg_color="#565656")
        menu_button.configure(fg_color="#333333",text_color="#d0d0d0", hover_color="#565656")
        progress_label.configure(text_color="#ebebeb", bg_color="#333333")
        iptal_buton.configure(fg_color="#333333", hover_color="#565656",)
        url_entry.configure(fg_color="#565656", text_color="#ebebeb")            #URL alanı
        playlist_checkbox.configure(text_color="#ebebeb", bg_color="#333333", border_color="#ebebeb", fg_color="#ebebeb", checkmark_color="#333333")
        kalite_secenek_menu.configure(fg_color="#565656", text_color="#ebebeb", button_color="#444444", button_hover_color="#666666")
        koyu_mod = True

# 🌙 Koyu mod geçiş butonu
theme_button = ctk.CTkButton(
    master=root,
    text="🌙",  # Başlangıçta "🌙" sembolü
    width=50,
    height=50,
    font=("Helvetica", 30, "bold"),
    fg_color="#dddddd",  # Arka plan rengi
    hover_color="#bbbbbb",  # Üzerine gelinceki rengi
    text_color="black",  # Yazı rengi
    corner_radius=8,  # Yuvarlak köşe
    command=toggle_theme  # Butona tıklanınca toggle_theme fonksiyonunu çalıştır
)

theme_button.place(relx=1, rely=1, anchor="se", x=-10, y=-10)


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
sidebar_icerik = ctk.CTkFrame(sidebar_frame, fg_color="#95aec9")
sidebar_icerik.pack(padx=0, pady=0, anchor="nw", fill="both", expand=True)


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
    font=("Helvetica", 20),
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


# Dil değiştirme
def dili_degistir(secili_dil):
    global aktif_dil
    aktif_dil = LANGUAGES.get(secili_dil, LANGUAGES["Tr"])  # fallback
    indir_buton.configure(text=aktif_dil["indir"])
    iptal_buton.configure(text=aktif_dil["iptal"])
    url_entry.configure(placeholder_text=aktif_dil["link_placeholder"])
    indirme_secenegi_label.configure(text=aktif_dil["kalite"])
    sistem_bildirim_checkbox.configure(text=aktif_dil["sistem_bildirim_checkbox"])
    koyu_modda_baslat_checkbox.configure(text=aktif_dil["koyu_modda_baslat_checkbox"])
    bildirim_button.configure(text=aktif_dil["bildirim_button"])
    playlist_checkbox.configure(text=aktif_dil["oynatma_listesi_checkbox_text"])
    # Seçenekleri yeniden oluştur ve dropdown'a yükle
    secenekler = [
        aktif_dil["2160p"],
        aktif_dil["1440p"],
        aktif_dil["1080p"],
        aktif_dil["720p"],
        aktif_dil["audio"]
    ]
    kalite_secenek_menu.configure(values=secenekler)
    ayar_kaydet("dil", secili_dil)


# Dil seçenekleri
dil_secenekleri = ["Tr", "En"]
dil_var = ctk.StringVar(value=dil_secenekleri[0])  # Varsayılan dil Türkçe
dil_menu_button = ctk.CTkOptionMenu(
    sidebar_icerik,
    variable=dil_var,
    values=dil_secenekleri,
    command=dili_degistir,  # <==
    width=70,
    height=30,
    font=("Helvetica", 12),
    fg_color="#4c6a8c",
    button_color="#004566",
    text_color="#ebebeb"
)
# Sidebar içindeki dil menüsünü sağ alt köşeye yerleştir
dil_menu_button.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)


# Toggle butonu (≡) - Sidebar'ı kontrol etmek için
menu_button = ctk.CTkButton(
    master=root,
    text="≡",
    font=("Helvetica", 45, "bold"),
    fg_color="#ebebeb",  # Başlangıçta açık gri
    text_color="#333333",
    width=50,
    height=50,
    command=toggle_sidebar,  # Butona tıklandığında sidebar'ı aç
    hover_color="#d0d0d0"
)
menu_button.place(x=10, y=10)


# config.json dosya islemleri
config_path = os.path.join(get_appData_path(), "config.json")

def ayar_yukle(anahtar, varsayilan=False):
    try:
        if os.path.exists(config_path) and os.path.getsize(config_path) > 0:
            with open(config_path, "r", encoding="utf-8") as dosya:
                ayarlar = json.load(dosya)
                return ayarlar.get(anahtar, varsayilan)
    except Exception as e:
        print("Ayar yükleme hatası:", e)
    return varsayilan

def ayar_kaydet(anahtar, deger):
    try:
        ayarlar = {}
        if os.path.exists(config_path) and os.path.getsize(config_path) > 0:
            with open(config_path, "r", encoding="utf-8") as dosya:
                ayarlar = json.load(dosya)

        ayarlar[anahtar] = deger

        with open(config_path, "w", encoding="utf-8") as dosya:
            json.dump(ayarlar, dosya, indent=4)
    except Exception as e:
        print("Ayar kaydetme hatası:", e)
# config.json dosya islemleri


def sistem_bildirim_degisti():
    ayar_kaydet("sistem_bildirimi", sistem_bildirim_var.get())

# Butona tıklatınca bildirim gönderme
def bildirim_onizleme():
    if sistem_bildirim_var.get():
        notification.notify(
            title=aktif_dil["preview_info_title"],
            message=aktif_dil["system_notification_message"],
            timeout=3,
            app_icon=previewIcon_path
        )
    else:
        messagebox.showinfo(
            aktif_dil["preview_info_title"],
            aktif_dil["preview_info_message"]
        )

# "Bildirimi Önizle" butonu
bildirim_button = ctk.CTkButton(
    master=sidebar_icerik,
    font=("Helvetica", 12),
    command=bildirim_onizleme,
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    width=100,
    height=30
)
# Butonu sol alt köşeye yerleştir
bildirim_button.place(x=10, y=-10, relx=0, rely=1, anchor="sw")


# Sidebar 1. checkbox
sistem_bildirim_var = ctk.BooleanVar()
sistem_bildirim_var.set(ayar_yukle("sistem_bildirimi", True))
sistem_bildirim_var.trace_add("write", lambda *args: ayar_kaydet("sistem_bildirimi", sistem_bildirim_var.get()))

sistem_bildirim_checkbox = ctk.CTkCheckBox(
    master=sidebar_icerik,
    variable=sistem_bildirim_var,
    onvalue=True,
    offvalue=False,
    command=sistem_bildirim_degisti,
    font=("Helvetica", 15),
    text_color="black",
    fg_color="#95aec9",
    hover_color="#6c8a9e",
    border_color="black",
    border_width=2,
    checkmark_color="black",
)
sistem_bildirim_checkbox.pack(anchor="w", pady=(60, 20), padx=10, fill="x")


# Sidebar 2. checkbox
koyu_mod_var = ctk.BooleanVar()
koyu_mod_var.set(ayar_yukle("koyu_modda_baslat", False))
koyu_mod_var.trace_add("write", lambda *args: ayar_kaydet("koyu_modda_baslat", koyu_mod_var.get()))

koyu_modda_baslat_checkbox = ctk.CTkCheckBox(
    master=sidebar_icerik,
    variable=koyu_mod_var,
    command=lambda: ayar_kaydet("koyu_modda_baslat", koyu_mod_var.get()),
    onvalue=True,
    offvalue=False,
    font=("Helvetica", 15),
    text_color="black",
    fg_color="#95aec9",
    hover_color="#6c8a9e",
    border_color="black",
    border_width=2,
    checkmark_color="black",
)
koyu_modda_baslat_checkbox.pack(anchor="w", pady=10, padx=10, fill="x")

# Eğer koyu mod aktifse başlarken uygula
if koyu_mod_var.get():
    toggle_theme()

# Dil ayarları
aktif_dil = ayar_yukle("dil", "Tr")
dil_var.set(aktif_dil)
dili_degistir(aktif_dil)  # GUI'yi seçilen dile göre başlat


root.mainloop()




