import logging
import os
import subprocess
import sys
import threading
import webbrowser

import customtkinter as ctk
from tkinter import Menu, filedialog, messagebox

from downloader import download_video, download_audio, cleanup_temp_files, TEMP_PREFIX
from quality_options import (
    DROPDOWN_QUALITY_ORDER,
    QUALITY_OPTION_BY_KEY,
    QUALITY_KEY_TO_FORMAT_TAG,
)
from error_classifier import classify_ytdlp_download_error, classify_ytdlp_update_error
from languages import LANGUAGES
from process_manager import acquire_single_instance, focus_existing_window
from settings import load_setting, save_setting
from ui.notifications import notify as send_notification
from ui.queue_view import QueueView
from ui.theme import ThemeManager
from updater import UpdateChecker, APP_VERSION
from utils import (
    clean_playlist_url,
    copy_icons,
    format_save_location_display,
    get_icon_path,
    load_button_icon,
    validate_video_url,
)


# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------
# The app shares config.json, the save folder, the startup temp-file sweep and
# the yt-dlp binary, so a second copy would interfere with the first. A named
# mutex marks the running copy; a second launch just brings the first window
# to the front and exits. "Local\\" scopes it to the current Windows session,
# matching the per-user config. The actual mutex/window-enumeration logic
# lives in process_manager.py — these two values are the only app-specific
# bits it needs.
_SINGLE_INSTANCE_MUTEX_NAME = "Local\\VideoDownloader_SingleInstance"
_WINDOW_TITLE_PREFIX = "Video Downloader v"

if not acquire_single_instance(_SINGLE_INSTANCE_MUTEX_NAME):
    focus_existing_window(_WINDOW_TITLE_PREFIX)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

logging.getLogger("PIL").setLevel(logging.WARNING)

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
# Window close (X)
# ---------------------------------------------------------------------------
def on_close_request():
    """Idle: close right away. Download/merge in progress: pause it and ask.
    On confirm, the download is stopped through the normal cancel path (stops
    yt-dlp/ffmpeg and lets the worker delete its temp files), then the app
    closes. Declining restores the previous pause state, so the download
    continues where it left off."""
    global closing, cancel_requested, pause_requested

    if closing:
        return

    if queue_view.current_item is not None:
        # Freeze the download while the dialog is open, using the same pause
        # mechanism as the Pause button (the button itself is left untouched).
        item_at_open = queue_view.current_item
        was_paused = pause_requested
        pause_requested = True
        if not messagebox.askyesno(
            current_language["close_confirm_title"],
            current_language["close_confirm_message"],
        ):
            # Only restore if it's still the same item; a new queue item
            # that started meanwhile has already reset its own pause state.
            if queue_view.current_item is item_at_open:
                pause_requested = was_paused
            return
        closing = True
        queue_view.clear()   # don't let the next queued item start
        pause_requested = False
        cancel_requested = True
        root.withdraw()          # window disappears immediately

    _finish_close(0)


def _finish_close(attempt: int):
    """Waits (max ~10 s) for the cancelled worker to finish, then closes.
    Anything still alive after that is killed by the job object."""
    if queue_view.current_item is not None and attempt < 100:
        root.after(100, lambda: _finish_close(attempt + 1))
        return
    if closing:
        # All processes are stopped by now; remove whatever temp files remain.
        cleanup_temp_files(save_location, TEMP_PREFIX)
    root.destroy()


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
# Theme definitions
# ---------------------------------------------------------------------------
# Moved to ui/theme.py — pure data, no widget references. See that module
# for the dict itself.


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
theme_manager = ThemeManager()
cancel_requested = False
pause_requested = False
closing = False  # True once the user confirmed closing during an active download
current_language: dict = {}
sidebar_open = False
SIDEBAR_WIDTH = 300
sidebar_x = -SIDEBAR_WIDTH

# Download queue — items waiting to start, plus the one currently in flight.
queue_view = QueueView()

