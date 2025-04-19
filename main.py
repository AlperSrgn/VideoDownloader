import glob
import re
import shutil
import subprocess
import sys
import webbrowser
import unicodedata
import yt_dlp
import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import json
from plyer import notification





# EXE ve script için doğru klasörü bul
def get_appData_path(app_name="VideoDownloader"):
    local_appdata = os.getenv('LOCALAPPDATA')  # C:\Users\KullaniciAdi\AppData\Local
    app_folder = os.path.join(local_appdata, app_name)
    os.makedirs(app_folder, exist_ok=True)  # klasör yoksa oluştur
    return app_folder



# iconları EXE nin bulunduğu dizine kopyala
def copy_icon():
    if getattr(sys, 'frozen', False):  # Sadece exe olarak çalışıyorsa
        exe_dizin = get_appData_path()
        hedef_notificationIcon_yolu = os.path.join(exe_dizin, "notificationIcon.ico")
        hedef_previewIcon_yolu = os.path.join(exe_dizin, "previewIcon.ico")
        hedef_appIcon_yolu = os.path.join(exe_dizin, "appIcon.ico")
        # Kaynak dosya (.ico dosyası .py dosyasıyla aynı klasörde olmalı)
        kaynak_notificationIcon_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notificationIcon.ico")
        kaynak_previewIcon_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previewIcon.ico")
        kaynak_appIcon_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "appIcon.ico")
        # Eğer dosya yoksa kopyala
        if not os.path.exists(hedef_notificationIcon_yolu):
            try:
                shutil.copy2(kaynak_notificationIcon_yolu, hedef_notificationIcon_yolu)
                shutil.copy2(kaynak_previewIcon_yolu, hedef_previewIcon_yolu)
                shutil.copy2(kaynak_appIcon_yolu, hedef_appIcon_yolu)
            except Exception as e:
                print(f"Icon kopyalama hatası: {e}")
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



# ProgressBar indirme bilgileri
def progress_hook(d):
    if d['status'] == 'downloading':
        try:
            percent = float(d['_percent_str'].strip('%'))
            downloaded = d.get('downloaded_bytes', 0) / (1024 * 1024)  # MB
            total_size = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            total_size_mb = total_size / (1024 * 1024) if total_size else 0
            speed = d.get('_speed_str', '0MiB')
            eta = d.get('_eta_str', '00:00:00')
            progress_bar['value'] = percent
            progress_label.config(
                text=f"{percent:.1f}% of {total_size_mb:.2f}MiB in {eta} at {speed}/s \n'Tamamlandı' mesajını "
                     f"görene kadar lütfen bekleyin"
            )
            root.update_idletasks()
        except Exception as e:
            print("Progress Hook Hatası:", str(e))



# Türkçe karakterleri değiştirerek dosya adlarını temizleme
def temizle_dosya_adi(dosya_adi):
    dosya_adi = dosya_adi.replace("ı", "i")  # 'ı' harflerini 'i' harfine çevir
    dosya_adi = unicodedata.normalize("NFKD", dosya_adi).encode("ascii", "ignore").decode("utf-8")
    dosya_adi = re.sub(r"[^\w\s.-]", "", dosya_adi)  # Geçersiz karakterleri kaldır
    dosya_adi = dosya_adi.replace(" ", "_")  # Boşlukları alt çizgiye çevir

    return dosya_adi



