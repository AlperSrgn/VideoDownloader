"""
Opening and closing the settings sidebar: the slide animation and the open /
closed state.

ui/sidebar.py builds the sidebar's widgets; this class only moves them.
Widgets don't exist yet when main.py constructs it, because
build_app_window() needs toggle() as the callback of the hamburger and close
buttons. They are attached afterwards via bind_widgets(), the same
build-then-wire two-step the other panels (CookiePanel, YtdlpStatusPanel,
AppLifecycle) use.
"""

import time

SIDEBAR_ANIMATION_MS = 260  # total slide time
SIDEBAR_FRAME_MS = 8        # target interval between frames; the real one is
                            # limited by the OS timer and by how long each
                            # redraw takes (see _animate)


class SidebarController:
    def __init__(self, app_state, sidebar_width: int):
        self.app_state = app_state
        self.sidebar_width = sidebar_width

        # Assigned by bind_widgets() once the real widgets exist. The user
        # can't trigger toggle() before that, so None until then is safe.
        self.root = None
        self.sidebar_frame = None
        self.menu_button = None

        self._anim_id = None  # pending root.after() id of the slide in progress

    def bind_widgets(self, **widgets) -> None:
        """Called once from main.py right after build_app_window() returns.
        Each keyword becomes an attribute of the same name, so the names
        must match the ones initialised to None in __init__."""
        for name, widget in widgets.items():
            setattr(self, name, widget)

    def toggle(self) -> None:
        if self.app_state.sidebar_open:
            self._animate(-self.sidebar_width)
            self.menu_button.place(x=10, y=10)
        else:
            # Let Tk finish laying out/drawing pending widget updates before
            # the sidebar starts moving into view.
            self.root.update_idletasks()
            self._animate(0)
            self.menu_button.place_forget()
        self.app_state.sidebar_open = not self.app_state.sidebar_open

    def _animate(self, target_x: int, duration_ms: int = SIDEBAR_ANIMATION_MS) -> None:
        """Slide the sidebar to target_x.
        Use a time-based animation with ease-out instead of fixed steps.
        Since each place() call redraws all child widgets,
        calling it too frequently can cause pixelated or partially drawn widgets.
        Frames are paced according to processing time, and a new toggle cancels any ongoing animation."""
        if self._anim_id is not None:
            self.root.after_cancel(self._anim_id)
            self._anim_id = None

        start_x = self.app_state.sidebar_x
        start_time = time.perf_counter()

        def frame() -> None:
            frame_start = time.perf_counter()
            progress = min(1.0, (frame_start - start_time) * 1000 / duration_ms)
            eased = 1 - (1 - progress) ** 4  # ease-out quart: fast start, long soft landing
            new_x = round(start_x + (target_x - start_x) * eased)
            # Skip the place() (and the widget redraw it triggers) when the
            # rounded position hasn't changed, which happens a lot in the slow tail.
            if new_x != self.app_state.sidebar_x:
                self.app_state.sidebar_x = new_x
                self.sidebar_frame.place(x=new_x, y=0)
            if progress < 1.0:
                # Subtract the time this frame took so the interval stays even
                # instead of drifting when a redraw is slow.
                work_ms = (time.perf_counter() - frame_start) * 1000
                delay = max(1, round(SIDEBAR_FRAME_MS - work_ms))
                self._anim_id = self.root.after(delay, frame)
            else:
                self._anim_id = None
                self.app_state.sidebar_x = target_x
                self.sidebar_frame.place(x=target_x, y=0)

        frame()