# Folder where completed downloads are saved.
# Can be changed by the user and is saved to config.json.
DEFAULT_SAVE_LOCATION = os.path.join(os.path.expanduser("~"), "Downloads")
save_location = load_setting("save_location", DEFAULT_SAVE_LOCATION)
if not os.path.isdir(save_location):
    # Fall back if the folder was moved or deleted.
    save_location = DEFAULT_SAVE_LOCATION

# Save the resolved location to config.json.
save_setting("save_location", save_location)

# Temp files (.ytdlp_tmp_*) left behind if the app was closed or killed
# mid-download. Each download uses a fresh UUID, so these can never be
# resumed and are just garbage.
cleanup_temp_files(save_location, TEMP_PREFIX)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def set_widgets_state(state: str):
    for w in [uninstall_button, check_updates_button]:
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
    if pause_requested:
        # This update was queued (via root.after in on_progress) from a
        # yt-dlp line the background thread read just before it noticed
        # the pause request — the download has already been stopped by
        # the time we get here, so drop this stale update rather than
        # overwriting the "paused" label with it.
        return
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
    if pause_requested:
        # Same stale-update guard as _update_progress_ui.
        return
    progress_bar.set(percent / 100)
    progress_label.configure(
        text=(
            f"{percent:.1f}%   |   {eta}\n"
            f"{current_language['merging_message']}"
        )
    )


def on_cancel_check() -> bool:
    return cancel_requested


def on_pause_check() -> bool:
    return pause_requested


def on_download_done(success_msg_key: str):
    root.after(0, lambda: _finalize_download(success_msg_key))


def _finalize_download(success_msg_key: str):
    send_notification(
        system_notification_enabled.get(),
        current_language["operation_completed_message"],
        current_language[success_msg_key],
        NOTIFICATION_ICON,
    )

    queue_view.current_item = None
    if queue_view.items:
        process_next_in_queue()
    else:
        render_queue_list()  # clears the just-finished item from the queue list
        hide_progress()
        set_widgets_state("normal")
        pause_button.pack_forget()
        download_button.pack(side="left", padx=5)
        download_button.configure(state="normal")
        queue_add_button.pack_forget()
        cancel_button.pack_forget()


def on_download_error(msg: str):
    root.after(0, lambda: _handle_error(msg))


def _handle_error(msg: str):
    if not closing:  # closing cancels the download on purpose — no error popup
        messagebox.showerror(current_language["error_title"], msg)

    queue_view.current_item = None
    if queue_view.items:
        process_next_in_queue()
    else:
        render_queue_list()  # clears the just-errored item from the queue list
        hide_progress()
        set_widgets_state("normal")
        pause_button.pack_forget()
        download_button.pack(side="left", padx=5)
        download_button.configure(state="normal")
        queue_add_button.pack_forget()
        cancel_button.pack_forget()


# ---------------------------------------------------------------------------
# Quality selection helpers
# ---------------------------------------------------------------------------
# The dropdown shows language-specific labels, but each queue item stores
# its selection as a language-independent key, so it stays valid if the language changes.
# The quality list itself (order, resolution, format tag) lives in
# quality_options.py — add new options there, not here.

# Maps the exact composed dropdown text (label + format tag) back to its
# quality key. Rebuilt every time the dropdown is (re)populated in
# change_language(), since the label text changes with the language.
DROPDOWN_DISPLAY_TO_KEY = {}


def resolve_quality_key(selection: str):
    """Turn the dropdown's current display text into a stable quality key,
    or None if it doesn't match anything (shouldn't normally happen)."""
    return DROPDOWN_DISPLAY_TO_KEY.get(selection)


def quality_label(quality_key: str) -> str:
    """Turn a stored quality key back into a label in the current language,
    for display in the queue list.

    Most options have a fixed `label` (same text in every language); a few
    (like "audio") have a `lang_field` instead and are looked up from the
    current language dict — see quality_options.py.
    """
    opt = QUALITY_OPTION_BY_KEY.get(quality_key)
    if not opt:
        return quality_key
    if "label" in opt:
        return opt["label"]
    return current_language.get(opt.get("lang_field"), quality_key)


