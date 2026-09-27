"""
Groups the small set of "current application status" flags that used to be
individual module-level globals in main.py, each mutated via `global` from
many different functions.

This is a structural change only: every read/write below is the exact same
statement as before, just as an attribute of an AppState instance instead of
a bare module-level name. Because attributes are mutated in place rather
than rebound, callers no longer need `global` to write to them — only a
reference to the one shared `state` instance.

Not included here: `dark_mode` (owned by ThemeManager, ui/theme.py) and the
download queue / currently-downloading item (owned by QueueView,
ui/queue_view.py) — both were already encapsulated in their own classes
before this refactor, so AppState only needed to pick up what was left.
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
