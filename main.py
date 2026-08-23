import itertools
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from collections import deque

import customtkinter as ctk
from plyer import notification
from tkinter import Menu, filedialog, messagebox

from downloader import download_video, download_audio
from languages import LANGUAGES
from settings import load_setting, save_setting
from utils import clean_playlist_url, copy_icons, get_icon_path

# Convert to exe file
# pyinstaller --onefile --noconsole --add-binary "C:\Users\alper\PycharmProjects\VideoDownloader\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe;." --add-data "notificationIcon.ico;." --add-data "previewIcon.ico;." --add-data "appIcon.ico;." --hidden-import=plyer.platforms.win.notification main.py

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
def fetch_ytdlp_version(callback, on_status=None):
    """Runs ensure_ytdlp (first-run download / self-update) in the background
    and reports the version via `callback`.

    If provided, `on_status(stage, percent)` is called during progress.
    This lets the UI show status while yt-dlp.exe is being downloaded.
    """
    def worker():
        try:
            from settings import get_appdata_path
            from ytdlp_manager import ensure_ytdlp, get_ytdlp_version
            # ensure_ytdlp downloads on first run and updates on later launches.
            # The auto-update runs once each time the app starts.
            exe_path = ensure_ytdlp(get_appdata_path(), on_status=on_status)
            callback(f"yt-dlp v{get_ytdlp_version(exe_path)}")
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
        "queue_header_label":  {"text_color": "#ebebeb"},
        "queue_list_frame":    {"fg_color": "#3d3d3d"},
        "queue_item_label":    {"text_color": "#ebebeb"},
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
        "queue_header_label":  {"text_color": "#333333"},
        "queue_list_frame":    {"fg_color": "#f5f5f5"},
        "queue_item_label":    {"text_color": "#333333"},
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

# Text color for dynamic queue rows; updated when the theme changes.
queue_item_text_color = THEMES["light"]["queue_item_label"]["text_color"]

# Download queue — items waiting to start.
download_queue = deque()
current_queue_item = None  # {"id": int, "url": str} or None when idle
_queue_id_counter = itertools.count(1)

# Folder where completed downloads are saved.
# Can be changed by the user and is saved to config.json.
DEFAULT_SAVE_LOCATION = os.path.join(os.path.expanduser("~"), "Downloads")
save_location = load_setting("save_location", DEFAULT_SAVE_LOCATION)
if not os.path.isdir(save_location):
    # Fall back if the folder was moved or deleted.
    save_location = DEFAULT_SAVE_LOCATION

# Save the resolved location to config.json.
save_setting("save_location", save_location)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def set_widgets_state(state: str):
    for w in [uninstall_button]:
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
    """Called from the background download thread — must not touch Tkinter
    widgets directly, so the actual UI update is marshaled onto the main
    thread via root.after()."""
    root.after(0, lambda: _update_progress_ui(percent, downloaded_mb, total_mb, eta))


def _update_progress_ui(percent: float, downloaded_mb: float, total_mb: float, eta: str):
    progress_bar.set(percent / 100)
    progress_label.configure(
        text=(
            f"{percent:.1f}%   |   {downloaded_mb:.2f} / {total_mb:.2f} MB   |   {eta}\n"
            f"{current_language['operation_in_progress_message']}"
        )
    )


def on_merge_progress(percent: float, elapsed_seconds: float, total_seconds: float, eta: str):
    """Separate from on_progress: merge progress is based on
    media time processed by ffmpeg, not MB. So it uses a separate label format instead of "X / Y MB".

    If total_seconds is unknown, percent stays at 0 and
    the progress bar won't reach 100% until ffmpeg finishes.

    Called from the background thread and uses root.after().
    """
    root.after(0, lambda: _update_merge_progress_ui(percent, eta))


def _update_merge_progress_ui(percent: float, eta: str):
    progress_bar.set(percent / 100)
    progress_label.configure(
        text=(
            f"{percent:.1f}%   |   {eta}\n"
            f"{current_language['merging_message']}"
        )
    )


def on_cancel_check() -> bool:
    return cancel_requested


def on_download_done(success_msg_key: str):
    root.after(0, lambda: _finalize_download(success_msg_key))


def _finalize_download(success_msg_key: str):
    global current_queue_item

    if system_notification_enabled.get():
        notification.notify(
            title=current_language["operation_completed_message"],
            message=current_language[success_msg_key],
            timeout=3,
            app_icon=NOTIFICATION_ICON,
        )

    current_queue_item = None
    if download_queue:
        process_next_in_queue()
    else:
        hide_progress()
        set_widgets_state("normal")
        download_button.configure(state="normal")
        queue_add_button.pack_forget()
        cancel_button.pack_forget()


