"""
The settings sidebar: its widgets, open/close animation and cookie section.

    view.py          build_sidebar(): builds the sidebar frame, everything inside it
                     (incl. the cookie section) and the hamburger button.
    controller.py    SidebarController: slide animation and open state. Its widgets
                     are attached after construction via bind_widgets().
    cookie_panel.py  CookiePanel: which cookie widgets show for the selected mode,
                     language refresh and the handlers behind the cookie buttons.
    widgets.py       sidebar_button() / sidebar_option_menu() / sidebar_checkbox()
                     and the sidebar's color constants.

Nothing is imported here on purpose, same as ui/__init__.py: callers import the
module they need, e.g. `from ui.sidebar.view import build_sidebar`.
"""
