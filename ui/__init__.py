"""
The app's user-interface package: everything that builds, styles and animates
widgets, with no download or update logic of its own.

    app_window.py     build_app_window(): the main window (URL row, queue list,
                      bottom action panel, toast label). Returns every widget as
                      one flat namespace that main.py keeps as self.ui. Also holds
                      WINDOW_TITLE_PREFIX, used by main.py's single-instance check.
    sidebar/          the settings sidebar as its own subpackage (see
                      ui/sidebar/__init__.py): view.py (build_sidebar(), incl. the
                      cookie section and hamburger button), controller.py
                      (SidebarController: slide animation and open state),
                      cookie_panel.py (CookiePanel) and widgets.py (button / menu /
                      checkbox factories and the sidebar's color constants).
    ytdlp_status.py   YtdlpStatusPanel: the yt-dlp.exe preparation status (first-run
                      download, self-update, retry button, URL entry lock, version
                      label) and the `ready` flag the Download button depends on.
    registry.py       UiRegistry: each widget declares its translated text, icon
                      and theme key once, where it is created; main.py loops over it.
    theme.py          THEMES (light/dark style dicts) and ThemeManager.
    queue_view.py     QueueView: draws the download queue and fetches previews.
    notifications.py  notify() for system notifications, ToastNotifier for the
                      in-app slide-in toast.

Nothing is imported here on purpose: importing `ui` stays free (no customtkinter,
no widgets are created); callers import the module they need, e.g.
`from ui.app_window import build_app_window`.
"""