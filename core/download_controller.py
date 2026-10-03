"""
Drives the download queue and the lifecycle of each item: queued,
downloading, paused, cancelled, finished or failed.

It sits on top of QueueView (which holds the queue state and draws the
list): it decides *when* the next item starts, wires download progress
into the progress bar, and reacts to a download finishing, failing or
being cancelled.

Widgets don't exist yet when main.py constructs this, because
build_app_window() needs this class's bound methods as button callbacks.
They are attached afterwards via bind_widgets() — the same build-then-wire
two-step main.py uses for UpdateChecker.
"""

from tkinter import messagebox

from downloading.downloader import download_video, download_audio
from core.quality_options import quality_label, resolve_quality_key
from system.process_manager import set_keep_awake
from ui.notifications import ToastNotifier
from ui.queue_view import QueueView
from utils import clean_playlist_url, validate_video_url


class DownloadController:
    # pause_button's icon depends on the paused state, so it is not in the
    # UI registry. Public constants because App.apply_button_icons() (main.py)
    # also uses them for the first paint.
    PAUSE_ICON_FILE = "pause.png"
    RESUME_ICON_FILE = "resume.png"

    def __init__(self, app_state, theme_manager, make_icon, send_notification,
                 notification_icon, get_system_notification_enabled):
        self.app_state = app_state
        self.theme_manager = theme_manager
        self.make_icon = make_icon
        self.send_notification = send_notification
        self.notification_icon = notification_icon
        self.get_system_notification_enabled = get_system_notification_enabled

        self.queue_view = QueueView()

        # Assigned by bind_widgets() once the real widgets exist (see the
        # module docstring). The user can't trigger any method that uses
        # them before that, so None until then is safe.
        self.root = None
        self.progress_bar = None
        self.progress_label = None
        self.download_button = None
        self.pause_button = None
        self.queue_add_button = None
        self.cancel_button = None
        self.queue_list_frame = None
        self.queue_header_label = None
        self.clear_queue_button = None
        self.url_entry = None
        self.option_var = None
        self.uninstall_button = None
        self.check_updates_button = None
        self.toast = None  # ToastNotifier, created in bind_widgets() from the toast label

    def bind_widgets(self, **widgets) -> None:
        """Called once from main.py right after build_app_window() returns.
        Each keyword becomes an attribute of the same name, so the names
        must match the ones initialised to None in __init__."""
        # The toast label is not stored directly: ToastNotifier owns it and
        # its animation (see ui/notifications.py).
        toast_label = widgets.pop("toast_label")
        for name, widget in widgets.items():
            setattr(self, name, widget)
        self.toast = ToastNotifier(self.root, toast_label)

    @property
    def lang(self) -> dict:
        """The current UI language dict (changes when the user switches language)."""
        return self.app_state.current_language

    # -- generic UI helpers --------------------------------------------------

    def set_widgets_state(self, state: str) -> None:
        for w in [self.uninstall_button, self.check_updates_button]:
            w.configure(state=state)

    def show_progress(self, text: str = "") -> None:
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10)
        self.progress_label.configure(text=text)
        self.progress_label.pack()

    def hide_progress(self) -> None:
        self.progress_bar.pack_forget()
        self.progress_label.pack_forget()

    def _show_downloading_ui(self) -> None:
        """Switch the buttons and progress area to the "download in
        progress" layout."""
        self.set_widgets_state("disabled")
        self.download_button.pack_forget()
        # Reset to the non-paused look (text, color and icon), in case the
        # previous queue item ended while paused.
        self._set_pause_button_state(paused=False)
        self.pause_button.pack(side="left", padx=5)
        self.queue_add_button.pack(side="left", padx=5)
        self.cancel_button.pack(pady=5)

        remaining = len(self.queue_view.items)
        starting_text = self.lang["download_starting_message"]
        if remaining:
            starting_text += f"  ({self.lang['queue_remaining_label']}: {remaining})"
        self.show_progress(starting_text)

    def _show_idle_ui(self) -> None:
        """Back to the idle layout once the queue has run out."""
        self.render_queue_list()  # clears the just-ended item from the queue list
        self.hide_progress()
        self.set_widgets_state("normal")
        self.pause_button.pack_forget()
        self.download_button.pack(side="left", padx=5)
        self.download_button.configure(state="normal")
        self.queue_add_button.pack_forget()
        self.cancel_button.pack_forget()

    # -- pause button appearance ----------------------------------------------
    # Single place that sets the pause button's text/color/icon together, so
    # the three can never drift out of sync.

    def _set_pause_button_state(self, paused: bool) -> None:
        icon_file = self.RESUME_ICON_FILE if paused else self.PAUSE_ICON_FILE
        icon = self.make_icon(icon_file, "#fbfbfb")
        text_key = "resume_button" if paused else "pause_button"
        self.pause_button.configure(
            text=self.lang[text_key],
            fg_color="#e0a12e",
            hover_color="#b87f1f",
            **({"image": icon} if icon is not None else {}),
        )

    # -- progress callbacks --------------------------------------------------
    # Called from the background download thread (see downloader.py), which
    # must not touch Tkinter widgets, so each callback hands the actual UI
    # update to the main thread via root.after().

    def on_progress(self, percent: float, downloaded_mb: float, total_mb: float, eta: str) -> None:
        self.root.after(0, lambda: self._update_progress_ui(percent, downloaded_mb, total_mb, eta))

    def _update_progress_ui(self, percent: float, downloaded_mb: float, total_mb: float, eta: str) -> None:
        if self.app_state.pause_requested:
            # Stale update: it was queued via root.after() just before the
            # download thread noticed the pause request. By now the
            # download (or ffmpeg) is already stopped/suspended, so drop it
            # instead of overwriting the "paused" label.
            return
        self.progress_bar.set(percent / 100)
        self.progress_label.configure(
            text=(
                f"{percent:.1f}%   |   {downloaded_mb:.2f} / {total_mb:.2f} MB   |   {eta}\n"
                f"{self.lang['operation_in_progress_message']}"
            )
        )

    def on_merge_progress(self, percent: float, elapsed_seconds: float, total_seconds: float, eta: str) -> None:
        """Separate from on_progress: merge progress is based on media time
        processed by ffmpeg, not MB, so it uses a separate label format.
        Covers both the video+audio merge and the audio-only mp3
        conversion."""
        self.root.after(0, lambda: self._update_merge_progress_ui(percent, eta))

    def _update_merge_progress_ui(self, percent: float, eta: str) -> None:
        if self.app_state.pause_requested:
            # Same stale-update guard as _update_progress_ui.
            return
        self.progress_bar.set(percent / 100)
        self.progress_label.configure(
            text=f"{percent:.1f}%   |   {eta}\n{self.lang['merging_message']}"
        )

    def on_cancel_check(self) -> bool:
        return self.app_state.cancel_requested

    def on_pause_check(self) -> bool:
        return self.app_state.pause_requested

    # -- completion / error handling -----------------------------------------

    def on_download_done(self, success_msg_key: str) -> None:
        self.root.after(0, lambda: self._finalize_download(success_msg_key))

    def _finalize_download(self, success_msg_key: str) -> None:
        lang = self.lang
        self.send_notification(
            self.get_system_notification_enabled(),
            lang["operation_completed_message"],
            lang[success_msg_key],
            self.notification_icon,
        )
        self._advance_queue_or_reset()

    def on_download_error(self, msg: str) -> None:
        self.root.after(0, lambda: self._handle_error(msg))

    def on_download_cancelled(self) -> None:
        self.root.after(0, self._handle_cancelled)

    def _handle_cancelled(self) -> None:
        """User pressed Cancel (or closed the app mid-download). This is an
        intended action, not a failure: no popup, just a brief toast, then
        move on to the next queued item (or back to idle)."""
        if not self.app_state.closing:  # window is withdrawn while closing — nothing to show
            self.toast.show(self.lang["download_canceled_message"])
        self._advance_queue_or_reset()

    def _handle_error(self, msg: str) -> None:
        if not self.app_state.closing:  # closing cancels the download on purpose — no error popup
            messagebox.showerror(self.lang["error_title"], msg)
        self._advance_queue_or_reset()

    def _advance_queue_or_reset(self) -> None:
        """Shared by finished, failed and cancelled downloads: drop the item
        that just ended, then either start the next queued one or reset the
        action buttons/progress area back to idle."""
        self.queue_view.current_item = None
        if self.queue_view.items:
            self.process_next_in_queue()
        else:
            set_keep_awake(False)  # nothing left to download: allow sleep again
            self._show_idle_ui()

    # -- queue rendering / preview -------------------------------------------

    def render_queue_list(self) -> None:
        """Redraws the queue list with the current theme color and language
        (see QueueView.render for the row layout). Call it after any change
        to the queue, the theme or the language."""
        self.queue_view.render(
            widgets={
                "list_frame": self.queue_list_frame,
                "header_label": self.queue_header_label,
                "clear_button": self.clear_queue_button,
            },
            text_color=self.theme_manager.queue_item_text_color,
            make_icon=self.make_icon,
            quality_label=lambda key: quality_label(key, self.lang),
            current_language=self.lang,
            on_remove=self.remove_from_queue,
        )

    def fetch_queue_item_preview(self, item: dict) -> None:
        """Fetches preview info in the background and attaches it to the
        queued item. The item is looked up by ID when the result arrives,
        so it is skipped if the item was removed in the meantime."""
        self.queue_view.fetch_preview(item, after=self.root.after, on_done=self._apply_preview_and_render)

    def _apply_preview_and_render(self, item_id: int, info: dict, thumb_bytes) -> None:
        self.queue_view.apply_preview(item_id, info, thumb_bytes)
        self.render_queue_list()

    def remove_from_queue(self, item_id: int) -> None:
        self.queue_view.remove(item_id)
        self.render_queue_list()

    def clear_queue(self) -> None:
        self.queue_view.clear()
        self.render_queue_list()

    # -- adding / starting downloads ------------------------------------------

    def add_to_queue(self) -> None:
        raw_url = self.url_entry.get().strip()
        error_key = validate_video_url(raw_url)
        if error_key:
            messagebox.showwarning(
                self.lang["warning_title"],
                self.lang[error_key],
            )
            return

        quality_key = resolve_quality_key(self.option_var.get())
        if not quality_key:
            messagebox.showwarning(
                self.lang["warning_title"],
                self.lang["quality_error_message"],
            )
            return

        url = clean_playlist_url(raw_url)
        queued_item = self.queue_view.enqueue(url, quality_key)
        self.url_entry.delete(0, "end")
        self.render_queue_list()
        self.fetch_queue_item_preview(queued_item)

        if self.queue_view.current_item is None:
            self.process_next_in_queue()

    def process_next_in_queue(self) -> None:
        """Pop the next item off the queue and start downloading it. Assumes
        queue_view.current_item is currently None (nothing else is in
        flight)."""
        if self.queue_view.pop_next() is None:
            return

        self.render_queue_list()
        self.app_state.cancel_requested = False
        self.app_state.pause_requested = False

        # Keep the PC from going to sleep while an item is downloading or
        # merging. Stays on across queued items; released by
        # pause_download() while paused, and in _advance_queue_or_reset()
        # once the queue is idle.
        set_keep_awake(True)

        self._show_downloading_ui()
        self._start_download(self.queue_view.current_item)

    def _start_download(self, item: dict) -> None:
        quality_key = item["quality_key"]
        # save_location is read when the item starts, not when it was
        # queued, so a folder changed in the meantime applies.
        common = dict(
            url=item["url"],
            save_location=self.app_state.save_location,
            on_progress=self.on_progress,
            on_cancel_check=self.on_cancel_check,
            on_error=self.on_download_error,
            on_cancelled=self.on_download_cancelled,
            lang=self.lang,
            on_merge_progress=self.on_merge_progress,
            on_pause_check=self.on_pause_check,
        )
        if quality_key == "audio":
            download_audio(
                **common,
                on_done=lambda: self.on_download_done("audio_download_complete_message"),
            )
        else:
            download_video(
                **common,
                target_resolution=quality_key,
                on_done=lambda: self.on_download_done("download_complete_message"),
            )

    def cancel_download(self) -> None:
        """Cancels only the item currently downloading. If more items are
        queued, the next one starts automatically once this one stops."""
        self.app_state.cancel_requested = True
        self.progress_label.configure(text=self.lang["download_canceling_message"])

    def pause_download(self) -> None:
        """Toggles the paused state of the item currently downloading.

        The background download thread polls on_pause_check() (see
        downloader.py) and reacts differently per phase, so pausing
        genuinely stops network/CPU usage rather than just freezing the
        progress bar: during a yt-dlp download it stops yt-dlp (leaving the
        partial file) and relaunches the same command on resume so it
        continues from that file; during the ffmpeg merge/convert step it
        suspends and later resumes the ffmpeg process in place
        (apply_pause_state in system/process_manager.py).
        """
        self.app_state.pause_requested = not self.app_state.pause_requested
        self._set_pause_button_state(paused=self.app_state.pause_requested)
        # A paused download isn't using the system, so don't hold it awake.
        set_keep_awake(not self.app_state.pause_requested)

        if self.app_state.pause_requested:
            self.progress_label.configure(text=self.lang["operation_paused_message"])