def on_download_error(msg: str):
    root.after(0, lambda: _handle_error(msg))


def _handle_error(msg: str):
    global current_queue_item

    messagebox.showerror(current_language["error_title"], msg)

    current_queue_item = None
    if download_queue:
        process_next_in_queue()
    else:
        hide_progress()
        set_widgets_state("normal")
        download_button.configure(state="normal")
        queue_add_button.pack_forget()
        cancel_button.pack_forget()


# ---------------------------------------------------------------------------
# Quality selection helpers
# ---------------------------------------------------------------------------
# The dropdown shows language-specific labels, but each queue item stores
# its selection as a language-independent key, so it stays valid if the language changes.
RESOLUTION_UI_MAP = {
    "720p":       "720p",
    "1080p ᴴᴰ":  "1080p",
    "1440p ²ᴷ":  "2K",
    "2160p ⁴ᴷ":  "4K",
}
QUALITY_KEY_TO_LANG_FIELD = {
    "720p": "720p",
    "1080p": "1080p",
    "2K": "1440p",
    "4K": "2160p",
    "audio": "audio",
}


def resolve_quality_key(selection: str):
    """Turn the dropdown's current display text into a stable quality key,
    or None if it doesn't match anything (shouldn't normally happen)."""
    if selection == current_language.get("audio"):
        return "audio"
    return RESOLUTION_UI_MAP.get(selection)


def quality_label(quality_key: str) -> str:
    """Turn a stored quality key back into a label in the current language,
    for display in the queue list."""
    lang_field = QUALITY_KEY_TO_LANG_FIELD.get(quality_key)
    return current_language.get(lang_field, quality_key) if lang_field else quality_key


# ---------------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------------
def render_queue_list():
    """Redraw the waiting-items list. The currently-downloading item is not
    shown here — it's already been popped off download_queue and is instead
    reflected in the progress label above."""
    for child in queue_list_frame.winfo_children():
        child.destroy()

    if not download_queue:
        queue_list_frame.grid_remove()
        queue_header_label.grid_remove()
        clear_queue_button.grid_remove()
        return

    queue_header_label.configure(
        text=f"{current_language['queue_title_label']} ({len(download_queue)})"
    )
    queue_header_label.grid()
    clear_queue_button.grid()
    queue_list_frame.grid()

    for idx, item in enumerate(download_queue, start=1):
        row = ctk.CTkFrame(queue_list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2, padx=2)

        display_url = item["url"] if len(item["url"]) <= 60 else item["url"][:57] + "..."
        label = ctk.CTkLabel(
            row,
            text=f"{idx}. [{quality_label(item['quality_key'])}] {display_url}",
            anchor="w", font=("Helvetica", 12),
            text_color=queue_item_text_color,
        )
        label.pack(side="left", fill="x", expand=True, padx=(5, 5))

        remove_btn = ctk.CTkButton(
            row, text="✕", width=24, height=24,
            fg_color="transparent", hover_color="#dddddd", text_color="#d9534f",
            command=lambda item_id=item["id"]: remove_from_queue(item_id),
        )
        remove_btn.pack(side="right", padx=5)


def remove_from_queue(item_id: int):
    global download_queue
    download_queue = deque(item for item in download_queue if item["id"] != item_id)
    render_queue_list()


def clear_queue():
    global download_queue
    download_queue = deque()
    render_queue_list()


def add_to_queue():
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

    quality_key = resolve_quality_key(option_var.get())
    if not quality_key:
        messagebox.showwarning(
            current_language["warning_title"],
            current_language["quality_error_message"],
        )
        return

    url = clean_playlist_url(raw_url)
    download_queue.append({"id": next(_queue_id_counter), "url": url, "quality_key": quality_key})
    url_entry.delete(0, "end")
    render_queue_list()

    if current_queue_item is None:
        process_next_in_queue()


