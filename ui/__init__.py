"""
The app's user-interface package: everything that builds, styles and animates
widgets, with no download or update logic of its own.

    app_window.py     build_app_window(): the main window (URL row, queue list,
                      bottom action panel, toast label). Returns every widget as
                      one flat namespace that main.py keeps as self.ui. Also holds
                      WINDOW_TITLE_PREFIX, used by main.py's single-instance check.
    sidebar.py        build_sidebar(): the settings sidebar, incl. the cookie
                      section and the hamburger button that opens it.
    cookie_panel.py   CookiePanel: which cookie widgets show for the selected mode,
                      language refresh of the mode menu, and the handlers behind
                      the cookie buttons (file picker, Firefox export, delete).
    widgets.py        sidebar_button() / sidebar_option_menu() / sidebar_checkbox()
                      and the sidebar's color constants.
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
