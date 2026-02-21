import logging
import os
import subprocess
import sys
import threading
import webbrowser

import customtkinter as ctk
from plyer import notification
from tkinter import messagebox

from downloader import download_video, download_audio
from languages import LANGUAGES
from settings import load_setting, save_setting
from utils import clean_playlist_url, copy_icons, get_icon_path

# Convert to exe file
# pyinstaller --onefile --noconsole --add-binary "C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --add-data "languages.py;." --add-data "settings.py;." --add-data "utils.py;." --add-data "downloader.py;." --hidden-import=plyer.platforms.win.notification main.py

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------
copy_icons()
NOTIFICATION_ICON = get_icon_path("notificationIcon.ico")
PREVIEW_ICON = get_icon_path("previewIcon.ico")
APP_ICON = get_icon_path("appIcon.ico")


# ---------------------------------------------------------------------------
# yt-dlp version (async)
# ---------------------------------------------------------------------------
def fetch_ytdlp_version(callback):
    def worker():
        try:
            import yt_dlp
            callback(f"yt-dlp v{yt_dlp.version.__version__}")
        except Exception:
            callback("yt-dlp version unavailable")
    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
def uninstall_app():
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    uninstall_path = os.path.join(app_dir, "unins000.exe")

    if not messagebox.askyesno(
        current_language["uninstall_app_title"],
        current_language["uninstall_app_message"]
    ):
        return

    if os.path.exists(uninstall_path):
        subprocess.Popen([uninstall_path])
        sys.exit()
    else:
        messagebox.showerror(
            current_language["error_title"],
            current_language["file_not_found_error"]
        )


# ---------------------------------------------------------------------------
# Theme definitions (module-level constant)
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "root":                {"fg_color": "#333333"},
        "frame":               {"fg_color": "#333333"},
        "video_url_label":     {"text_color": "#ebebeb"},
        "download_option_label": {"text_color": "#ebebeb"},
        "light_dark":          {"text": "🔆"},
        "downloads_button":    {"fg_color": "#565656"},
        "menu_button":         {"fg_color": "#333333", "text_color": "#d0d0d0", "hover_color": "#565656"},
        "progress_label":      {"text_color": "#ebebeb", "bg_color": "#333333"},
        "cancel_button":       {"fg_color": "#333333", "hover_color": "#565656"},
        "url_entry":           {"fg_color": "#565656", "text_color": "#ebebeb"},
        "playlist_checkbox":   {
            "text_color": "#ebebeb", "bg_color": "#333333",
            "border_color": "#ebebeb", "fg_color": "#ebebeb", "checkmark_color": "#333333"
        },
        "quality_options_menu": {
            "fg_color": "#565656", "text_color": "#ebebeb",
            "button_color": "#444444", "button_hover_color": "#666666"
        },
    },
    "light": {
        "root":                {"fg_color": "#ebebeb"},
        "frame":               {"fg_color": "#ebebeb"},
        "video_url_label":     {"text_color": "#333333"},
        "download_option_label": {"text_color": "#333333"},
        "light_dark":          {"text": "🌙"},
        "downloads_button":    {"fg_color": "#dddddd"},
        "menu_button":         {"fg_color": "#ebebeb", "text_color": "#333333", "hover_color": "#d0d0d0"},
        "progress_label":      {"text_color": "#333333", "bg_color": "#ebebeb"},
        "cancel_button":       {"fg_color": "#ebebeb", "hover_color": "#dddddd"},
        "url_entry":           {"fg_color": "#ffffff", "text_color": "#333333"},
        "playlist_checkbox":   {
            "text_color": "#333333", "bg_color": "#ebebeb",
            "border_color": "#333333", "fg_color": "#333333", "checkmark_color": "#ebebeb"
        },
        "quality_options_menu": {
            "fg_color": "#e0e0e0", "text_color": "#333333",
            "button_color": "#d0d0d0", "button_hover_color": "#c0c0c0"
        },
    },
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
dark_mode = False
cancel_requested = False
current_language: dict = {}
sidebar_open = False
SIDEBAR_WIDTH = 250
sidebar_x = -SIDEBAR_WIDTH


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def set_widgets_state(state: str):
    for w in [
        preview_notification_button, download_button, url_entry,
        quality_options_menu, playlist_checkbox, uninstall_button,
    ]:
        w.configure(state=state)


def show_progress(text: str = ""):
    progress_bar.set(0)
    progress_bar.pack(pady=10)
    progress_label.configure(text=text)
    progress_label.pack()


def hide_progress():
    progress_bar.pack_forget()
    progress_label.pack_forget()