def process_next_in_queue():
    """Pop the next item off the queue and start downloading it. Assumes
    current_queue_item is currently None (nothing else is in flight)."""
    global current_queue_item, cancel_requested

    if not download_queue:
        current_queue_item = None
        return

    current_queue_item = download_queue.popleft()
    render_queue_list()
    cancel_requested = False

    url = current_queue_item["url"]
    quality_key = current_queue_item["quality_key"]
    # Uses the current global save_location;
    # saves to the location selected when the download starts.

    set_widgets_state("disabled")
    download_button.configure(state="disabled")
    queue_add_button.pack(side="left", padx=5)
    cancel_button.pack(pady=5)

    remaining = len(download_queue)
    starting_text = current_language["download_starting_message"]
    if remaining:
        starting_text += f"  ({current_language['queue_remaining_label']}: {remaining})"
    show_progress(starting_text)

    if quality_key == "audio":
        download_audio(
            url=url,
            save_location=save_location,
            on_progress=on_progress,
            on_cancel_check=on_cancel_check,
            on_done=lambda: on_download_done("audio_download_complete_message"),
            on_error=on_download_error,
            lang=current_language,
        )
    else:
        download_video(
            url=url,
            save_location=save_location,
            target_resolution=quality_key,
            on_progress=on_progress,
            on_cancel_check=on_cancel_check,
            on_done=lambda: on_download_done("download_complete_message"),
            on_error=on_download_error,
            lang=current_language,
            on_merge_progress=on_merge_progress,
        )


def cancel_download():
    """Cancels only the item currently downloading. If more items are
    queued, the next one starts automatically once this one stops."""
    global cancel_requested
    cancel_requested = True
    progress_label.configure(text=current_language["download_canceling_message"])


# ---------------------------------------------------------------------------
# Theme toggle
# ---------------------------------------------------------------------------
def toggle_theme():
    global dark_mode, queue_item_text_color
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
        "queue_header_label":  queue_header_label,
        "queue_list_frame":    queue_list_frame,
    }

    for key, widget in widget_map.items():
        widget.configure(**theme[key])

    queue_item_text_color = theme["queue_item_label"]["text_color"]
    render_queue_list()  # repaints any already-visible queue rows with the new color

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
        clear_queue_button:           "clear_queue_button",
        queue_add_button:             "add_to_queue_button",
        save_location_button:         "choose_folder_button",
    }
    for widget, key in label_map.items():
        widget.configure(text=current_language[key])

    render_queue_list()  # refreshes the "Queue (N)" header text in the new language

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
def show_entry_context_menu(event, entry: ctk.CTkEntry):
    """
    Right-click Cut/Copy/Paste/Select All menu for CTkEntry.
    """
    real_entry = entry._entry
    menu = Menu(
        entry,
        tearoff=0,
        font=("Helvetica", 13),
        activeborderwidth=6,
    )
    menu.add_command(
        label=f"✂   {current_language['cut_label']}",
        command=lambda: real_entry.event_generate("<<Cut>>"),
    )
    menu.add_command(
        label=f"⧉   {current_language['copy_label']}",
        command=lambda: real_entry.event_generate("<<Copy>>"),
    )
    menu.add_command(
        label=f"📋   {current_language['paste_label']}",
        command=lambda: real_entry.event_generate("<<Paste>>"),
    )
    menu.add_separator()
    menu.add_command(
        label=f"▤   {current_language['select_all_label']}",
        command=lambda: entry.select_range(0, "end"),
    )
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def open_downloads_folder():
    if os.name == "nt":
        os.startfile(save_location)
    else:
        webbrowser.open(save_location)


def _format_save_location_display(path: str) -> str:
    """Shorten a path for display in the sidebar's limited width."""
    max_len = 28
    if len(path) <= max_len:
        return path
    return "…" + path[-(max_len - 1):]


def update_save_location_label():
    save_location_value_label.configure(text=_format_save_location_display(save_location))


def choose_save_location():
    global save_location
    folder = filedialog.askdirectory(
        initialdir=save_location if os.path.isdir(save_location) else DEFAULT_SAVE_LOCATION,
        title=current_language.get("choose_folder_button", "Choose Folder"),
    )
    if folder:
        save_location = folder
        save_setting("save_location", folder)
        update_save_location_label()


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
root.geometry("800x600")
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
url_entry.bind("<Button-3>", lambda e: show_entry_context_menu(e, url_entry))

# Playlist checkbox (hidden until list= detected)
frame.grid_rowconfigure(1, minsize=50)
playlist_checkbox_var = ctk.BooleanVar()
playlist_checkbox = ctk.CTkCheckBox(
    frame,
    #variable=playlist_checkbox_var,
    font=ctk.CTkFont(size=15),
    checkbox_height=20,
    checkbox_width=20,
    border_width=2,
    fg_color="#333333",
    hover_color="#cccccc",
    corner_radius=4,
)
#playlist_checkbox.grid(row=1, column=3, sticky="w", padx=10, pady=5)
#playlist_checkbox.grid_remove()

