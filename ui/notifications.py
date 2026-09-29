"""
User notifications: system notifications (Windows toast via plyer) and the
in-app toast (a brief label that slides in from the bottom-right corner).

System notifications: both call sites — a download finishing (core/download_controller.py) and
the sidebar's "preview notification" button (main.py) — share the same
"only if the user's checkbox is on" guard, so it's centralized here
rather than repeated at each call site. This is also the only place that
imports plyer, so neither of those two callers needs to know it exists.

In-app toast: ToastNotifier (below) owns the slide-in/out animation and its
timers. The label widget itself is built by build_app_window() and handed in
by DownloadController.bind_widgets(); this module only animates and
shows/hides it, it doesn't decide *when* a toast appears.
"""

from plyer import notification


def notify(enabled: bool, title: str, message: str, icon: str, timeout: int = 3) -> None:
    """Shows a system notification, unless `enabled` is False — the
    user's "system_notification" checkbox setting in main.py."""
    if not enabled:
        return
    notification.notify(title=title, message=message, timeout=timeout, app_icon=icon)


class ToastNotifier:
    """Slides a pre-built label in from the right edge, holds it, then slides
    it back out.

    CTk has no built-in animation, so the slide is done by hand: repeatedly
    nudging the label's place(x=...) offset via root.after(). Used for things
    that are neither an error (no popup wanted) nor worth a persistent status
    line — currently just the "cancelled" notice.

    Must be used from the main (Tk) thread only.
    """

    # REST_X/Y are the place() offsets once fully shown; the "hidden" x (fully
    # off the right edge) is computed per-show from the label's own width,
    # since that depends on the message text. ANIM_FRAMES * ANIM_INTERVAL_MS
    # is roughly how long the slide itself takes (12 * 15ms ~ 180ms).
    REST_X = -18
    Y = -50
    ANIM_FRAMES = 12
    ANIM_INTERVAL_MS = 15

    def __init__(self, root, label):
        self.root = root
        self.label = label
        self._hidden_x = 0
        # root.after() ids for the pending hide timer and the in-flight
        # animation frame, so a second toast while one is still showing or
        # sliding cancels it cleanly instead of the two fighting over the
        # widget's position.
        self._hide_job = None
        self._anim_job = None

    def show(self, text: str, duration_ms: int = 2500) -> None:
        self._cancel_timers()
        self.label.configure(text=text)

        # Place far off-screen first, purely to get an accurate width out of
        # winfo_reqwidth() below (it needs the label mapped with its final
        # text/padding to measure correctly) - this position is never seen.
        self.label.place(relx=1.0, rely=1.0, y=self.Y, anchor="se", x=-9999)
        self.label.update_idletasks()
        # A bit past the edge, so no sliver peeks in. Stored so the hide
        # animation slides back to exactly where the show animation started.
        self._hidden_x = self.label.winfo_reqwidth() + 20
        self.label.place_configure(x=self._hidden_x)

        self._animate_x(self._hidden_x, self.REST_X,
                        on_complete=lambda: self._schedule_hide(duration_ms))

    def _schedule_hide(self, duration_ms: int) -> None:
        self._hide_job = self.root.after(duration_ms, self._start_hide)

    def _start_hide(self) -> None:
        self._hide_job = None
        self._animate_x(self.REST_X, self._hidden_x, on_complete=self.label.place_forget)

    def _animate_x(self, start_x: int, end_x: int, frame: int = 0, on_complete=None) -> None:
        t = frame / self.ANIM_FRAMES
        eased = 1 - (1 - t) ** 3  # ease-out cubic: fast start, gentle landing
        self.label.place_configure(x=round(start_x + (end_x - start_x) * eased))

        if frame >= self.ANIM_FRAMES:
            self._anim_job = None
            if on_complete:
                on_complete()
            return
        self._anim_job = self.root.after(
            self.ANIM_INTERVAL_MS,
            lambda: self._animate_x(start_x, end_x, frame + 1, on_complete),
        )

    def _cancel_timers(self) -> None:
        if self._hide_job is not None:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None
        if self._anim_job is not None:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None