def quality_dropdown_text(quality_key: str) -> str:
    """Format tag (mp4/mp3) plus the label, as shown in the dropdown itself."""
    label = quality_label(quality_key)
    tag = QUALITY_KEY_TO_FORMAT_TAG.get(quality_key, "")
    return f"{tag}    {label}" if tag else label


# ---------------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------------
# The queue's own state and rendering live in QueueView (ui/queue_view.py);
# these are thin wrappers that supply the widgets/state QueueView needs and
# don't own itself (theme color, icon factory, language strings), plus the
# remove-then-redraw / preview-applied-then-redraw glue.

def render_queue_list():
    """Redraw the queue list. The currently-downloading item, if any, is
    shown first as an active row (marked with ▶, no remove button —
    cancel_button is used for that instead), followed by the waiting items."""
    queue_view.render(
        widgets={
            "list_frame": queue_list_frame,
            "header_label": queue_header_label,
            "clear_button": clear_queue_button,
        },
        text_color=theme_manager.queue_item_text_color,
        make_icon=_make_ctk_icon,
        quality_label=quality_label,
        current_language=current_language,
        on_remove=remove_from_queue,
    )


def fetch_queue_item_preview(item: dict):
    """Fetches preview info in the background and updates the queued item.
    Uses the item ID, so it can update while waiting in the queue."""
    queue_view.fetch_preview(item, after=root.after, on_done=_apply_preview_and_render)


def _apply_preview_and_render(item_id: int, info: dict, thumb_bytes):
    queue_view.apply_preview(item_id, info, thumb_bytes)
    render_queue_list()


def remove_from_queue(item_id: int):
    queue_view.remove(item_id)
    render_queue_list()


def clear_queue():
    queue_view.clear()
    render_queue_list()


def add_to_queue():
    raw_url = url_entry.get().strip()
    error_key = validate_video_url(raw_url)
    if error_key:
        messagebox.showwarning(
            current_language["warning_title"],
            current_language[error_key],
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
    queued_item = queue_view.enqueue(url, quality_key)
    url_entry.delete(0, "end")
    render_queue_list()
    fetch_queue_item_preview(queued_item)

    if queue_view.current_item is None:
        process_next_in_queue()


def process_next_in_queue():
    """Pop the next item off the queue and start downloading it. Assumes
    queue_view.current_item is currently None (nothing else is in flight)."""
    global cancel_requested, pause_requested

    if queue_view.pop_next() is None:
        return

    render_queue_list()
    cancel_requested = False
    pause_requested = False

    url = queue_view.current_item["url"]
    quality_key = queue_view.current_item["quality_key"]
    # Uses the current global save_location;
    # saves to the location selected when the download starts.

    set_widgets_state("disabled")
    download_button.pack_forget()
    # Reset to its default "paused? no" look in case the previous item in
    # the queue ended while paused.
    pause_button.configure(
        text=current_language["pause_button"],
        fg_color="#e0a12e",
        hover_color="#b87f1f",
    )
    pause_button.pack(side="left", padx=5)
    queue_add_button.pack(side="left", padx=5)
    cancel_button.pack(pady=5)

    remaining = len(queue_view.items)
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
            on_merge_progress=on_merge_progress,
            on_pause_check=on_pause_check,
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
            on_pause_check=on_pause_check,
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
        "clear_queue_button":  clear_queue_button,
    }
    theme_manager.toggle(widget_map, _make_ctk_icon)
    render_queue_list()  # repaints any already-visible queue rows with the new color


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
    current_language = LANGUAGES.get(selected, LANGUAGES["En"])

    label_map = {
        download_button:              "download_button",
        pause_button:                 "pause_button",
        cancel_button:                "cancel_button",
        download_option_label:        "download_option_label",
        system_notification_checkbox: "system_notification_checkbox",
        start_in_dark_mode_checkbox:  "start_in_dark_mode_checkbox",
        preview_notification_button:  "preview_notification_button",
        playlist_checkbox:            "playlist_checkbox",
        uninstall_button:             "uninstall_button",
        clear_queue_button:           "clear_queue_button",
        queue_add_button:             "queue_add_button",
        save_location_button:         "save_location_button",
        ytdlp_retry_button:           "ytdlp_retry_button",
        check_updates_button:         "check_updates_button",
    }
    for widget, key in label_map.items():
        widget.configure(text=current_language[key])

    # pause_button's label depends on the paused state, not just the
    # language, so it overrides the generic "pause_button" text set above.
    if pause_requested:
        pause_button.configure(text=current_language["resume_button"])

    render_queue_list()  # refreshes the "Queue (N)" header text in the new language

    dropdown_options = [quality_dropdown_text(key) for key in DROPDOWN_QUALITY_ORDER]
    DROPDOWN_DISPLAY_TO_KEY.clear()
    DROPDOWN_DISPLAY_TO_KEY.update(zip(dropdown_options, DROPDOWN_QUALITY_ORDER))
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


