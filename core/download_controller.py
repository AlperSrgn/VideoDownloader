"""
Owns the download queue and the full lifecycle of "what happens when a
video is queued, downloading, paused, cancelled, finishes, or fails".

Before this, that lifecycle was about a dozen loosely related
module-level functions in main.py, all sharing state through globals
(queue_view, app_state, and the various progress/queue widgets) — the
same "package everything into one place" move already made for the
queue's own state (download_queue.py) and its rendering (ui/queue_view.py).
This class is the layer above QueueView: it decides *when* the next item
starts, wires yt-dlp progress into the progress bar, and reacts to a
download finishing or failing.

Widgets don't exist yet when main.py constructs this (build_app_window()
needs bound methods of this class as its button callbacks, so the
controller has to exist before the widgets it will use do). They're
attached afterwards via bind_widgets(), once build_app_window() has run —
the same build-then-wire two-step main.py already uses for UpdateChecker.
"""

from tkinter import messagebox

from downloading.downloader import download_video, download_audio
from core.quality_options import quality_label, resolve_quality_key
from ui.queue_view import QueueView
from utils import clean_playlist_url, validate_video_url


class DownloadController:
    # pause_button toggles between these two depending on state — kept as
    # class constants rather than a static dict entry since main.py's own
    # apply_button_icons() also needs them for the very first paint,
    # before any pause/resume has happened yet.
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

        # Set by bind_widgets() once main.py's build_app_window() call has
        # returned and the real widgets exist. Nothing above can actually
        # be triggered by the user before that happens, so leaving these
        # unset until then is safe — DownloadController itself is
        # constructed before its widgets exist, the same two-step
        # main.py's App class already uses for UpdateChecker.
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

    def bind_widgets(self, **widgets) -> None:
        """Called once from main.py right after build_app_window() returns
        and self.ui is assigned, with the widgets this controller drives."""
        for name, widget in widgets.items():
            setattr(self, name, widget)

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

    # -- pause button appearance ----------------------------------------------
    # Single place that sets the pause button's text/color/icon together, so
    # the three can never drift out of sync (pause_download() and
    # process_next_in_queue() both used to set these separately, and a
    # previous version of process_next_in_queue() forgot the icon — leaving
    # a "Pause" label with a leftover resume icon after a paused item was
    # cancelled and the next one started).

    def _set_pause_button_state(self, paused: bool) -> None:
        icon_file = self.RESUME_ICON_FILE if paused else self.PAUSE_ICON_FILE
        icon = self.make_icon(icon_file, "#fbfbfb")
        text_key = "resume_button" if paused else "pause_button"
        self.pause_button.configure(
            text=self.app_state.current_language[text_key],
            fg_color="#e0a12e",
            hover_color="#b87f1f",
            **({"image": icon} if icon is not None else {}),
        )

    # -- progress callbacks --------------------------------------------------
    # Called from the background download thread (see downloader.py) — must
    # not touch Tkinter widgets directly, so the actual UI update is
    # marshaled onto the main thread via root.after().

    def on_progress(self, percent: float, downloaded_mb: float, total_mb: float, eta: str) -> None:
        self.root.after(0, lambda: self._update_progress_ui(percent, downloaded_mb, total_mb, eta))

    def _update_progress_ui(self, percent: float, downloaded_mb: float, total_mb: float, eta: str) -> None:
        if self.app_state.pause_requested:
            # This update was queued (via root.after in on_progress) from a
            # yt-dlp line the background thread read just before it noticed
            # the pause request — the download has already been stopped by
            # the time we get here, so drop this stale update rather than
            # overwriting the "paused" label with it.
            return
        self.progress_bar.set(percent / 100)
        self.progress_label.configure(
            text=(
                f"{percent:.1f}%   |   {downloaded_mb:.2f} / {total_mb:.2f} MB   |   {eta}\n"
                f"{self.app_state.current_language['operation_in_progress_message']}"
            )
        )

    def on_merge_progress(self, percent: float, elapsed_seconds: float, total_seconds: float, eta: str) -> None:
        """Separate from on_progress: merge progress is based on media time
        processed by ffmpeg, not MB, so it uses a separate label format."""
        self.root.after(0, lambda: self._update_merge_progress_ui(percent, eta))

    def _update_merge_progress_ui(self, percent: float, eta: str) -> None:
        if self.app_state.pause_requested:
            # Same stale-update guard as _update_progress_ui.
            return
        self.progress_bar.set(percent / 100)
        self.progress_label.configure(
            text=f"{percent:.1f}%   |   {eta}\n{self.app_state.current_language['merging_message']}"
        )

    def on_cancel_check(self) -> bool:
        return self.app_state.cancel_requested

    def on_pause_check(self) -> bool:
        return self.app_state.pause_requested

    # -- completion / error handling -----------------------------------------

    def on_download_done(self, success_msg_key: str) -> None:
        self.root.after(0, lambda: self._finalize_download(success_msg_key))

    def _finalize_download(self, success_msg_key: str) -> None:
        lang = self.app_state.current_language
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
        intended action, not a failure: no popup, just move on to the next
        queued item (or back to idle)."""
        self._advance_queue_or_reset()

    def _handle_error(self, msg: str) -> None:
        if not self.app_state.closing:  # closing cancels the download on purpose — no error popup
            messagebox.showerror(self.app_state.current_language["error_title"], msg)
        self._advance_queue_or_reset()

    def _advance_queue_or_reset(self) -> None:
        """Shared by a finished and a failed download alike: drop the item
        that just ended, then either start the next queued one or reset the
        action buttons/progress area back to idle. Used to be duplicated
        almost verbatim between _finalize_download and _handle_error."""
        self.queue_view.current_item = None
        if self.queue_view.items:
            self.process_next_in_queue()
        else:
            self.render_queue_list()  # clears the just-ended item from the queue list
            self.hide_progress()
            self.set_widgets_state("normal")
            self.pause_button.pack_forget()
            self.download_button.pack(side="left", padx=5)
            self.download_button.configure(state="normal")
            self.queue_add_button.pack_forget()
            self.cancel_button.pack_forget()

    # -- queue rendering / preview -------------------------------------------

    def render_queue_list(self) -> None:
        """Redraw the queue list. The currently-downloading item, if any, is
        shown first as an active row (marked with ▶, no remove button —
        cancel_button is used for that instead), followed by the waiting
        items."""
        self.queue_view.render(
            widgets={
                "list_frame": self.queue_list_frame,
                "header_label": self.queue_header_label,
                "clear_button": self.clear_queue_button,
            },
            text_color=self.theme_manager.queue_item_text_color,
            make_icon=self.make_icon,
            quality_label=lambda key: quality_label(key, self.app_state.current_language),
            current_language=self.app_state.current_language,
            on_remove=self.remove_from_queue,
        )

    def fetch_queue_item_preview(self, item: dict) -> None:
        """Fetches preview info in the background and updates the queued
        item. Uses the item ID, so it can update while waiting in the
        queue."""
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
                self.app_state.current_language["warning_title"],
                self.app_state.current_language[error_key],
            )
            return

        quality_key = resolve_quality_key(self.option_var.get())
        if not quality_key:
            messagebox.showwarning(
                self.app_state.current_language["warning_title"],
                self.app_state.current_language["quality_error_message"],
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

        url = self.queue_view.current_item["url"]
        quality_key = self.queue_view.current_item["quality_key"]
        # Uses the current app_state.save_location;
        # saves to the location selected when the download starts.

        self.set_widgets_state("disabled")
        self.download_button.pack_forget()
        # Reset to its default "paused? no" look (text, color AND icon) in
        # case the previous item in the queue ended while paused.
        self._set_pause_button_state(paused=False)
        self.pause_button.pack(side="left", padx=5)
        self.queue_add_button.pack(side="left", padx=5)
        self.cancel_button.pack(pady=5)

        remaining = len(self.queue_view.items)
        starting_text = self.app_state.current_language["download_starting_message"]
        if remaining:
            starting_text += f"  ({self.app_state.current_language['queue_remaining_label']}: {remaining})"
        self.show_progress(starting_text)

        lang = self.app_state.current_language
        if quality_key == "audio":
            download_audio(
                url=url,
                save_location=self.app_state.save_location,
                on_progress=self.on_progress,
                on_cancel_check=self.on_cancel_check,
                on_done=lambda: self.on_download_done("audio_download_complete_message"),
                on_error=self.on_download_error,
                on_cancelled=self.on_download_cancelled,
                lang=lang,
                on_merge_progress=self.on_merge_progress,
                on_pause_check=self.on_pause_check,
            )
        else:
            download_video(
                url=url,
                save_location=self.app_state.save_location,
                target_resolution=quality_key,
                on_progress=self.on_progress,
                on_cancel_check=self.on_cancel_check,
                on_done=lambda: self.on_download_done("download_complete_message"),
                on_error=self.on_download_error,
                on_cancelled=self.on_download_cancelled,
                lang=lang,
                on_merge_progress=self.on_merge_progress,
                on_pause_check=self.on_pause_check,
            )

    def cancel_download(self) -> None:
        """Cancels only the item currently downloading. If more items are
        queued, the next one starts automatically once this one stops."""
        self.app_state.cancel_requested = True
        self.progress_label.configure(text=self.app_state.current_language["download_canceling_message"])

    def pause_download(self) -> None:
        """Toggles the paused state of the item currently downloading.

        The background download thread polls on_pause_check() (see
        downloader.py's apply_pause_state) and suspends/resumes the yt-dlp
        or ffmpeg process accordingly, so pausing genuinely stops
        network/CPU usage rather than just freezing the progress bar.
        """
        self.app_state.pause_requested = not self.app_state.pause_requested
        self._set_pause_button_state(paused=self.app_state.pause_requested)

        if self.app_state.pause_requested:
            self.progress_label.configure(text=self.app_state.current_language["operation_paused_message"])