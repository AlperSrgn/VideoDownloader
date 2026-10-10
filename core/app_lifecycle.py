"""
The end of the app's life: closing the window (X) and uninstalling.

  - on_close_request(): idle -> close right away; download/merge in progress
                        -> pause it, ask, and on confirm stop it through the
                        normal cancel path before closing
  - uninstall_app():    confirm, then launch the Inno Setup uninstaller

The start of the app's life (single-instance check) is a plain Windows API
call and lives in system/process_manager.py; this module is the part that
needs the app's state, translated texts and widgets.

Same build-then-wire pattern as DownloadController, CookiePanel and
YtdlpStatusPanel: main.py constructs it before the window (the window's
close handler and the uninstall button use its bound methods), then attaches
the root window with bind_widgets().
"""

import os
import subprocess
import sys
from tkinter import messagebox

from downloading.downloader import TEMP_PREFIX
from utils import cleanup_temp_files


class AppLifecycle:
    def __init__(self, app_state, queue_view, get_update_checker):
        """
        queue_view: the DownloadController's QueueView (its current_item says
            whether a download is in flight; clear() stops the next queued
            item from starting).
        get_update_checker: callable returning the UpdateChecker. A callable
            (not the object) because the UpdateChecker is created after the
            window, which is after this class.
        """
        self.app_state = app_state
        self.queue_view = queue_view
        self._get_update_checker = get_update_checker

        # Assigned by bind_widgets().
        self.root = None

    def bind_widgets(self, **widgets) -> None:
        """Called once from main.py right after build_app_window() returns."""
        for name, widget in widgets.items():
            setattr(self, name, widget)

    @property
    def lang(self) -> dict:
        """The current UI language dict (changes when the user switches language)."""
        return self.app_state.current_language

    @property
    def _update_checker(self):
        return self._get_update_checker()

    # -- Window close (X) ----------------------------------------------------

    def on_close_request(self) -> None:
        """Idle: close right away. Download/merge in progress: pause it and
        ask. On confirm, the download is stopped through the normal cancel
        path (stops yt-dlp/ffmpeg and lets the worker delete its temp
        files), then the app closes. Declining restores the previous pause
        state, so the download continues where it left off."""
        if self.app_state.closing:
            return

        queue_view = self.queue_view
        if queue_view.current_item is not None:
            # Freeze the download while the dialog is open, using the same
            # pause mechanism as the Pause button (the button itself is
            # left untouched).
            item_at_open = queue_view.current_item
            was_paused = self.app_state.pause_requested
            self.app_state.pause_requested = True
            if not messagebox.askyesno(
                self.lang["close_confirm_title"],
                self.lang["close_confirm_message"],
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
            self.root.withdraw()  # window disappears immediately

        # An app-update installer download in progress: cancel it so its
        # partial .part file gets deleted (_finish_close waits for that).
        if self._update_checker.is_downloading:
            self._update_checker.cancel_download()
            self.root.withdraw()

        self._finish_close(0)

    def _finish_close(self, attempt: int) -> None:
        """Waits (max ~10 s) for the cancelled worker to finish, then closes.
        Anything still alive after that is killed by the job object."""
        busy = (
            self.queue_view.current_item is not None
            or self._update_checker.is_downloading
        )
        if busy and attempt < 100:
            self.root.after(100, lambda: self._finish_close(attempt + 1))
            return
        if self.app_state.closing:
            # Processes should be stopped by now (any that aren't are killed
            # by the job object as we exit); remove whatever temp files remain.
            cleanup_temp_files(self.app_state.save_location, TEMP_PREFIX)
        self.root.destroy()

    # -- Uninstall -----------------------------------------------------------

    def uninstall_app(self) -> None:
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        uninstall_path = os.path.join(app_dir, "unins000.exe")

        if not messagebox.askyesno(
            self.lang["uninstall_app_title"],
            self.lang["uninstall_app_message"],
        ):
            return

        if os.path.exists(uninstall_path):
            subprocess.Popen([uninstall_path])
            sys.exit()
        else:
            messagebox.showerror(
                self.lang["error_title"],
                self.lang["file_not_found_error"],
            )
