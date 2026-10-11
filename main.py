"""
Application entry point.

App owns the main window and everything that is not download- or
update-specific: building the window and theme/language switching.
(Save-location handling lives in DownloadController, the sidebar slide
animation in SidebarController.)

It constructs DownloadController (core/download_controller.py) before the
window, because the window's button callbacks are its bound methods; its
widgets are attached afterwards via bind_widgets(). CookiePanel
(ui/sidebar/cookie_panel.py), YtdlpStatusPanel (ui/ytdlp_status.py),
SidebarController (ui/sidebar/controller.py) and AppLifecycle
(core/app_lifecycle.py, closing and uninstalling) follow the same pattern. UpdateChecker is constructed after the window, once the
widgets it needs exist.

Which widgets get a translated label, a button icon or theme colors is
declared where each widget is created, in build_app_window() (via
ui/registry.py); toggle_theme(), change_language() and apply_button_icons()
just loop over self.ui.registry.
"""

import logging
import os
import sys
from types import SimpleNamespace

import customtkinter as ctk
from tkinter import Menu

from core.app_lifecycle import AppLifecycle
from core.app_state import AppState
from core.download_controller import DownloadController
from core.quality_options import build_dropdown_options, quality_dropdown_text, resolve_quality_key
from downloading.downloader import TEMP_PREFIX
from languages import LANGUAGES
from system.process_manager import acquire_single_instance, focus_existing_window
from system.updater import UpdateChecker, APP_VERSION
from settings import load_setting, save_setting
from ui.app_window import WINDOW_TITLE_PREFIX, build_app_window
from ui.notifications import notify as send_notification
from ui.sidebar.controller import SidebarController
from ui.sidebar.cookie_panel import CookiePanel
from ui.theme import ThemeManager
from ui.ytdlp_status import YtdlpStatusPanel
from utils import (
    cleanup_temp_files,
    copy_icons,
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
SIDEBAR_WIDTH = 270

# Default download folder, saved to config.json.
DEFAULT_SAVE_LOCATION = os.path.join(os.path.expanduser("~"), "Downloads")

# Default button icon size (PNG).
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
            default_save_location=DEFAULT_SAVE_LOCATION,
        )

        # -- Cookie panel ------------------------------------------------
        # Created here for the same reason: the sidebar's cookie buttons use
        # its methods as callbacks. Widgets are attached via bind_widgets()
        # after build_app_window() returns.
        self.cookie_panel = CookiePanel(app_state=self.app_state)

        # -- yt-dlp status panel -----------------------------------------
        # Same pattern: the retry button uses its `retry` as callback; widgets
        # are attached via bind_widgets() after build_app_window() returns.
        # Its `ready` flag gates the Download button (see refresh_download_button).
        # update_checker doesn't exist yet, hence the lambda.
        self.ytdlp_status = YtdlpStatusPanel(
            app_state=self.app_state,
            refresh_download_button=self.refresh_download_button,
            is_app_update_downloading=lambda: self.update_checker.is_downloading,
        )

        # -- App lifecycle (close / uninstall) ---------------------------
        # Same pattern: the window's close handler and the uninstall button
        # use its methods; root is attached via bind_widgets() below.
        # update_checker doesn't exist yet, hence the lambda.
        self.lifecycle = AppLifecycle(
            app_state=self.app_state,
            queue_view=self.download_controller.queue_view,
            get_update_checker=lambda: self.update_checker,
        )

        # -- Sidebar (open / close animation) ----------------------------
        # Same pattern: the hamburger and close buttons use its `toggle` as
        # callback; widgets are attached via bind_widgets() below.
        self.sidebar = SidebarController(
            app_state=self.app_state,
            sidebar_width=SIDEBAR_WIDTH,
        )

        # -- Build UI ------------------------------------------------------
        # Every widget build_app_window() creates lives on self.ui
        # (self.ui.download_button, self.ui.root, ...).
        self.ui = build_app_window(
            callbacks=SimpleNamespace(
                on_close_request=self.lifecycle.on_close_request,
                url_changed=self.url_changed,
                show_entry_context_menu=self.show_entry_context_menu,
                clear_queue=self.download_controller.clear_queue,
                retry_ytdlp_setup=self.ytdlp_status.retry,
                add_to_queue=self.download_controller.add_to_queue,
                pause_download=self.download_controller.pause_download,
                cancel_download=self.download_controller.cancel_download,
                open_downloads_folder=self.download_controller.open_downloads_folder,
                toggle_sidebar=self.sidebar.toggle,
                toggle_theme=self.toggle_theme,
                change_language=self.change_language,
                choose_save_location=self.download_controller.choose_save_location,
                preview_notification=self.preview_notification,
                uninstall_app=self.lifecycle.uninstall_app,
                change_cookie_mode=self.cookie_panel.change_mode,
                change_cookie_browser=self.cookie_panel.change_browser,
                choose_cookie_file=self.cookie_panel.choose_file,
                create_cookie_file=self.cookie_panel.create_file,
                delete_cookie_file=self.cookie_panel.delete_file,
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
            save_location_value_label=ui.save_location_value_label,
        )
        self.cookie_panel.bind_widgets(
            mode_var=ui.cookie_mode_var,
            mode_menu=ui.cookie_mode_menu,
            browser_menu=ui.cookie_browser_menu,
            file_button=ui.cookie_file_button,
            file_label=ui.cookie_file_label,
            create_title_label=ui.cookie_create_title_label,
            buttons_row=ui.cookie_buttons_row,
        )
        self.lifecycle.bind_widgets(root=ui.root)
        self.sidebar.bind_widgets(
            root=ui.root,
            sidebar_frame=ui.sidebar_frame,
            menu_button=ui.menu_button,
        )
        self.ytdlp_status.bind_widgets(
            root=ui.root,
            url_entry=ui.url_entry,
            status_label=ui.ytdlp_status_label,
            retry_button=ui.ytdlp_retry_button,
            action_buttons_frame=ui.action_buttons_frame,
        )

        # Needs save_location_value_label, attached via bind_widgets() above.
        self.download_controller.update_save_location_label()

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

        # First-run download / self-update of yt-dlp.exe (runs in the background).
        self.ytdlp_status.fetch()

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
            self.ytdlp_status.ready
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

    # -- Language ------------------------------------------------------------
    def change_language(self, selected: str) -> None:
        ui = self.ui

        # Convert the current selection to a language-independent key BEFORE the language changes.
        selected_key = resolve_quality_key(ui.option_var.get())

        # Same for the cookie mode.
        cookie_mode_key = self.cookie_panel.current_mode_key()

        self.app_state.current_language = LANGUAGES.get(selected, LANGUAGES["EN"])
        dropdown_options = build_dropdown_options(self.app_state.current_language)
        ui.quality_options_menu.configure(values=dropdown_options)
        if selected_key is not None:
            ui.option_var.set(
                quality_dropdown_text(selected_key, self.app_state.current_language)
            )
        save_setting("language", selected)

        self.cookie_panel.refresh_language(cookie_mode_key)

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

    def preview_notification(self) -> None:
        send_notification(
            self.system_notification_enabled.get(),
            self.app_state.current_language["preview_info_title"],
            self.app_state.current_language["system_notification_message"],
            self.preview_icon,
        )

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


if __name__ == "__main__":
    App().run()