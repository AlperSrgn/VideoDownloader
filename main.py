import glob
import re
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

    # Geçerli çözünürlük mü kontrolü
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
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-strict", "experimental",
            output_path
        ]
        subprocess.run(ffmpeg_cmd, check=True)

        os.remove(video_path)
        os.remove(audio_path)

        messagebox.showinfo("Tamamlandı", "İşlem tamamlandı!")

    except Exception as e:
        messagebox.showerror("Hata", f"Birleştirme hatası: {str(e)}")



# Video sesini indirme
def youtube_ses_indir(url, kayit_yeri):
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_title = info.get("title", "indirilen_ses")

        # Türkçe karakterleri temizle
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

        # Bilgilendirme mesajı göster
        messagebox.showinfo("Başarılı", f"İşlem tamamlandı!")

    except Exception as e:
        # Hata mesajı göster
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
indir_buton = tk.Button(root, text="⬇ İndir", command=indir, width=11, height=2,
                        font=("Helvetica", 12, "bold"),
                        fg="#fbfbfb", bg="#458bc6",
                        relief="flat",
                        activebackground="#3a688d",
                        activeforeground="#fbfbfb",
                        bd=0,
                        highlightthickness=0)
indir_buton.pack(pady=20)


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
                             font=("Helvetica", 13, "bold"), fg="black", bg="#ddd",
                             relief="flat", activebackground="#bbb",
                             activeforeground="black", bd=0, highlightthickness=0)
downloads_button.place(relx=0, rely=1, anchor="sw", x=10, y=-10)


# Koyu mod değişkeni
dark_mode = False

# Tema değiştirme fonksiyonu
def toggle_theme():
    global dark_mode
    if dark_mode:
        root.config(bg="#fbfbfb")
        frame.config(bg="#fbfbfb")
        theme_button.config(text="🌙", bg="#ddd", fg="black", activebackground="#bbb", activeforeground="black")
        downloads_button.config(bg="#ddd", fg="black", activebackground="#bbb", activeforeground="black")

        # Label renklerini açık moda uygun hale getir
        indirme_secenegi_label.config(bg="#fbfbfb", fg="#2e2e2e")
        video_url_label.config(bg="#fbfbfb", fg="#2e2e2e")
        progress_label.config(bg="#fbfbfb", fg="#2e2e2e")

    else:
        root.config(bg="#2e2e2e")
        frame.config(bg="#2e2e2e")
        theme_button.config(text="☀", bg="#444", fg="white", activebackground="#666", activeforeground="#fbfbfb")
        downloads_button.config(bg="#444", fg="white", activebackground="#666", activeforeground="#fbfbfb")

        # Label renklerini koyu moda uygun hale getir
        indirme_secenegi_label.config(bg="#2e2e2e", fg="#fbfbfb")
        video_url_label.config(bg="#2e2e2e", fg="#fbfbfb")
        progress_label.config(bg="#2e2e2e", fg="#fbfbfb")

    dark_mode = not dark_mode

# Koyu mod butonu
theme_button = tk.Button(root, text="🌙", command=toggle_theme,
                         font=("Helvetica", 13, "bold"),
                         fg="black", bg="#ddd",
                         relief="flat",
                         activebackground="#bbb",
                         activeforeground="black",
                         bd=0, highlightthickness=0)
theme_button.place(relx=1, rely=1, anchor="se", x=-10, y=-10)

root.mainloop()


