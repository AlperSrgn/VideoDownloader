"""
Application entry point.

App owns the main window and everything that is not download- or
update-specific: building the window, sidebar animation, theme/language
switching, save-location settings, the yt-dlp status display and closing.

It constructs DownloadController (core/download_controller.py) before the
window, because the window's button callbacks are its bound methods; its
widgets are attached afterwards via bind_widgets(). UpdateChecker is
constructed after the window, once the widgets it needs exist.

Which widgets get a translated label, a button icon or theme colors is
declared where each widget is created, in build_app_window() (via
ui/registry.py); toggle_theme(), change_language() and apply_button_icons()
just loop over self.ui.registry.
"""

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from types import SimpleNamespace

import customtkinter as ctk
from tkinter import Menu, filedialog, messagebox

from core.app_state import AppState
from core.download_controller import DownloadController
from core.quality_options import build_dropdown_options, quality_dropdown_text, resolve_quality_key
from downloading.downloader import TEMP_PREFIX
from downloading.error_classifier import classify_ytdlp_download_error, classify_ytdlp_update_error
from languages import LANGUAGES
from system.process_manager import acquire_single_instance, focus_existing_window
from system.updater import UpdateChecker, APP_VERSION
from settings import load_setting, save_setting
from ui.app_window import WINDOW_TITLE_PREFIX, build_app_window
from ui.notifications import notify as send_notification
from ui.theme import ThemeManager
from utils import (
    cleanup_temp_files,
    copy_icons,
    format_save_location_display,
    get_icon_path,
    load_button_icon,
)


# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------
# The app shares config.json, the save folder, startup cleanup, and yt-dlp,
# so only one copy can run at a time. A mutex identifies the active copy;
# a second launch brings the first window to the front and exits. "Local\"
# limits it to the current Windows session. The mutex and window handling
# live in system/process_manager.py.
#
# Must run before anything else, including Tk, so a second launch exits
# without creating a window; hence module scope, not App.__init__.
_SINGLE_INSTANCE_MUTEX_NAME = "Local\\VideoDownloader_SingleInstance"

if not acquire_single_instance(_SINGLE_INSTANCE_MUTEX_NAME):
    focus_existing_window(WINDOW_TITLE_PREFIX)
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
# App-wide constants
# ---------------------------------------------------------------------------
SIDEBAR_WIDTH = 300

# Folder where completed downloads are saved by default.
# Can be changed by the user and is saved to config.json.
DEFAULT_SAVE_LOCATION = os.path.join(os.path.expanduser("~"), "Downloads")

# Button icons (PNG files in icons/) default to this size unless a call site
# overrides it.
BUTTON_ICON_SIZE = (18, 18)