def on_progress(percent: float, downloaded_mb: float, total_mb: float, eta: str):
    progress_bar.set(percent / 100)
    progress_label.configure(
        text=(
            f"{percent:.1f}%   |   {downloaded_mb:.2f} / {total_mb:.2f} MB   |   {eta}\n"
            f"{current_language['operation_in_progress_message']}"
        )
    )
    root.update_idletasks()


def on_cancel_check() -> bool:
    return cancel_requested


def on_download_done(success_msg_key: str):
    root.after(0, lambda: _finalize_download(success_msg_key))


def _finalize_download(success_msg_key: str):
    hide_progress()
    set_widgets_state("normal")
    cancel_button.pack_forget()

    if system_notification_enabled.get():
        notification.notify(
            title=current_language["operation_completed_message"],
            message=current_language[success_msg_key],
            timeout=3,
            app_icon=NOTIFICATION_ICON,
        )


def on_download_error(msg: str):
    root.after(0, lambda: _handle_error(msg))


def _handle_error(msg: str):
    hide_progress()
    set_widgets_state("normal")
    cancel_button.pack_forget()
    messagebox.showerror(current_language["error_title"], msg)


# ---------------------------------------------------------------------------
# Download entry point
# ---------------------------------------------------------------------------
def start_download():
    global cancel_requested
    cancel_requested = False

    raw_url = url_entry.get().strip()
    if not raw_url:
        messagebox.showwarning(
            current_language["warning_title"],
            current_language["empty_url_warning"],
        )
        return

    if not raw_url.startswith(("http://", "https://")):
        messagebox.showwarning(
            current_language["warning_title"],
            current_language["invalid_url_warning"],
        )
        return

    url = clean_playlist_url(raw_url)
    selection = option_var.get()
    save_location = os.path.join(os.path.expanduser("~"), "Downloads")

    set_widgets_state("disabled")
    cancel_button.pack(pady=5)
    show_progress(current_language["download_starting_message"])

    resolution_ui_map = {
        "720p":       "720p",
        "1080p ᴴᴰ":  "1080p",
        "1440p ²ᴷ":  "2K",
        "2160p ⁴ᴷ":  "4K",
    }

    if selection == current_language.get("audio"):
        download_audio(
            url=url,
            save_location=save_location,
            on_progress=on_progress,
            on_cancel_check=on_cancel_check,
            on_done=lambda: on_download_done("audio_download_complete_message"),
            on_error=on_download_error,
            lang=current_language,
        )
    elif selection in resolution_ui_map:
        download_video(
            url=url,
            save_location=save_location,
            target_resolution=resolution_ui_map[selection],
            on_progress=on_progress,
            on_cancel_check=on_cancel_check,
            on_done=lambda: on_download_done("download_complete_message"),
            on_error=on_download_error,
            lang=current_language,
        )
    else:
        _handle_error(current_language["quality_error_message"])


def cancel_download():
    global cancel_requested
    cancel_requested = True
    progress_label.configure(text=current_language["download_canceling_message"])


# ---------------------------------------------------------------------------
# Theme toggle
# ---------------------------------------------------------------------------
def toggle_theme():
    global dark_mode
    theme_key = "dark" if not dark_mode else "light"
    theme = THEMES[theme_key]

    widget_map = {
        "root":                root,
        "frame":               frame,
        "video_url_label":     video_url_label,
        "download_option_label": download_option_label,
        "light_dark":          light_dark,
        "downloads_button":    downloads_button,
        "menu_button":         menu_button,
        "progress_label":      progress_label,
        "cancel_button":       cancel_button,
        "url_entry":           url_entry,
        "playlist_checkbox":   playlist_checkbox,
        "quality_options_menu": quality_options_menu,
    }

    for key, widget in widget_map.items():
        widget.configure(**theme[key])

    dark_mode = not dark_mode


# ---------------------------------------------------------------------------
# Sidebar animation
# ---------------------------------------------------------------------------
def animate_sidebar(target_x: int, step: int):
    global sidebar_x
    if sidebar_x != target_x:
        sidebar_x = max(target_x, min(0, sidebar_x + step)) if step > 0 else max(target_x, sidebar_x + step)
        sidebar_frame.place(x=sidebar_x, y=0)
        root.after(5, lambda: animate_sidebar(target_x, step))
    else:
        sidebar_frame.place(x=target_x, y=0)