# Video indirme ve birleştirme
def youtube_video_indir_birlestir(url, kayit_yeri, hedef_cozunurluk):
    # Çözünürlük için yükseklik eşlemesi
    cozunurluk_haritasi = {
        "720p": 720,
        "1080p": 1080,
        "2K": 1440,
        "4K": 2160
    }

    # Geçerli çözünürlük kontrolü
    if hedef_cozunurluk not in cozunurluk_haritasi:
        messagebox.showerror("Hata", f"Geçersiz çözünürlük: {hedef_cozunurluk}")
        return

    yukseklik = cozunurluk_haritasi[hedef_cozunurluk]

    # Video bilgilerini al
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        video_title = info.get("title", "indirilen_video")

    temiz_video_title = temizle_dosya_adi(video_title)
    base_filename = os.path.join(kayit_yeri, temiz_video_title)

    # İndirme ayarları
    ydl_opts_video = {
        "format": f"bestvideo[height={yukseklik}]/bestvideo",
        "outtmpl": f"{base_filename}_(Video).%(ext)s",
        "progress_hooks": [progress_hook]
    }
    ydl_opts_audio = {
        "format": "bestaudio",
        "outtmpl": f"{base_filename}_(Ses).%(ext)s",
        "progress_hooks": [progress_hook]
    }

    # İndir
    with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
        ydl.download([url])
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

    while not os.path.exists(video_path) or not os.path.exists(audio_path):
        time.sleep(1)

    try:
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

        # ffmpeg için konsol ekranı açar
        # subprocess.run(ffmpeg_cmd, check=True)

        # ffmpeg için konsol ekranı olmadan çalıştırma
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

        os.remove(video_path)
        os.remove(audio_path)

        if sistem_bildirim_var.get():
            notification.notify(
                title="İndirme Tamamlandı",
                message="Video başarıyla indirildi",
                timeout=3,
                app_icon = notificationIcon_path
            )
        else:
            messagebox.showinfo("Başarılı", f"İşlem tamamlandı!")

    except Exception as e:
        messagebox.showerror("Hata", f"Birleştirme hatası\n{str(e)}")



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
            "progress_hooks": [progress_hook]
        }

        with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
            ydl.download([url])

        update_file_timestamp(os.path.join(kayit_yeri, output_filename))

        if sistem_bildirim_var.get():
            notification.notify(
                title="İndirme Tamamlandı",
                message="Ses dosyası başarıyla indirildi.",
                timeout=3,
                app_icon=notificationIcon_path
            )
        else:
            messagebox.showinfo("Başarılı", f"İşlem tamamlandı!")

    except Exception as e:
        messagebox.showerror("Hata", f"Ses indirilemedi:\n{str(e)}")



# İndir butonuna ait fonksiyon
def indir():
    url = url_entry.get()
    secim = secenek_var.get()
    kayit_yeri = os.path.join(os.path.expanduser("~"), "Downloads")

    if not url:
        messagebox.showwarning("Uyarı", "Lütfen bir video linki girin!")
        return

    indir_buton["state"] = "disabled"
    progress_bar.pack(pady=10)
    progress_bar["value"] = 0
    progress_label.pack()

    def indirme_islemi():
        try:
            if secim == "Ses":
                youtube_ses_indir(url, kayit_yeri)
            else:
                # Görsel seçim etiketinden çözünürlük etiketini ayıkla
                cozunurluk_haritasi = {
                    "720p": "720p",
                    "1080p": "1080p",
                    "1440p (2K)": "2K",
                    "2160p (4K)": "4K"
                }

                hedef_cozunurluk = cozunurluk_haritasi.get(secim)
                if hedef_cozunurluk:
                    youtube_video_indir_birlestir(url, kayit_yeri, hedef_cozunurluk)
                else:
                    messagebox.showerror("Hata", f"Bilinmeyen çözünürlük: {secim}")

        except Exception as e:
            messagebox.showerror("Hata", f"Bir hata oluştu:\n{str(e)}")
        finally:
            progress_bar.pack_forget()
            progress_label.pack_forget()
            indir_buton["state"] = "normal"

    threading.Thread(target=indirme_islemi, daemon=True).start()


#######################################################################################################################
#######################################################################################################################


# Arayüz oluşturma
root = tk.Tk()
root.title("Video Downloader")
root.geometry("800x300")
root.config(bg="#fbfbfb")

frame = tk.Frame(root, bg="#fbfbfb")
frame.pack(pady=30, padx=30)

# İndirme seçenekleri
secenek_var = tk.StringVar()
secenekler = ["2160p (4K)" , "1440p (2K)" , "1080p" , "720p" , "Ses"]
secenek_var.set(secenekler[0])