# Queue header + clear button (row 2, hidden until something is queued)
queue_header_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=13, weight="bold"))
queue_header_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="w")
queue_header_label.grid_remove()

clear_queue_button = ctk.CTkButton(
    frame,
    command=clear_queue,
    width=100, height=24,
    font=("Helvetica", 11),
    fg_color="#ebebeb", hover_color="#dddddd", text_color="#d9534f",
)
clear_queue_button.grid(row=2, column=2, columnspan=2, padx=10, pady=(10, 0), sticky="e")
clear_queue_button.grid_remove()

# Queue list (waiting items only — the active download shows in the progress area)
queue_list_frame = ctk.CTkScrollableFrame(frame, width=440, height=90, fg_color="#f5f5f5")
queue_list_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=(5, 10), sticky="ew")
queue_list_frame.grid_remove()

# Bottom action panel: fixed to the bottom with place().
# Its contents use pack() among themselves.
bottom_panel = ctk.CTkFrame(root, fg_color="transparent")
bottom_panel.place(relx=0.5, rely=1.0, anchor="s", y=-15)

# yt-dlp status message — shown on first run or during update checks.
# Hidden otherwise. See on_ytdlp_status().
ytdlp_status_label = ctk.CTkLabel(
    bottom_panel, text="", font=("Helvetica", 14, "italic"), text_color="#888888",
)
ytdlp_status_label.pack(pady=(0, 5))
ytdlp_status_label.pack_forget()

# Action buttons: "İndir" is always visible,
# "➕ Sıraya Ekle" is shown only while downloading.
action_buttons_frame = ctk.CTkFrame(bottom_panel, fg_color="transparent")
action_buttons_frame.pack(pady=(0, 10))

download_button = ctk.CTkButton(
    action_buttons_frame,
    command=add_to_queue,
    width=120,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#458bc6",
    hover_color="#1f567a",
    text_color="#fbfbfb",
    corner_radius=5,
    state="disabled",  # re-enabled once on_ytdlp_status reports "ready"
)
download_button.pack(side="left", padx=5)

queue_add_button = ctk.CTkButton(
    action_buttons_frame,
    command=add_to_queue,
    width=150,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#5cb85c",
    hover_color="#449d44",
    text_color="#fbfbfb",
    corner_radius=5,
)
queue_add_button.pack(side="left", padx=5)
queue_add_button.pack_forget()

# Cancel button
cancel_button = ctk.CTkButton(
    bottom_panel,
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
progress_bar = ctk.CTkProgressBar(bottom_panel, orientation="horizontal", width=300, height=15)
progress_bar.set(0)
progress_bar.pack(pady=10)
progress_bar.pack_forget()

# Progress label
progress_label = ctk.CTkLabel(bottom_panel, text="", font=("Helvetica", 13))
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

# Save location picker
save_location_button = ctk.CTkButton(
    sidebar_content,
    command=choose_save_location,
    font=("Helvetica", 13),
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    height=30,
)
save_location_button.pack(anchor="w", pady=(10, 0), padx=10, fill="x")

save_location_value_label = ctk.CTkLabel(
    sidebar_content,
    text="",
    font=("Helvetica", 11),
    text_color="#333333",
)
save_location_value_label.pack(anchor="w", pady=(2, 10), padx=10, fill="x")
update_save_location_label()

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


def on_ytdlp_status(stage: str, percent):
    """Called (possibly from a background thread) as ensure_ytdlp progresses.
    Shows a status message while yt-dlp.exe is being prepared
    and locks the download button until it's ready."""
    def apply():
        lang = current_language or LANGUAGES.get("Tr", {})

        if stage == "ready":
            ytdlp_status_label.pack_forget()
            if current_queue_item is None:  # don't steal control from an active download
                download_button.configure(state="normal")
            return

        if stage == "checking_update":
            text = lang["ytdlp_checking_message"]
        elif stage == "downloading" and percent is not None:
            text = lang["ytdlp_downloading_message"].replace("{percent}", f"{percent:.0f}")
        else:
            text = lang["ytdlp_downloading_indeterminate_message"]

        ytdlp_status_label.configure(text=text)
        ytdlp_status_label.pack(pady=(0, 5), before=action_buttons_frame)

    root.after(0, apply)


fetch_ytdlp_version(
    lambda t: root.after(0, lambda: yt_dlp_version_label.configure(text=t)),
    on_status=on_ytdlp_status,
)

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