class App:
    def __init__(self):
        # -- Icons -----------------------------------------------------------
        copy_icons()
        self.notification_icon = get_icon_path("notificationIcon.ico")
        self.preview_icon = get_icon_path("previewIcon.ico")
        self.app_icon = get_icon_path("appIcon.ico")

        # -- State -------------------------------------------------------
        self.theme_manager = ThemeManager()

        initial_save_location = load_setting("save_location", DEFAULT_SAVE_LOCATION)
        if not os.path.isdir(initial_save_location):
            # Fall back if the folder was moved or deleted.
            initial_save_location = DEFAULT_SAVE_LOCATION
        save_setting("save_location", initial_save_location)

        self.app_state = AppState(save_location=initial_save_location, sidebar_width=SIDEBAR_WIDTH)

        # True while yt-dlp.exe is available and not being replaced. False at startup,
        # during the initial download or `--update-to` update (checking_update), or
        # after a failed initial download. The Download button is derived from this
        # flag (see refresh_download_button), so it cannot be enabled before yt-dlp is ready.
        self.ytdlp_ready = False

        # Temp files (.ytdlp_tmp_*) left if the app closes during a download.
        # Each download uses a new UUID, so they cannot be resumed and can be deleted.
        cleanup_temp_files(self.app_state.save_location, TEMP_PREFIX)

        # -- Download controller -----------------------------------------
        # Created here so build_app_window() can use its methods as button callbacks.
        # Widget references (progress_bar, download_button, ...) are assigned via
        # download_controller.bind_widgets(...) after build_app_window() returns.
        self.download_controller = DownloadController(
            app_state=self.app_state,
            theme_manager=self.theme_manager,
            make_icon=self.make_icon,
            send_notification=send_notification,
            notification_icon=self.notification_icon,
            get_system_notification_enabled=lambda: self.system_notification_enabled.get(),
        )

        # -- Build UI ------------------------------------------------------
        # Every widget build_app_window() creates lives on self.ui
        # (self.ui.download_button, self.ui.root, ...).
        self.ui = build_app_window(
            callbacks=SimpleNamespace(
                on_close_request=self.on_close_request,
                url_changed=self.url_changed,
                show_entry_context_menu=self.show_entry_context_menu,
                clear_queue=self.download_controller.clear_queue,
                retry_ytdlp_setup=self.retry_ytdlp_setup,
                add_to_queue=self.download_controller.add_to_queue,
                pause_download=self.download_controller.pause_download,
                cancel_download=self.download_controller.cancel_download,
                open_downloads_folder=self.open_downloads_folder,
                toggle_sidebar=self.toggle_sidebar,
                toggle_theme=self.toggle_theme,
                change_language=self.change_language,
                choose_save_location=self.choose_save_location,
                preview_notification=self.preview_notification,
                uninstall_app=self.uninstall_app,
            ),
            app_version=APP_VERSION,
            app_icon=self.app_icon,
            sidebar_width=SIDEBAR_WIDTH,
            sidebar_x=self.app_state.sidebar_x,
        )

        # Now that the real widgets exist, hand them to the controller.
        ui = self.ui
        self.download_controller.bind_widgets(
            root=ui.root,
            progress_bar=ui.progress_bar,
            progress_label=ui.progress_label,
            download_button=ui.download_button,
            pause_button=ui.pause_button,
            queue_add_button=ui.queue_add_button,
            cancel_button=ui.cancel_button,
            queue_list_frame=ui.queue_list_frame,
            queue_header_label=ui.queue_header_label,
            clear_queue_button=ui.clear_queue_button,
            url_entry=ui.url_entry,
            option_var=ui.option_var,
            uninstall_button=ui.uninstall_button,
            check_updates_button=ui.check_updates_button,
            toast_label=ui.toast_label,
        )

        # Needs save_location_value_label, which build_app_window() creates.
        self.update_save_location_label()

        # Wired up here because the checker needs several widgets, and the
        # buttons' commands can only be set once the checker exists.
        self.update_checker = UpdateChecker(
            root=ui.root,
            get_language=lambda: self.app_state.current_language,
            refresh_download_button=self.refresh_download_button,
            check_updates_button=ui.check_updates_button,
            uninstall_button=ui.uninstall_button,
            ytdlp_status_label=ui.ytdlp_status_label,
            action_buttons_frame=ui.action_buttons_frame,
            update_buttons_frame=ui.update_buttons_frame,
            update_cancel_button=ui.update_cancel_button,
            update_install_button=ui.update_install_button,
        )
        ui.check_updates_button.configure(command=self.update_checker.check_for_updates)
        ui.update_cancel_button.configure(command=self.update_checker.cancel_download)
        ui.update_install_button.configure(command=self.update_checker.install_update)

        # -- Button icons --------------------------------------------------
        # Icons are declared next to their widgets in build_app_window()
        # (registry.add(..., icon=("file.png", color))) and applied by
        # apply_button_icons(). If a file is missing, the button stays
        # text-only. pause_button's icon switches with its state; see
        # DownloadController._set_pause_button_state().
        self.apply_button_icons()

        # yt-dlp version label (populated asynchronously)
        self.yt_dlp_version_label = ctk.CTkLabel(
            ui.root, text="", font=ctk.CTkFont(size=10), text_color="#888888",
        )
        self.yt_dlp_version_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)

        self.fetch_ytdlp_version(on_status=self.on_ytdlp_status)

        # -- Apply saved settings on startup ---------------------------------
        if ui.dark_mode_enabled.get():
            self.toggle_theme()

        saved_lang = load_setting("language", "EN")
        ui.language_var.set(saved_lang)
        self.change_language(saved_lang)
        # keep the default selection in sync with the tagged dropdown text
        ui.option_var.set(quality_dropdown_text("1080p", self.app_state.current_language))

    @property
    def system_notification_enabled(self):
        """The sidebar's "system_notification" checkbox variable (see
        build_app_window()), exposed as a shortcut."""
        return self.ui.system_notification_enabled

    def run(self) -> None:
        self.ui.root.mainloop()

    # -- Download button gate -----------------------------------------------
    def _download_allowed(self) -> bool:
        return (
            self.ytdlp_ready
            and self.download_controller.queue_view.current_item is None
            and not self.update_checker.is_locked
        )

    def refresh_download_button(self) -> None:
        """Single place that decides whether the Download button is usable:
        yt-dlp ready AND no active download AND no app update in progress.
        Call this after any of those three changes."""
        self.ui.download_button.configure(
            state="normal" if self._download_allowed() else "disabled"
        )

    # -- yt-dlp version (async) ------------------------------------------
    def fetch_ytdlp_version(self, on_status=None) -> None:
        """Runs ensure_ytdlp (first-run download / self-update) in the
        background and updates yt_dlp_version_label with the result.

        If provided, `on_status(stage, detail)` is called as ensure_ytdlp
        progresses (detail is the percentage while downloading, or the
        exception on failure — see ensure_ytdlp's docstring for the stages).
        This lets the UI show status while yt-dlp.exe is being downloaded
        or updated.
        """
        # Set synchronously on the main thread, before the worker starts, so
        # there is no window in which Download is enabled while ensure_ytdlp
        # may already be replacing the exe. Also covers the retry button.
        self.ytdlp_ready = False
        self.refresh_download_button()

        def worker():
            try:
                from settings import get_appdata_path
                from downloading.ytdlp_manager import ensure_ytdlp, get_ytdlp_version
                # ensure_ytdlp downloads on first run; on later launches, it checks for
                # updates at most once every 12 hours and once per session.
                exe_path = ensure_ytdlp(get_appdata_path(), on_status=on_status)
                version_text = f"yt-dlp v{get_ytdlp_version(exe_path)}"
            except Exception:
                version_text = "yt-dlp version unavailable"
            self.ui.root.after(0, lambda: self.yt_dlp_version_label.configure(text=version_text))

        threading.Thread(target=worker, daemon=True).start()

    # -- Window close (X) -------------------------------------------------
    def on_close_request(self) -> None:
        """Idle: close right away. Download/merge in progress: pause it and
        ask. On confirm, the download is stopped through the normal cancel
        path (stops yt-dlp/ffmpeg and lets the worker delete its temp
        files), then the app closes. Declining restores the previous pause
        state, so the download continues where it left off."""
        if self.app_state.closing:
            return

        queue_view = self.download_controller.queue_view
        if queue_view.current_item is not None:
            # Freeze the download while the dialog is open, using the same
            # pause mechanism as the Pause button (the button itself is
            # left untouched).
            item_at_open = queue_view.current_item
            was_paused = self.app_state.pause_requested
            self.app_state.pause_requested = True
            if not messagebox.askyesno(
                self.app_state.current_language["close_confirm_title"],
                self.app_state.current_language["close_confirm_message"],
            ):
                # Only restore if it's still the same item; a new queue item
                # that started meanwhile has already reset its own pause state.
                if queue_view.current_item is item_at_open:
                    self.app_state.pause_requested = was_paused
                return
            self.app_state.closing = True
            queue_view.clear()  # don't let the next queued item start
            self.app_state.pause_requested = False
            self.app_state.cancel_requested = True
            self.ui.root.withdraw()  # window disappears immediately

        # An app-update installer download in progress: cancel it so its
        # partial .part file gets deleted (_finish_close waits for that).
        if self.update_checker.is_downloading:
            self.update_checker.cancel_download()
            self.ui.root.withdraw()

        self._finish_close(0)

    def _finish_close(self, attempt: int) -> None:
        """Waits (max ~10 s) for the cancelled worker to finish, then closes.
        Anything still alive after that is killed by the job object."""
        busy = (
            self.download_controller.queue_view.current_item is not None
            or self.update_checker.is_downloading
        )
        if busy and attempt < 100:
            self.ui.root.after(100, lambda: self._finish_close(attempt + 1))
            return
        if self.app_state.closing:
            # Processes should be stopped by now (any that aren't are killed
            # by the job object as we exit); remove whatever temp files remain.
            cleanup_temp_files(self.app_state.save_location, TEMP_PREFIX)
        self.ui.root.destroy()

    # -- Uninstall ---------------------------------------------------------
    def uninstall_app(self) -> None:
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        uninstall_path = os.path.join(app_dir, "unins000.exe")

        if not messagebox.askyesno(
            self.app_state.current_language["uninstall_app_title"],
            self.app_state.current_language["uninstall_app_message"],
        ):
            return

        if os.path.exists(uninstall_path):
            subprocess.Popen([uninstall_path])
            sys.exit()
        else:
            messagebox.showerror(
                self.app_state.current_language["error_title"],
                self.app_state.current_language["file_not_found_error"],
            )

    # -- Theme toggle --------------------------------------------------------
    def toggle_theme(self) -> None:
        ui = self.ui
        # Every widget that follows the light/dark theme registers itself in
        # build_app_window() (registry.add(..., theme="<THEMES key>")).
        widget_map = ui.registry.themed
        self.theme_manager.toggle(widget_map, self.make_icon)
        # update_cancel_button isn't in THEMES; it just mirrors cancel_button's
        # freshly-themed colors (same look, shown only during an app update).
        ui.update_cancel_button.configure(
            fg_color=ui.cancel_button.cget("fg_color"),
            hover_color=ui.cancel_button.cget("hover_color"),
        )
        self.download_controller.render_queue_list()  # repaints any already-visible queue rows with the new color

    # -- Sidebar animation -----------------------------------------------
    def animate_sidebar(self, target_x: int, step: int) -> None:
        if self.app_state.sidebar_x != target_x:
            self.app_state.sidebar_x = (
                max(target_x, min(0, self.app_state.sidebar_x + step)) if step > 0
                else max(target_x, self.app_state.sidebar_x + step)
            )
            self.ui.sidebar_frame.place(x=self.app_state.sidebar_x, y=0)
            self.ui.root.after(5, lambda: self.animate_sidebar(target_x, step))
        else:
            self.ui.sidebar_frame.place(x=target_x, y=0)

    def toggle_sidebar(self) -> None:
        if self.app_state.sidebar_open:
            self.animate_sidebar(-SIDEBAR_WIDTH, -10)
            self.ui.menu_button.place(x=10, y=10)
        else:
            self.animate_sidebar(0, 10)
            self.ui.menu_button.place_forget()
        self.app_state.sidebar_open = not self.app_state.sidebar_open

    # -- Language ------------------------------------------------------------
    def change_language(self, selected: str) -> None:
        ui = self.ui

        # Convert the current selection to a language-independent key BEFORE the language changes.
        selected_key = resolve_quality_key(ui.option_var.get())

        self.app_state.current_language = LANGUAGES.get(selected, LANGUAGES["EN"])
        dropdown_options = build_dropdown_options(self.app_state.current_language)
        ui.quality_options_menu.configure(values=dropdown_options)
        if selected_key is not None:
            ui.option_var.set(
                quality_dropdown_text(selected_key, self.app_state.current_language)
            )
        save_setting("language", selected)

        # widget -> language key, registered in build_app_window()
        # (registry.add(..., text="<language key>")).
        label_map = ui.registry.texts
        for widget, key in label_map.items():
            widget.configure(text=self.app_state.current_language[key])

        # pause_button's label depends on the paused state, not just the
        # language, so it overrides the generic "pause_button" text set above.
        if self.app_state.pause_requested:
            ui.pause_button.configure(text=self.app_state.current_language["resume_button"])

        self.download_controller.render_queue_list()  # refreshes the "Queue (N)" header text in the new language

    # -- URL change handler ------------------------------------------------
    def url_changed(self, *_) -> None:
        # Playlist support is pending: once enabled, a "list=" URL should
        # show playlist_checkbox (see the commented-out grid() call in
        # build_app_window()). Until then the checkbox stays hidden.
        if "list=" in self.ui.url_var.get():
            pass  # playlist_checkbox.grid()  — playlist support pending
        else:
            self.ui.playlist_checkbox.grid_remove()

    # -- Misc UI callbacks ---------------------------------------------------
    def show_entry_context_menu(self, event, entry: ctk.CTkEntry) -> None:
        """
        Right-click Cut/Copy/Paste/Select All menu for CTkEntry.
        """
        real_entry = entry._entry
        lang = self.app_state.current_language
        menu = Menu(
            entry,
            tearoff=0,
            font=("Helvetica", 13),
            activeborderwidth=6,
        )
        menu.add_command(
            label=f"✂   {lang['cut_label']}",
            command=lambda: real_entry.event_generate("<<Cut>>"),
        )
        menu.add_command(
            label=f"⧉   {lang['copy_label']}",
            command=lambda: real_entry.event_generate("<<Copy>>"),
        )
        menu.add_command(
            label=f"📋   {lang['paste_label']}",
            command=lambda: real_entry.event_generate("<<Paste>>"),
        )
        menu.add_separator()
        menu.add_command(
            label=f"▤   {lang['select_all_label']}",
            command=lambda: entry.select_range(0, "end"),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def open_downloads_folder(self) -> None:
        if os.name == "nt":
            os.startfile(self.app_state.save_location)
        else:
            webbrowser.open(self.app_state.save_location)

    def update_save_location_label(self) -> None:
        self.ui.save_location_value_label.configure(
            text=format_save_location_display(self.app_state.save_location)
        )

    def choose_save_location(self) -> None:
        folder = filedialog.askdirectory(
            initialdir=self.app_state.save_location
            if os.path.isdir(self.app_state.save_location) else DEFAULT_SAVE_LOCATION,
            title=self.app_state.current_language.get("choose_folder_button", "Choose Folder"),
        )
        if folder:
            self.app_state.save_location = folder
            save_setting("save_location", folder)
            self.update_save_location_label()

    def preview_notification(self) -> None:
        send_notification(
            self.system_notification_enabled.get(),
            self.app_state.current_language["preview_info_title"],
            self.app_state.current_language["system_notification_message"],
            self.preview_icon,
        )

    def retry_ytdlp_setup(self) -> None:
        """Called from the retry button after a failed first-run yt-dlp.exe
        download. Re-runs the startup setup; ensure_ytdlp tries the
        download again since it was never marked as checked/cached."""
        self.ui.ytdlp_retry_button.pack_forget()
        self.fetch_ytdlp_version(on_status=self.on_ytdlp_status)

    # -- Button icons --------------------------------------------------------
    def make_icon(self, filename: str, color: str, size=BUTTON_ICON_SIZE):
        img = load_button_icon(filename, color=color, size=size)
        if img is None:
            return None
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)

    def apply_button_icons(self) -> None:
        for widget, spec in self.ui.registry.icons.items():
            filename, color = spec[0], spec[1]
            size = spec[2] if len(spec) > 2 else BUTTON_ICON_SIZE
            icon = self.make_icon(filename, color, size)
            if icon is not None:
                widget.configure(image=icon, compound="left")

        pause_icon_file = (
            DownloadController.RESUME_ICON_FILE if self.app_state.pause_requested
            else DownloadController.PAUSE_ICON_FILE
        )
        pause_icon = self.make_icon(pause_icon_file, "#fbfbfb")
        if pause_icon is not None:
            self.ui.pause_button.configure(image=pause_icon, compound="left")

        # light_dark starts in "light" mode (theme_manager.dark_mode=False
        # until load_setting/toggle_theme run in __init__) — so it shows the
        # moon icon, matching THEMES["light"]["light_dark_icon"] set by
        # toggle_theme().
        theme_icon_file = "sun.png" if self.theme_manager.dark_mode else "moon.png"
        theme_icon = self.make_icon(theme_icon_file, "#fbfbfb", (24, 24))
        if theme_icon is not None:
            self.ui.light_dark.configure(image=theme_icon)

    def on_ytdlp_status(self, stage: str, detail) -> None:
        """Called during ensure_ytdlp to update preparation status. Keeps
        self.ytdlp_ready in sync and derives the download button from it
        (see refresh_download_button); also locks the URL entry while
        yt-dlp.exe is being downloaded, preventing failed preview fetches
        and a stuck "Loading..." state.

        detail is the download percentage (0-100) or the failure exception.
        """
        def apply():
            ui = self.ui
            lang = self.app_state.current_language or LANGUAGES.get("EN", {})

            # While the app-update installer is downloading, ytdlp_status_label
            # is showing its "%" progress — don't hide/overwrite it.
            updating = self.update_checker.is_downloading

            if stage == "ready":
                if not updating:
                    ui.ytdlp_status_label.pack_forget()
                ui.ytdlp_retry_button.pack_forget()
                ui.url_entry.configure(state="normal")
                self.ytdlp_ready = True
                self.refresh_download_button()  # stays disabled if a download/app update is active
                return

            if stage == "error":
                # Classifies yt-dlp.exe download errors as connection or
                # other errors, showing the raw error message for
                # non-connection failures.
                message = classify_ytdlp_download_error(
                    detail if isinstance(detail, Exception) else Exception("unknown"), lang
                )
                ui.ytdlp_status_label.configure(text=message)
                ui.ytdlp_status_label.pack(pady=(0, 5), before=ui.action_buttons_frame)
                ui.ytdlp_retry_button.configure(text=lang["ytdlp_retry_button"])
                ui.ytdlp_retry_button.pack(pady=(0, 5), before=ui.action_buttons_frame)
                self.ytdlp_ready = False
                self.refresh_download_button()
                ui.url_entry.configure(state="disabled")
                return

            if stage == "update_failed":
                # Self-update check failed on a later launch, but this is
                # not fatal because the existing yt-dlp.exe still works.
                # Keep download/URL controls enabled, show a brief
                # classified warning, then hide it after a few seconds.
                message = classify_ytdlp_update_error(
                    detail if isinstance(detail, Exception) else Exception("unknown"), lang
                )
                ui.ytdlp_retry_button.pack_forget()
                if not updating:
                    ui.ytdlp_status_label.configure(text=message)
                    ui.ytdlp_status_label.pack(pady=(0, 5), before=ui.action_buttons_frame)
                ui.url_entry.configure(state="normal")
                self.ytdlp_ready = True
                self.refresh_download_button()
                if not updating:
                    ui.root.after(6000, ui.ytdlp_status_label.pack_forget)
                return

            # Every stage below is transitional (checking_update, downloading,
            # unknown): `--update-to` replaces yt-dlp.exe in place, so a
            # download must not be able to start (or spawn its own
            # ensure_ytdlp) until "ready" / "update_failed" arrives.
            self.ytdlp_ready = False
            self.refresh_download_button()

            if stage == "checking_update":
                # exe already exists and works (this stage only occurs when
                # an exe was already there), so the URL entry can stay
                # usable — only Download is held back until the update
                # check finishes.
                text = lang["ytdlp_checking_message"]
                ui.url_entry.configure(state="normal")
            elif stage == "downloading":
                # First run: exe doesn't exist yet. Lock the URL entry too,
                # so a pasted link can't kick off a preview fetch that's
                # doomed to fail silently and leave "Loading..." stuck on
                # screen.
                text = (
                    lang["ytdlp_downloading_message"].replace("{percent}", f"{detail:.0f}")
                    if detail is not None
                    else lang["ytdlp_downloading_indeterminate_message"]
                )
                ui.url_entry.configure(state="disabled")
            else:
                text = lang["ytdlp_downloading_indeterminate_message"]

            ui.ytdlp_retry_button.pack_forget()
            ui.ytdlp_status_label.configure(text=text)
            ui.ytdlp_status_label.pack(pady=(0, 5), before=ui.action_buttons_frame)

        self.ui.root.after(0, apply)


if __name__ == "__main__":
    App().run()