def update_save_location_label():
    save_location_value_label.configure(text=format_save_location_display(save_location))


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
    send_notification(
        system_notification_enabled.get(),
        current_language["preview_info_title"],
        current_language["system_notification_message"],
        PREVIEW_ICON,
    )


# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------
root = ctk.CTk()
root.title(f"Video Downloader v{APP_VERSION}")
root.geometry("800x600")
root.iconbitmap(APP_ICON)
root.protocol("WM_DELETE_WINDOW", on_close_request)

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
frame.grid_rowconfigure(1, minsize=20)
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
queue_header_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")
queue_header_label.grid_remove()

clear_queue_button = ctk.CTkButton(
    frame,
    command=clear_queue,
    width=100, height=24,
    font=("Helvetica", 13, "bold"),
    fg_color="#ebebeb", hover_color="#dddddd", text_color="#d9534f",
)
clear_queue_button.grid(row=2, column=2, columnspan=2, padx=10, pady=(1, 0), sticky="e")
clear_queue_button.grid_remove()

# Queue list (waiting items only — the active download shows in the progress area)
queue_list_frame = ctk.CTkScrollableFrame(frame, width=440, height=160, fg_color="#f5f5f5")
queue_list_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=(2, 10), sticky="ew")
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

# Shown only if the first-run yt-dlp.exe download fails (e.g. no internet).
# Lets the user retry without having to restart the whole app.
ytdlp_retry_button = ctk.CTkButton(
    bottom_panel,
    command=lambda: retry_ytdlp_setup(),
    width=140,
    height=32,
    font=("Helvetica", 13),
    fg_color="#565656",
    hover_color="#787878",
    text_color="#fbfbfb",
    corner_radius=5,
)
ytdlp_retry_button.pack(pady=(0, 5))
ytdlp_retry_button.pack_forget()

# Action buttons: "Download" is always visible,
# "➕ Add to Queue" is shown only while downloading.
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

# Shown in place of "download_button" while a download is active.
def pause_download():
    """Toggles the paused state of the item currently downloading.

    The background download thread polls on_pause_check() (see downloader.py's
    _apply_pause_state) and suspends/resumes the yt-dlp or ffmpeg process
    accordingly, so pausing genuinely stops network/CPU usage rather than
    just freezing the progress bar.
    """
    global pause_requested
    pause_requested = not pause_requested

    icon_file = RESUME_ICON_FILE if pause_requested else PAUSE_ICON_FILE
    icon = _make_ctk_icon(icon_file, "#fbfbfb")

    if pause_requested:
        pause_button.configure(
            text=current_language["resume_button"],
            fg_color="#e0a12e",
            hover_color="#b87f1f",
            **({"image": icon} if icon is not None else {}),
        )
        progress_label.configure(text=current_language["operation_paused_message"])
    else:
        pause_button.configure(
            text=current_language["pause_button"],
            fg_color="#e0a12e",
            hover_color="#b87f1f",
            **({"image": icon} if icon is not None else {}),
        )


pause_button = ctk.CTkButton(
    action_buttons_frame,
    command=pause_download,
    width=120,
    height=45,
    font=("Helvetica", 14, "bold"),
    fg_color="#e0a12e",
    hover_color="#b87f1f",
    text_color="#fbfbfb",
    corner_radius=5,
)
pause_button.pack(side="left", padx=5)
pause_button.pack_forget()

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
    text="",
    command=open_downloads_folder,
    width=50, height=50,
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
    text="",
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    width=45, height=45,
    command=toggle_theme,
)
light_dark.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)