# 'Kalite' text
indirme_secenegi_label = tk.Label(frame, text="Kalite:", font=("Helvetica", 12 , ""), bg="#fbfbfb", fg="#2e2e2e")
indirme_secenegi_label.grid(row=0, column=0, padx=10, pady=5)

# 'Video URL' text
video_url_label = tk.Label(frame, text="Video URL:", font=("Helvetica", 12 , ""), bg="#fbfbfb", fg="#2e2e2e")
video_url_label.grid(row=0, column=2, padx=10, pady=5)

# URL sağ tık menü
def entry_sag_tik_menusu(entry):
    menu = tk.Menu(entry, tearoff=0, bg="#f0f0f0", fg="#000", activebackground="#0078D7", activeforeground="white",
                   bd=0, relief="flat")

    def sag_tik(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    menu.add_command(label="Kes", command=lambda: entry.event_generate("<<Cut>>"))
    menu.add_command(label="Kopyala", command=lambda: entry.event_generate("<<Copy>>"))
    menu.add_command(label="Yapıştır", command=lambda: entry.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Tümünü Seç", command=lambda: entry.event_generate("<<SelectAll>>"))

    entry.bind("<Button-3>", sag_tik)

# URL alanı
url_entry = tk.Entry(frame, width=50)
url_entry.grid(row=0, column=3, padx=10, pady=5)

# Sağ tık menüsü ekle
entry_sag_tik_menusu(url_entry)


# Stil ayarı (Combobox için)
style = ttk.Style()
style.configure("TCombobox", background="white", fieldbackground="white")

# Combobox'u oluşturma
secenek_menu = ttk.Combobox(frame, textvariable=secenek_var, values=secenekler, state="readonly", width=20)
secenek_menu.grid(row=0, column=1, padx=10, pady=5)


# İndir butonu
def on_enter(e):
    indir_buton.config(bg="#1f567a")  # Hover rengi (daha açık)

def on_leave(e):
    indir_buton.config(bg="#458bc6")  # Normal rengi

indir_buton = tk.Button(root, text="⬇ İndir", command=indir, width=11, height=2,
                        font=("Helvetica", 12, "bold"),
                        fg="#fbfbfb", bg="#458bc6",
                        relief="flat",
                        activebackground="#3a688d",
                        activeforeground="#fbfbfb",
                        bd=0,
                        highlightthickness=0
                        )
indir_buton.pack(pady=20)
indir_buton.bind("<Enter>", on_enter)  # Mouse içine girince
indir_buton.bind("<Leave>", on_leave)  # Mouse çıkınca


# ProgressBar
progress_bar = ttk.Progressbar(root, mode="determinate", length=300)
progress_label = tk.Label(root, text="İndirme Başlıyor...", bg="#fbfbfb", fg="#2e2e2e")


# İndirilenler klasörünü açma fonksiyonu
def open_downloads_folder():
    downloads_path = os.path.expanduser("~/Downloads")
    if os.name == "nt":  # Windows
        os.startfile(downloads_path)
    elif os.name == "posix":  # macOS & Linux
        webbrowser.open(downloads_path)

# İndirilenler klasörünü açma butonu (Sol alt köşe)
downloads_button = tk.Button(root, text="📁", command=open_downloads_folder,
                        font=("Helvetica", 19, "bold"),
                        fg="black",
                        bg="#ddd",
                        relief="flat",
                        activebackground="#bbb",
                        activeforeground="black",
                        bd=0, highlightthickness=0
                        )
downloads_button.place(relx=0, rely=1, anchor="sw", x=10, y=-10)



# Tema değiştirme fonksiyonu
dark_mode = False
def toggle_theme():
    global dark_mode
    if dark_mode:
        root.config(bg="#fbfbfb")
        frame.config(bg="#fbfbfb")
        theme_button.config(text="🌙", bg="#ddd", fg="black", activebackground="#bbb", activeforeground="black")
        downloads_button.config(bg="#ddd", fg="black", activebackground="#bbb", activeforeground="black")

        # Labels
        indirme_secenegi_label.config(bg="#fbfbfb", fg="#2e2e2e")
        video_url_label.config(bg="#fbfbfb", fg="#2e2e2e")
        progress_label.config(bg="#fbfbfb", fg="#2e2e2e")

        # Menü butonu açık mod rengi (sadece sidebar kapalıysa gösterilir)
        if not sidebar_acik:
            menu_button.config(bg="#fbfbfb", fg="#2e2e2e", activebackground="#d0d0d0", activeforeground="#000")

    else:
        root.config(bg="#2e2e2e")
        frame.config(bg="#2e2e2e")
        theme_button.config(text="☀", bg="#444", fg="white", activebackground="#666", activeforeground="#fbfbfb")
        downloads_button.config(bg="#444", fg="white", activebackground="#666", activeforeground="#fbfbfb")

        # Labels
        indirme_secenegi_label.config(bg="#2e2e2e", fg="#fbfbfb")
        video_url_label.config(bg="#2e2e2e", fg="#fbfbfb")
        progress_label.config(bg="#2e2e2e", fg="#fbfbfb")

        # Menü butonu koyu mod rengi (sidebar kapalıysa gösterilir)
        if not sidebar_acik:
            menu_button.config(bg="#2e2e2e", fg="white", activebackground="#444", activeforeground="white")

    dark_mode = not dark_mode

# Koyu mod butonu
theme_button = tk.Button(root, text="🌙", command=toggle_theme,
                         font=("Helvetica", 19, "bold"),
                         fg="black", bg="#ddd",
                         relief="flat",
                         activebackground="#bbb",
                         activeforeground="black",
                         bd=0, highlightthickness=0
                         )
theme_button.place(relx=1, rely=1, anchor="se", x=-10, y=-10)



# Sidebar toggle sistemi
sidebar_acik = False
sidebar_x = -250  # Başlangıç konumu
sidebar_genislik = 250

# Sidebar frame sadece bir kez tanımlanmalı
sidebar_frame = tk.Frame(root, width=sidebar_genislik, height=300, bg="#95aec9")
sidebar_frame.place(x=sidebar_x, y=0, relheight=1)


# BUTONA TIKLAYINCA BİLDİRİM GÖNDERME
# Bildirim Önizleme
def bildirim_onizleme():
    if sistem_bildirim_var.get():
        notification.notify(
            title="Önizleme",
            message="Sistem bildirimi bu şekilde görünür.",
            timeout=3,
            app_icon=previewIcon_path
        )
    else:
        messagebox.showinfo("Önizleme", "Uygulama bildirimi bu şekilde görünür.")
bildirim_buton = tk.Button(
    sidebar_frame,
                text="bildirimi önizle",
                command=bildirim_onizleme,
                bg="#95aec9",
                fg="#000",
                activebackground="#95aec9",
                activeforeground="#000",
                bd=1,  # kenarlık kalınlığı
                relief="solid",
)

bildirim_buton.place(x=10, y=-10, rely=1.0, anchor="sw")
# BUTONA TIKLAYINCA BİLDİRİM GÖNDERME


# Sidebar kapatma butonu (✕)
sidebar_kapatma_butonu = tk.Button(sidebar_frame,
                            text="✕",  # Çarpı işareti
                            font=("Helvetica", 14, ""),
                            bg="#95aec9",
                            fg="#000",
                            relief="flat",
                            command=lambda: sidebar_kapat_if_gerekirse(None),
                            activebackground="#7d98b3",
                            )
sidebar_kapatma_butonu.place(relx=1.0, x=-10, y=10, anchor="ne")

def animate_sidebar(target_x, step):
    global sidebar_x
    if sidebar_x != target_x:
        # Bir adım yaklaştır
        sidebar_x += step
        sidebar_frame.place(x=sidebar_x, y=0)
        # Hedefe ulaşmadıysa tekrar çağır
        root.after(5, lambda: animate_sidebar(target_x, step))
    else:
        sidebar_frame.place(x=target_x, y=0)

def toggle_sidebar():
    global sidebar_acik, sidebar_x
    if sidebar_acik:
        animate_sidebar(-sidebar_genislik, -10)               # Kapat
        menu_button.place(x=10, y=10, width=45, height=45)    # Geri getir
        menu_button.config(bg="#fbfbfb", activebackground="#d0d0d0")
    else:
        animate_sidebar(0, 10)                   # Aç
        menu_button.place_forget()               # Butonu gizle
    sidebar_acik = not sidebar_acik

def sidebar_kapat_if_gerekirse(event=None):
    global sidebar_acik

    if not sidebar_acik:
        return

    if event is not None:
        x, y = event.x_root, event.y_root
        sidebar_abs_x = sidebar_frame.winfo_rootx()
        sidebar_abs_y = sidebar_frame.winfo_rooty()
        sidebar_width = sidebar_frame.winfo_width()
        sidebar_height = sidebar_frame.winfo_height()

        # Tıklama sidebar dışındaysa kapat
        if (sidebar_abs_x <= x <= sidebar_abs_x + sidebar_width and
            sidebar_abs_y <= y <= sidebar_abs_y + sidebar_height):
            return

    # Sidebar'ı kapat
    animate_sidebar(-sidebar_genislik, -10)
    menu_button.place(x=10, y=10, width=45, height=45)

    # Tema durumuna göre renk ayarla
    if dark_mode:
        menu_button.config(bg="#2e2e2e", fg="white", activebackground="#444", activeforeground="white")
    else:
        menu_button.config(bg="#fbfbfb", fg="#2e2e2e", activebackground="#d0d0d0", activeforeground="#000")

    sidebar_acik = False
root.bind("<Button-1>", sidebar_kapat_if_gerekirse)


# Toggle butonu
menu_button = tk.Button(root,
                        text="≡",
                        font=("Helvetica", 25, "bold"),
                        bg="#fbfbfb",
                        fg="#2e2e2e",
                        relief="flat",
                        command=toggle_sidebar,
                        activebackground="#d0d0d0",
                        activeforeground="#000")
menu_button.place(x=10, y=10, width=45, height=45)      # Yerleştir ve en üste getir
menu_button.lift()


# Sidebar içeriği için çerçeve (liste gibi dizmek için)
sidebar_icerik = tk.Frame(sidebar_frame, bg="#95aec9")
sidebar_icerik.pack(padx=10, pady=50, anchor="nw")


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

def sistem_bildirim_degisti():
    ayar_kaydet("sistem_bildirimi", sistem_bildirim_var.get())

# 1. Seçenek
sistem_bildirim_var = tk.BooleanVar()
sistem_bildirim_var.set(ayar_yukle("sistem_bildirimi", False))
sistem_bildirim_var.trace_add("write", lambda *args: ayar_kaydet("sistem_bildirimi", sistem_bildirim_var.get()))

sistem_bildirim_checkbox = tk.Checkbutton(
                        sidebar_icerik,
                        text="İşlem tamamlandığında\nsistem bildirimi al",
                        variable=sistem_bildirim_var,
                        command=sistem_bildirim_degisti,  # Değişince kaydet
                        font=("Helvetica", 11),
                        bg="#95aec9", fg="#000",
                        activebackground="#95aec9",
                        activeforeground="#000",
                        justify="left",
                        anchor="w",
)
sistem_bildirim_checkbox.pack(anchor="w", pady=5, fill="x")


# 2. Seçenek
koyu_mod_var = tk.BooleanVar()
koyu_mod_var.set(ayar_yukle("koyu_modda_baslat", False))
koyu_mod_var.trace_add("write", lambda *args: ayar_kaydet("koyu_modda_baslat", koyu_mod_var.get()))

koyu_modda_baslat_checkbox = tk.Checkbutton(
                        sidebar_icerik,
                        text="Koyu modda başlat",
                        variable=koyu_mod_var,
                        font=("Helvetica", 11),
                        bg="#95aec9", fg="#000",
                        activebackground="#95aec9",
                        activeforeground="#000",
                        justify="left",
                        anchor="w"
)
koyu_modda_baslat_checkbox.pack(anchor="w", pady=5, fill="x")

# Eğer koyu mod aktifse başlarken uygula
if ayar_yukle("koyu_modda_baslat", False):
    toggle_theme()



root.mainloop()




