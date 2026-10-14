"""
Cookie support in the sidebar (age-restricted / members-only videos): which
cookie widgets are visible for the selected mode, and the handlers behind
their buttons (file picker, Firefox export, delete, open folder).

The widgets themselves are built by ui/sidebar/view.py; the cookie logic (modes,
files, export) lives in the cookie package. This class is only the glue
between them: widget visibility, language refresh and the dialogs.

Same pattern as DownloadController: App creates the panel before the window,
because the sidebar's button callbacks are its bound methods, and attaches the
widgets afterwards via bind_widgets().

Must be used from the main (Tk) thread only.
"""

import logging
import os
import subprocess
import webbrowser
from tkinter import filedialog, messagebox

from cookie import (
    COOKIE_MODES,
    CookieExportError,
    build_cookie_mode_options,
    cookie_file_exists,
    cookie_mode_label,
    export_cookies_from_firefox,
    get_cookie_file_label,
    get_cookie_mode,
    import_cookie_file,
    remove_cookie_file,
    resolve_cookie_browser_key,
    resolve_cookie_mode_key,
    set_cookie_browser,
    set_cookie_mode,
)
from utils import format_save_location_display

logger = logging.getLogger(__name__)


class CookiePanel:
    def __init__(self, app_state):
        self.app_state = app_state
        # Assigned by bind_widgets() once the sidebar exists.
        self.mode_var = None
        self.mode_menu = None
        self.browser_menu = None
        self.file_button = None
        self.file_label = None
        self.create_title_label = None
        self.buttons_row = None
        self.create_button = None
        self.delete_button = None
        self.file_delete_button = None

    def bind_widgets(self, *, mode_var, mode_menu, browser_menu, file_button,
                     file_label, create_title_label, buttons_row,
                     create_button=None, delete_button=None,
                     file_delete_button=None) -> None:
        """Attaches the sidebar's cookie widgets (see ui/sidebar/view.py).

        Only the mode menu is always visible; browser_menu (shown to the right
        of the mode menu), file_label, create_title_label and buttons_row
        (shown below it) start unpacked and are shown/hidden by
        update_widgets().

        file_button, create_button and delete_button are the buttons inside
        buttons_row (a grid): "From file" mode shows file_button + Delete,
        "Create from Firefox" mode shows Create + Delete."""
        self.mode_var = mode_var
        self.mode_menu = mode_menu
        self.browser_menu = browser_menu
        self.file_button = file_button
        self.file_label = file_label
        self.create_title_label = create_title_label
        self.buttons_row = buttons_row
        self.create_button = create_button
        self.delete_button = delete_button
        # "From file" mode: Delete sits in the mode menu's row (like the browser
        # menu). If it isn't passed, the old layout (Delete next to the file
        # button) is used.
        self.file_delete_button = file_delete_button

    # -- Language ------------------------------------------------------------
    def current_mode_key(self) -> str:
        """The selected cookie mode as a language-independent key. Called by
        App.change_language() BEFORE the language changes, so the dropdown
        text can still be resolved; at startup the dropdown is still empty,
        so it falls back to the saved setting."""
        cookie_mode_key = (
            resolve_cookie_mode_key(self.mode_var.get(), self.app_state.current_language)
            or get_cookie_mode()
        )
        if cookie_mode_key not in COOKIE_MODES:
            cookie_mode_key = "none"
        return cookie_mode_key

    def refresh_language(self, cookie_mode_key: str) -> None:
        """Re-translates the mode menu (call AFTER app_state.current_language
        changed) and keeps `cookie_mode_key` selected."""
        self.mode_menu.configure(
            values=build_cookie_mode_options(self.app_state.current_language)
        )
        self.mode_var.set(
            cookie_mode_label(cookie_mode_key, self.app_state.current_language)
        )
        self.update_widgets()

    # -- Widgets and handlers --------------------------------------------------
    def update_widgets(self) -> None:
        """Shows the widgets that belong to the selected mode:

            browser         browser menu (in the mode menu's row)
            file            "cookies.txt" + Delete side by side, file name
            firefox_export  heading, Create + Delete side by side, file name
        """
        mode = resolve_cookie_mode_key(
            self.mode_var.get(), self.app_state.current_language
        )

        self.browser_menu.pack_forget()
        self.file_label.pack_forget()
        self.create_title_label.pack_forget()
        self.buttons_row.pack_forget()
        if self.file_delete_button is not None:
            self.file_delete_button.pack_forget()
        # file_button, create_button and delete_button are gridded inside
        # buttons_row by _layout_buttons().

        if mode == "browser":
            # Same row as the mode menu (see ui/sidebar/view.py), right next to it.
            # No fill/expand on purpose: the width is COOKIE_BROWSER_MENU_WIDTH
            # (ui/sidebar/widgets.py), not whatever space the mode menu leaves free.
            self.browser_menu.pack(side="left", padx=(6, 0))
        elif mode == "file":
            if self.file_delete_button is not None:
                # Same row as the mode menu, right next to it.
                self.file_delete_button.pack(side="left", padx=(6, 0))
            self._layout_buttons(mode)
            self.buttons_row.pack(anchor="w", pady=(8, 0), padx=10, fill="x")
            self.file_label.pack(anchor="w", pady=(2, 0), padx=10, fill="x")
            self._refresh_file_label()
        elif mode == "firefox_export":
            self.create_title_label.pack(anchor="w", pady=(8, 0), padx=10, fill="x")
            self._layout_buttons(mode)
            self.buttons_row.pack(anchor="w", pady=(4, 0), padx=10, fill="x")
            self.file_label.pack(anchor="w", pady=(4, 0), padx=10, fill="x")
            self._refresh_file_label()
        else:
            self._layout_buttons(mode)  # hides all three

    def _refresh_file_label(self) -> None:
        self.file_label.configure(
            text=format_save_location_display(get_cookie_file_label())
        )

    def _layout_buttons(self, mode) -> None:
        """Lays out the button row (buttons_row, a grid with two columns):

            file            [ Choose cookies.txt ]      full width; Delete is in
                            the mode menu's row (file_delete_button). Without
                            file_delete_button: [ cookies.txt ][ Delete ]
            firefox_export  [ Create ][ Delete ]        two equal halves

        The Create and Delete buttons are optional in bind_widgets(); a
        missing one is simply not shown."""
        row = self.buttons_row
        for button in (self.file_button, self.create_button, self.delete_button):
            if button is not None:
                button.grid_remove()

        if mode == "file" and self.file_delete_button is not None:
            # The file button fills the whole row; Delete is in the menu row.
            row.grid_columnconfigure(0, weight=1, minsize=0, uniform="")
            row.grid_columnconfigure(1, weight=0, minsize=0, uniform="")
            self.file_button.grid(row=0, column=0, sticky="ew")
        elif mode == "file":
            file_column_width = self.file_button.cget("width") + 3  # + gap
            row.grid_columnconfigure(0, weight=0, minsize=file_column_width, uniform="")
            row.grid_columnconfigure(1, weight=1, minsize=0, uniform="")
            self.file_button.grid(row=0, column=0, sticky="w", padx=(0, 3))
            if self.delete_button is not None:
                self.delete_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        elif mode == "firefox_export":
            row.grid_columnconfigure(0, weight=1, minsize=0, uniform="cookie_btn")
            row.grid_columnconfigure(1, weight=1, minsize=0, uniform="cookie_btn")
            if self.create_button is not None:
                self.create_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
            if self.delete_button is not None:
                self.delete_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))

    def change_mode(self, selected: str) -> None:
        mode = resolve_cookie_mode_key(selected, self.app_state.current_language)
        if mode is None:
            return
        set_cookie_mode(mode)
        self.update_widgets()

    def change_browser(self, selected: str) -> None:
        browser = resolve_cookie_browser_key(selected)
        if browser:
            set_cookie_browser(browser)

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="cookies.txt",
            filetypes=[("cookies.txt", "*.txt"), ("*", "*.*")],
        )
        if not path:
            return
        try:
            import_cookie_file(path)
        except OSError as e:
            messagebox.showerror(self.app_state.current_language["error_title"], str(e))
            return
        self.update_widgets()

    def create_file(self) -> None:
        """Exports the YouTube/Google cookies from Firefox into the app's own
        cookies.txt (the file yt-dlp reads in "file" mode), then tells the
        user where it is and offers to open the folder."""
        lang = self.app_state.current_language
        try:
            result = export_cookies_from_firefox()
        except Exception as e:  # CookieExportError and anything unexpected
            if not isinstance(e, CookieExportError):
                logger.exception("cookies.txt export failed")
            messagebox.showerror(
                lang["error_title"],
                lang["cookie_export_failed_message"].replace("{error}", str(e)),
            )
            return

        self.update_widgets()
        path = result.path

        if not result.logged_in:
            messagebox.showwarning(
                lang["warning_title"],
                lang["cookie_not_logged_in_message"].replace("{path}", path),
            )
            return

        message = (
            lang["cookie_created_message"]
            .replace("{count}", str(result.count))
            .replace("{path}", path)
        )
        if messagebox.askyesno(lang["cookie_section_label"], message):
            self.reveal_in_folder(path)

    def delete_file(self) -> None:
        """Deletes the app's own cookies.txt copy after confirmation. A file
        the user picked with "Choose cookies.txt" was copied here, so their
        original is never touched."""
        lang = self.app_state.current_language

        if not cookie_file_exists():
            messagebox.showinfo(lang["cookie_section_label"], lang["cookie_delete_none_message"])
            return

        if not messagebox.askyesno(lang["cookie_section_label"], lang["cookie_delete_confirm_message"]):
            return

        try:
            remove_cookie_file()
        except OSError as e:
            messagebox.showerror(
                lang["error_title"],
                lang["cookie_delete_failed_message"].replace("{error}", str(e)),
            )
            return

        self.update_widgets()

    @staticmethod
    def reveal_in_folder(path: str) -> None:
        """Opens Explorer with the file selected (falls back to just the folder)."""
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                webbrowser.open(os.path.dirname(path))
        except OSError:
            logger.warning("Could not open folder for %s", path, exc_info=True)