# Language selector
language_options = ["De", "En", "Es", "Fr", "It", "Tr"]
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

# Check for Updates button
check_updates_button = ctk.CTkButton(
    sidebar_content,
    font=("Helvetica", 13),
    fg_color="#4c6a8c",
    hover_color="#3b556f",
    text_color="#fbfbfb",
    height=30,
)
check_updates_button.pack(anchor="w", pady=(0, 10), padx=10, fill="x")

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

# Now that every widget it needs exists, wire up the update checker and
# hook it to the button created above (its command couldn't be set at
# creation time since the checker needs uninstall_button too).
update_checker = UpdateChecker(
    root=root,
    get_language=lambda: current_language,
    is_download_active=lambda: queue_view.current_item is not None,
    check_updates_button=check_updates_button,
    uninstall_button=uninstall_button,
    download_button=download_button,
    ytdlp_status_label=ytdlp_status_label,
    action_buttons_frame=action_buttons_frame,
)
check_updates_button.configure(command=update_checker.check_for_updates)

# ---------------------------------------------------------------------------
# Button icons (PNG files in icons/, downloaded from an icon site such as
# Flaticon and dropped in next to appIcon.ico etc.). Each entry's color
# matches that button's own text_color above, so the icon reads the same
# as the label. A missing file just leaves that button text-only — see
# load_button_icon() — so icons can be added one at a time.
# ---------------------------------------------------------------------------
BUTTON_ICON_SIZE = (18, 18)
BUTTON_ICONS = {
    download_button:              ("download.png",     "#fbfbfb"),
    queue_add_button:             ("add.png",           "#fbfbfb"),
    cancel_button:                ("cancel.png",        "#d9534f"),
    save_location_button:         ("folder.png",        "#fbfbfb"),
    check_updates_button:         ("refresh.png",       "#fbfbfb"),
    ytdlp_retry_button:           ("refresh.png",       "#fbfbfb"),
    preview_notification_button:  ("notification.png",  "#fbfbfb"),
    clear_queue_button:           ("clear.png",          "#d9534f"),
    uninstall_button:             ("uninstall.png",     "#fbfbfb"),
    downloads_button:             ("folder.png",   "black", (30, 30)),
}
# pause_button toggles between two icons depending on state, so it's kept
# separate from the static dict above and wired up in pause_download().
PAUSE_ICON_FILE, RESUME_ICON_FILE = "pause.png", "resume.png"


def _make_ctk_icon(filename: str, color: str, size=BUTTON_ICON_SIZE):
    img = load_button_icon(filename, color=color, size=size)
    if img is None:
        return None
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)


def apply_button_icons():
    for widget, spec in BUTTON_ICONS.items():
        filename, color = spec[0], spec[1]
        size = spec[2] if len(spec) > 2 else BUTTON_ICON_SIZE
        icon = _make_ctk_icon(filename, color, size)
        if icon is not None:
            widget.configure(image=icon, compound="left")

    pause_icon_file = RESUME_ICON_FILE if pause_requested else PAUSE_ICON_FILE
    pause_icon = _make_ctk_icon(pause_icon_file, "#fbfbfb")
    if pause_icon is not None:
        pause_button.configure(image=pause_icon, compound="left")

    # light_dark starts in "light" mode (theme_manager.dark_mode=False at
    # module load, before load_setting/toggle_theme run below) — so it
    # shows the moon icon, matching THEMES["light"]["light_dark_icon"] set
    # by toggle_theme().
    theme_icon_file = "sun.png" if theme_manager.dark_mode else "moon.png"
    theme_icon = _make_ctk_icon(theme_icon_file, "#fbfbfb", (24, 24))
    if theme_icon is not None:
        light_dark.configure(image=theme_icon)


apply_button_icons()

# yt-dlp version label (populated asynchronously)
yt_dlp_version_label = ctk.CTkLabel(
    root,
    text="",
    font=ctk.CTkFont(size=10),
    text_color="#888888",
)
yt_dlp_version_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)


