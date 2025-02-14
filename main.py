import re

import unicodedata
import yt_dlp
import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from moviepy import VideoFileClip, AudioFileClip


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
                text=f"{percent:.1f}% of {total_size_mb:.2f}MiB in {eta} at {speed}/s"
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


# 720p video indirme
def youtube_720p_video_indir(url, kayit_yeri):
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        video_title = info.get("title", "indirilen_video")

    # Türkçe karakterleri temizle
    temiz_video_title = temizle_dosya_adi(video_title)
    output_filename = unique_filename(kayit_yeri, f"{temiz_video_title}.mp4")

    ydl_opts = {
        "format": "best[height<=720]",
        "outtmpl": os.path.join(kayit_yeri, output_filename),
        "progress_hooks": [progress_hook]
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    update_file_timestamp(os.path.join(kayit_yeri, output_filename))


# 1080p video indirme
def youtube_1080p_video_ses_indir(url, kayit_yeri):
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        video_title = info.get("title", "indirilen_video")

    # Türkçe karakterleri temizle
    temiz_video_title = temizle_dosya_adi(video_title)

    video_filename = f"{temiz_video_title}_(Video).mp4"
    audio_filename = f"{temiz_video_title}_(Ses).mp3"
    output_filename = f"{temiz_video_title}.mp4"

    ydl_opts_video = {
        "format": "bestvideo[height=1080]",
        "outtmpl": os.path.join(kayit_yeri, video_filename),
        "progress_hooks": [progress_hook]
    }
    ydl_opts_audio = {
        "format": "bestaudio",
        "outtmpl": os.path.join(kayit_yeri, audio_filename),
        "progress_hooks": [progress_hook]
    }

    with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
        ydl.download([url])
    with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
        ydl.download([url])

    update_file_timestamp(os.path.join(kayit_yeri, video_filename))
    update_file_timestamp(os.path.join(kayit_yeri, audio_filename))

    # Dosyanın indirildiğinden emin ol
    while not os.path.exists(os.path.join(kayit_yeri, video_filename)):
        time.sleep(1)
    while not os.path.exists(os.path.join(kayit_yeri, audio_filename)):
        time.sleep(1)

    # Video ve ses dosyalarını birleştir
    try:
        video = VideoFileClip(os.path.join(kayit_yeri, video_filename))
        audio = AudioFileClip(os.path.join(kayit_yeri, audio_filename))

        audio = audio.with_duration(video.duration)
        video_with_audio = video.with_audio(audio)

        output_path = os.path.join(kayit_yeri, output_filename)
        video_with_audio.write_videofile(output_path, codec="libx264", audio_codec="aac")

        # Eski video ve ses dosyalarını sil
        os.remove(os.path.join(kayit_yeri, video_filename))
        os.remove(os.path.join(kayit_yeri, audio_filename))

        messagebox.showinfo("Başarılı", "Video ve ses başarıyla birleştirildi")
    except Exception as e:
        messagebox.showerror("Hata", f"Birleştirme hatası: {str(e)}")


# Video sesini indirme
def youtube_ses_indir(url, kayit_yeri):
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


# İndir butonuna ait fonksiyon
def indir():
    url = url_entry.get()
    secim = secenek_var.get()
    kayit_yeri = os.path.join(os.path.expanduser("~"), "Downloads")

    if not url:
        messagebox.showwarning("Uyarı", "Lütfen bir video linki girin!")
        return

    progress_bar.pack(pady=10)
    progress_bar["value"] = 0
    progress_label.pack()

    def indirme_islemi():
        try:
            if secim == "720p":
                youtube_720p_video_indir(url, kayit_yeri)
            elif secim == "Ses":
                youtube_ses_indir(url, kayit_yeri)
            elif secim == "1080p":
                youtube_1080p_video_ses_indir(url, kayit_yeri)
            messagebox.showinfo("Başarılı", "İndirme tamamlandı!")
        except Exception as e:
            messagebox.showerror("Hata", f"Bir hata oluştu:\n{str(e)}")
        finally:
            progress_bar.pack_forget()
            progress_label.pack_forget()

    threading.Thread(target=indirme_islemi, daemon=True).start()