def toggle_sidebar():
    global sidebar_open
    if sidebar_open:
        animate_sidebar(-SIDEBAR_WIDTH, -10)
        menu_button.place(x=10, y=10)
    else:
        animate_sidebar(0, 10)
        menu_button.place_forget()
    sidebar_open = not sidebar_open


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------
def change_language(selected: str):
    global current_language
    current_language = LANGUAGES.get(selected, LANGUAGES["Tr"])

    label_map = {
        download_button:             "download",
        cancel_button:               "cancel",
        download_option_label:       "kalite",
        system_notification_checkbox: "system_notification_checkbox",
        start_in_dark_mode_checkbox:  "start_in_dark_mode_checkbox",
        preview_notification_button:  "preview_notification_button",
        playlist_checkbox:            "playlist_checkbox_text",
        uninstall_button:             "uninstall_button",
    }
    for widget, key in label_map.items():
        widget.configure(text=current_language[key])

    url_entry.configure(placeholder_text=current_language["link_placeholder"])

    dropdown_options = [
        current_language["2160p"],
        current_language["1440p"],
        current_language["1080p"],
        current_language["720p"],
        current_language["audio"],
    ]
    quality_options_menu.configure(values=dropdown_options)
    save_setting("language", selected)


# ---------------------------------------------------------------------------
# URL change handler
# ---------------------------------------------------------------------------
def url_changed(*_):
    if "list=" in url_var.get():
        pass  # playlist_checkbox.grid()  — playlist support pending
    else:
        playlist_checkbox.grid_remove()


# ---------------------------------------------------------------------------
# Misc UI callbacks
# ---------------------------------------------------------------------------
def open_downloads_folder():
    path = os.path.expanduser("~/Downloads")
    if os.name == "nt":
        os.startfile(path)
    else:
        webbrowser.open(path)


def preview_notification():
    if system_notification_enabled.get():
        notification.notify(
            title=current_language["preview_info_title"],
            message=current_language["system_notification_message"],
            timeout=3,
            app_icon=PREVIEW_ICON,
        )


# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------
root = ctk.CTk()
root.title("Video Downloader")
root.geometry("800x370")
root.iconbitmap(APP_ICON)

# Main frame
frame = ctk.CTkFrame(root, fg_color="#ebebeb")
frame.pack(pady=30, padx=30)

# Quality label
download_option_label = ctk.CTkLabel(frame, font=ctk.CTkFont(size=16))
download_option_label.grid(row=0, column=0, padx=10, pady=5)

# Quality dropdown
option_var = ctk.StringVar(value="1080p ᴴᴰ")
quality_options_menu = ctk.CTkOptionMenu(
    frame,
    variable=option_var,
    fg_color="#e0e0e0",
    text_color="#333333",
    button_color="#d0d0d0",
    button_hover_color="#c0c0c0",
)
quality_options_menu.grid(row=0, column=1, padx=10, pady=5)

# URL label
video_url_label = ctk.CTkLabel(frame, text="Video URL:", font=ctk.CTkFont(size=16))
video_url_label.grid(row=0, column=2, padx=10, pady=5)

# URL entry
url_var = ctk.StringVar()
url_var.trace_add("write", url_changed)
url_entry = ctk.CTkEntry(frame, width=300, textvariable=url_var)
url_entry.grid(row=0, column=3, padx=10, pady=5)

# Playlist checkbox (hidden until list= detected)
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
    corner_radius=4,
)
playlist_checkbox.grid(row=1, column=3, sticky="w", padx=10, pady=5)
playlist_checkbox.grid_remove()

# Download button
download_button = ctk.CTkButton(
    root,
    command=start_download,
    width=120,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#458bc6",
    hover_color="#1f567a",
    text_color="#fbfbfb",
    corner_radius=5,
)
download_button.pack(pady=20)

# Cancel button
cancel_button = ctk.CTkButton(
    root,
    command=cancel_download,
    width=120,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#ebebeb",
    hover_color="#dddddd",
    text_color="#d9534f",
    border_color="#d9534f",
    border_width=2,
    corner_radius=5,
)
cancel_button.pack(pady=0)
cancel_button.pack_forget()

# Progress bar
progress_bar = ctk.CTkProgressBar(root, orientation="horizontal", width=300, height=15)
progress_bar.set(0)
progress_bar.pack(pady=10)
progress_bar.pack_forget()

# Progress label
progress_label = ctk.CTkLabel(root, text="", font=("Helvetica", 13))
progress_label.pack()
progress_label.pack_forget()

# Downloads folder button
downloads_button = ctk.CTkButton(
    root,
    text="📂",
    command=open_downloads_folder,
    width=50, height=50,
    font=("Helvetica", 30, "bold"),
    fg_color="#dddddd",
    hover_color="#bbbbbb",
    text_color="black",
    corner_radius=8,
)
downloads_button.place(relx=0, rely=1, anchor="sw", x=10, y=-10)

