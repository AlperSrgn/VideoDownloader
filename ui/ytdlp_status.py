"""
yt-dlp.exe preparation status: first-run download, self-update, retry.

Owns everything the app shows while yt-dlp.exe is being made ready:
  - the status label / retry button above the action buttons
  - locking the URL entry while the exe is being downloaded
  - the small "yt-dlp vX" version label in the bottom-right corner
  - the `ready` flag the Download button depends on

Same build-then-wire pattern as DownloadController and CookiePanel: main.py
constructs it before the window (the retry button needs `retry` as its
callback), then attaches the widgets with bind_widgets() afterwards.
"""

import threading

import customtkinter as ctk

from core.error_classifier import classify_ytdlp_download_error, classify_ytdlp_update_error
from languages import LANGUAGES


class YtdlpStatusPanel:
    def __init__(self, app_state, refresh_download_button, is_app_update_downloading):
        """
        refresh_download_button: called whenever `ready` changes, so the
            Download button can be re-derived (see App.refresh_download_button).
        is_app_update_downloading: callable returning True while the app-update
            installer is downloading. Its "%" progress is shown in the same
            status label, so it must not be hidden or overwritten. A callable
            (not a value) because the UpdateChecker is created after this panel.
        """
        self.app_state = app_state
        self._refresh_download_button = refresh_download_button
        self._is_app_update_downloading = is_app_update_downloading

        # True while yt-dlp.exe is available and not being replaced. False at
        # startup, during the initial download or `--update-to` update
        # (checking_update), or after a failed initial download.
        self.ready = False

        # Assigned by bind_widgets().
        self.root = None
        self.url_entry = None
        self.status_label = None
        self.retry_button = None
        self.action_buttons_frame = None
        self.version_label = None

    def bind_widgets(self, **widgets) -> None:
        """Called once from main.py right after build_app_window() returns."""
        for name, widget in widgets.items():
            setattr(self, name, widget)

        # yt-dlp version label (populated asynchronously by fetch()).
        self.version_label = ctk.CTkLabel(
            self.root, text="", font=ctk.CTkFont(size=10), text_color="#888888",
        )
        self.version_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-5)

    @property
    def lang(self) -> dict:
        return self.app_state.current_language or LANGUAGES.get("EN", {})

    # -- setup / retry -------------------------------------------------------

    def fetch(self) -> None:
        """Runs ensure_ytdlp (first-run download / self-update) in the
        background, reports its progress through on_status() and shows the
        resulting version in the version label.

        ensure_ytdlp downloads on first run; on later launches it checks for
        updates at most once every 12 hours and once per session.
        """
        # Set synchronously on the main thread, before the worker starts, so
        # there is no window in which Download is enabled while ensure_ytdlp
        # may already be replacing the exe. Also covers the retry button.
        self.ready = False
        self._refresh_download_button()

        def worker():
            try:
                from settings import get_appdata_path
                from ytdlp import ensure_ytdlp, get_ytdlp_version
                exe_path = ensure_ytdlp(get_appdata_path(), on_status=self.on_status)
                version_text = f"yt-dlp v{get_ytdlp_version(exe_path)}"
            except Exception:
                version_text = "yt-dlp version unavailable"
            self.root.after(0, lambda: self.version_label.configure(text=version_text))

        threading.Thread(target=worker, daemon=True).start()

    def retry(self) -> None:
        """Called from the retry button after a failed first-run yt-dlp.exe
        download. Re-runs the startup setup; ensure_ytdlp tries the download
        again since it was never marked as checked/cached."""
        self.retry_button.pack_forget()
        self.fetch()

    # -- status callback -----------------------------------------------------

    def on_status(self, stage: str, detail) -> None:
        """Called from ensure_ytdlp's (background) thread; hands the actual UI
        update to the main thread.

        Keeps `ready` in sync and derives the download button from it; also
        locks the URL entry while yt-dlp.exe is being downloaded, preventing
        failed preview fetches and a stuck "Loading..." state.

        detail is the download percentage (0-100) or the failure exception.
        """
        self.root.after(0, lambda: self._apply_status(stage, detail))

    def _show_status(self, text: str) -> None:
        self.status_label.configure(text=text)
        self.status_label.pack(pady=(0, 5), before=self.action_buttons_frame)

    def _apply_status(self, stage: str, detail) -> None:
        lang = self.lang

        # While the app-update installer is downloading, the status label is
        # showing its "%" progress -- don't hide/overwrite it.
        updating = self._is_app_update_downloading()

        if stage == "ready":
            if not updating:
                self.status_label.pack_forget()
            self.retry_button.pack_forget()
            self.url_entry.configure(state="normal")
            self.ready = True
            self._refresh_download_button()  # stays disabled if a download/app update is active
            return

        if stage == "error":
            # Classifies yt-dlp.exe download errors as connection or other
            # errors, showing the raw error message for non-connection failures.
            message = classify_ytdlp_download_error(
                detail if isinstance(detail, Exception) else Exception("unknown"), lang
            )
            self._show_status(message)
            self.retry_button.configure(text=lang["ytdlp_retry_button"])
            self.retry_button.pack(pady=(0, 5), before=self.action_buttons_frame)
            self.ready = False
            self._refresh_download_button()
            self.url_entry.configure(state="disabled")
            return

        if stage == "update_failed":
            # Self-update check failed on a later launch, but this is not
            # fatal because the existing yt-dlp.exe still works. Keep
            # download/URL controls enabled, show a brief classified warning,
            # then hide it after a few seconds.
            message = classify_ytdlp_update_error(
                detail if isinstance(detail, Exception) else Exception("unknown"), lang
            )
            self.retry_button.pack_forget()
            if not updating:
                self._show_status(message)
            self.url_entry.configure(state="normal")
            self.ready = True
            self._refresh_download_button()
            if not updating:
                self.root.after(6000, self.status_label.pack_forget)
            return

        # Every stage below is transitional (checking_update, downloading,
        # unknown): `--update-to` replaces yt-dlp.exe in place, so a download
        # must not be able to start (or spawn its own ensure_ytdlp) until
        # "ready" / "update_failed" arrives.
        self.ready = False
        self._refresh_download_button()

        if stage == "checking_update":
            # The exe already exists and works (this stage only occurs when an
            # exe was already there), so the URL entry can stay usable -- only
            # Download is held back until the update check finishes.
            text = lang["ytdlp_checking_message"]
            self.url_entry.configure(state="normal")
        elif stage == "downloading":
            # First run: the exe doesn't exist yet. Lock the URL entry too, so
            # a pasted link can't kick off a preview fetch that's doomed to
            # fail silently and leave "Loading..." stuck on screen.
            text = (
                lang["ytdlp_downloading_message"].replace("{percent}", f"{detail:.0f}")
                if detail is not None
                else lang["ytdlp_downloading_indeterminate_message"]
            )
            self.url_entry.configure(state="disabled")
        else:
            text = lang["ytdlp_downloading_indeterminate_message"]

        self.retry_button.pack_forget()
        self._show_status(text)