def on_ytdlp_status(stage: str, detail):
    """Called during ensure_ytdlp to update preparation status.
    Locks the download button and URL entry until yt-dlp.exe is ready, preventing
    failed preview fetches and a stuck "Loading..." state.

    detail is the download percentage (0-100) or the failure exception.
    """
    def apply():
        lang = current_language or LANGUAGES.get("En", {})

        if stage == "ready":
            ytdlp_status_label.pack_forget()
            ytdlp_retry_button.pack_forget()
            url_entry.configure(state="normal")
            if queue_view.current_item is None:  # don't steal control from an active download
                download_button.configure(state="normal")
            return

        if stage == "error":
            # Classifies yt-dlp.exe download errors as connection or other errors,
            # showing the raw error message for non-connection failures.
            message = classify_ytdlp_download_error(
                detail if isinstance(detail, Exception) else Exception("unknown"), lang
            )
            ytdlp_status_label.configure(text=message)
            ytdlp_status_label.pack(pady=(0, 5), before=action_buttons_frame)
            ytdlp_retry_button.configure(text=lang["ytdlp_retry_button"])
            ytdlp_retry_button.pack(pady=(0, 5), before=action_buttons_frame)
            download_button.configure(state="disabled")
            url_entry.configure(state="disabled")
            return

        if stage == "update_failed":
            # Self-update check failed on a later launch, but this is not fatal because
            # the existing yt-dlp.exe still works. Keep download/URL controls enabled,
            # show a brief classified warning, then hide it after a few seconds.
            message = classify_ytdlp_update_error(
                detail if isinstance(detail, Exception) else Exception("unknown"), lang
            )
            ytdlp_retry_button.pack_forget()
            ytdlp_status_label.configure(text=message)
            ytdlp_status_label.pack(pady=(0, 5), before=action_buttons_frame)
            url_entry.configure(state="normal")
            if queue_view.current_item is None:
                download_button.configure(state="normal")
            root.after(6000, ytdlp_status_label.pack_forget)
            return

        if stage == "checking_update":
            # exe already exists and works (this only runs on 2nd+ launch)
            # — no need to lock anything, just show the status text.
            text = lang["ytdlp_checking_message"]
            url_entry.configure(state="normal")
        elif stage == "downloading":
            # First run: exe doesn't exist yet. Lock the URL entry too, so a
            # pasted link can't kick off a preview fetch that's doomed to
            # fail silently and leave "Loading..." stuck on screen.
            text = (
                lang["ytdlp_downloading_message"].replace("{percent}", f"{detail:.0f}")
                if detail is not None
                else lang["ytdlp_downloading_indeterminate_message"]
            )
            url_entry.configure(state="disabled")
        else:
            text = lang["ytdlp_downloading_indeterminate_message"]

        ytdlp_retry_button.pack_forget()
        ytdlp_status_label.configure(text=text)
        ytdlp_status_label.pack(pady=(0, 5), before=action_buttons_frame)

    root.after(0, apply)


def retry_ytdlp_setup():
    """Called from the retry button after a failed first-run yt-dlp.exe
    download. Simply re-runs the same setup fetch_ytdlp_version already does
    at startup — ensure_ytdlp will attempt the download again since it was
    never marked as successfully checked/cached."""
    ytdlp_retry_button.pack_forget()
    fetch_ytdlp_version(
        lambda t: root.after(0, lambda: yt_dlp_version_label.configure(text=t)),
        on_status=on_ytdlp_status,
    )


fetch_ytdlp_version(
    lambda t: root.after(0, lambda: yt_dlp_version_label.configure(text=t)),
    on_status=on_ytdlp_status,
)

# ---------------------------------------------------------------------------
# Apply saved settings on startup
# ---------------------------------------------------------------------------
if dark_mode_enabled.get():
    toggle_theme()

saved_lang = load_setting("language", "En")
language_var.set(saved_lang)
change_language(saved_lang)
option_var.set(quality_dropdown_text("1080p"))  # keep the default selection in sync with the tagged dropdown text

# ---------------------------------------------------------------------------
root.mainloop()