# Sidebar
sidebar_frame = ctk.CTkFrame(root, width=SIDEBAR_WIDTH, fg_color="#95aec9", corner_radius=0)
sidebar_frame.place(x=sidebar_x, y=0, relheight=1)

sidebar_content = ctk.CTkFrame(sidebar_frame, fg_color="#95aec9")
sidebar_content.pack(padx=0, pady=0, anchor="nw", fill="both", expand=True)

close_button = ctk.CTkButton(
    sidebar_frame,
    text="✕",
    font=("Helvetica", 19),
    fg_color="#95aec9",
    text_color="black",
    width=35, height=35,
    command=toggle_sidebar,
    hover_color="#6c8a9e",
)
close_button.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

# Menu (hamburger) button
menu_button = ctk.CTkButton(
    root,
    text="☰",
    font=("Helvetica", 30, "bold"),
    fg_color="#ebebeb",
    text_color="#333333",
    width=50, height=50,
    command=toggle_sidebar,
    hover_color="#d0d0d0",
)
menu_button.place(x=10, y=10)

# Light/dark toggle inside sidebar
light_dark = ctk.CTkButton(
    sidebar_content,
    text="🌙",
    font=("Helvetica", 30),
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    width=45, height=45,
    command=toggle_theme,
)
light_dark.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)

# Language selector
language_options = ["Tr", "En"]
language_var = ctk.StringVar(value=language_options[0])
language_menu = ctk.CTkOptionMenu(
    sidebar_content,
    variable=language_var,
    values=language_options,
    command=change_language,
    width=70, height=30,
    font=("Helvetica", 13),
    fg_color="#4c6a8c",
    button_color="#004566",
    text_color="#ebebeb",
)
language_menu.place(relx=1.0, rely=1.0, anchor="se", x=-85, y=-10)

# System notification checkbox
system_notification_enabled = ctk.BooleanVar(value=load_setting("system_notification", True))
system_notification_enabled.trace_add(
    "write",
    lambda *_: save_setting("system_notification", system_notification_enabled.get()),
)
system_notification_checkbox = ctk.CTkCheckBox(
    sidebar_content,
    variable=system_notification_enabled,
    onvalue=True, offvalue=False,
    font=("Helvetica", 14),
    text_color="black",
    fg_color="#95aec9",
    hover_color="#6c8a9e",
    border_color="black",
    border_width=2,
    checkbox_width=20, checkbox_height=20,
    corner_radius=4,
    checkmark_color="black",
)
system_notification_checkbox.pack(anchor="w", pady=(60, 20), padx=10, fill="x")

# Start in dark mode checkbox
dark_mode_enabled = ctk.BooleanVar(value=load_setting("start_in_dark_mode", False))
dark_mode_enabled.trace_add(
    "write",
    lambda *_: save_setting("start_in_dark_mode", dark_mode_enabled.get()),
)
start_in_dark_mode_checkbox = ctk.CTkCheckBox(
    sidebar_content,
    variable=dark_mode_enabled,
    onvalue=True, offvalue=False,
    font=("Helvetica", 14),
    text_color="black",
    fg_color="#95aec9",
    hover_color="#6c8a9e",
    border_color="black",
    border_width=2,
    checkbox_width=20, checkbox_height=20,
    corner_radius=4,
    checkmark_color="black",
)
start_in_dark_mode_checkbox.pack(anchor="w", pady=10, padx=10, fill="x")

# Preview notification button
preview_notification_button = ctk.CTkButton(
    sidebar_content,
    font=("Helvetica", 13),
    command=preview_notification,
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    width=35, height=35,
)
preview_notification_button.place(x=10, y=-70, relx=0, rely=1, anchor="sw")

# Uninstall button
uninstall_button = ctk.CTkButton(
    sidebar_content,
    command=uninstall_app,
    font=("Helvetica", 13),
    width=70, height=30,
    fg_color="#cc3b3b",
    hover_color="#ff4c4c",
    text_color="#fbfbfb",
)
uninstall_button.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

# yt-dlp version label (populated asynchronously)
yt_dlp_version_label = ctk.CTkLabel(
    root,
    text="",
    font=ctk.CTkFont(size=10),
    text_color="#888888",
)
yt_dlp_version_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)
fetch_ytdlp_version(lambda t: yt_dlp_version_label.configure(text=t))

# ---------------------------------------------------------------------------
# Apply saved settings on startup
# ---------------------------------------------------------------------------
if dark_mode_enabled.get():
    toggle_theme()

saved_lang = load_setting("language", "Tr")
language_var.set(saved_lang)
change_language(saved_lang)

# ---------------------------------------------------------------------------
root.mainloop()
