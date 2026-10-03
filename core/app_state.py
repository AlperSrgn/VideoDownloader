"""
Application-wide status flags shared between App, DownloadController and
the update/close logic.

Not included here: `dark_mode` (owned by ThemeManager, ui/theme.py) and the
download queue / currently-downloading item (owned by DownloadQueue,
core/download_queue.py).
"""


class AppState:
    def __init__(self, save_location: str, sidebar_width: int):
        self.cancel_requested = False
        self.pause_requested = False
        self.closing = False  # True once the user confirmed closing during an active download
        self.current_language: dict = {}
        self.sidebar_open = False
        self.sidebar_x = -sidebar_width
        self.save_location = save_location