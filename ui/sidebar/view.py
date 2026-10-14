"""
Settings sidebar construction.

build_sidebar() creates the sidebar frame and everything inside it (theme
toggle, language menu, notification / dark-mode checkboxes, save location,
update button, cookie support, preview notification, uninstall) plus the
hamburger button that opens it, and returns them as a SimpleNamespace that
build_app_window() (ui/app_window.py) merges into self.ui.

The cookie widgets are built by _build_cookie_section(), called from the
middle of build_sidebar() so the pack order inside sidebar_content is the
same as before the split.

Callbacks, registry and colors work exactly as described in
ui/app_window.py. The repeated button / option menu / checkbox settings live
in ui/sidebar/widgets.py (sidebar_button(), sidebar_option_menu(), sidebar_checkbox());
only what differs per widget is passed here. Colors that don't change between
themes are hardcoded or come from ui/sidebar/widgets.py's constants.
"""

from types import SimpleNamespace

import customtkinter as ctk

from cookie import COOKIE_BROWSERS, get_cookie_browser
from settings import load_setting, save_setting
from ui.theme import THEMES
from ui.sidebar.widgets import (
    COOKIE_BROWSER_MENU_WIDTH, COOKIE_MODE_MENU_WIDTH,
    DANGER, DANGER_HOVER, SIDEBAR_BG, SIDEBAR_HOVER,
    sidebar_button, sidebar_checkbox, sidebar_option_menu,
)

_LIGHT = THEMES["light"]


def build_sidebar(root, registry, callbacks, sidebar_width: int, sidebar_x: int) -> SimpleNamespace:
    # Sidebar
    sidebar_frame = ctk.CTkFrame(root, width=sidebar_width, fg_color=SIDEBAR_BG, corner_radius=0)
    sidebar_frame.place(x=sidebar_x, y=0, relheight=1)
    # Fixed width: it comes from `width` above, never from whatever size the
    # children's texts request, so a language change can't resize the sidebar.
    sidebar_frame.pack_propagate(False)

    sidebar_content = ctk.CTkFrame(sidebar_frame, fg_color=SIDEBAR_BG)
    sidebar_content.pack(padx=0, pady=0, anchor="nw", fill="both", expand=True)

    close_button = ctk.CTkButton(
        sidebar_frame,
        text="✕",
        font=("Helvetica", 19),
        fg_color=SIDEBAR_BG,
        text_color="black",
        width=35, height=35,
        command=callbacks.toggle_sidebar,
        hover_color=SIDEBAR_HOVER,
    )
    close_button.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)


    # Menu (hamburger) button
    menu_button = ctk.CTkButton(
        root,
        text="☰",
        font=("Helvetica", 30, "bold"),
        fg_color=_LIGHT["menu_button"]["fg_color"],
        text_color=_LIGHT["menu_button"]["text_color"],
        width=50, height=50,
        command=callbacks.toggle_sidebar,
        hover_color=_LIGHT["menu_button"]["hover_color"],
    )
    menu_button.place(x=10, y=10)
    registry.add(menu_button, theme="menu_button")


    # Light/dark toggle inside sidebar
    light_dark = ctk.CTkButton(
        sidebar_content,
        text="",
        fg_color="#4c6a8c",
        hover_color="#3b556f",
        text_color="#fbfbfb",
        width=45, height=45,
        command=callbacks.toggle_theme,
    )
    light_dark.place(relx=0.0, rely=1.0, anchor="sw", x=10, y=-10)
    # icon (sun/moon) depends on the current theme, so it's handled by apply_button_icons()/ThemeManager
    registry.add(light_dark, theme="light_dark")


    # Language selector
    language_options = ["DE", "EN", "ES", "FR", "IT", "TR"]
    language_var = ctk.StringVar(value=language_options[0])
    language_menu = sidebar_option_menu(
        sidebar_content,
        variable=language_var,
        values=language_options,
        command=callbacks.change_language,
        width=70,
    )
    language_menu.place(relx=1.0, rely=1.0, anchor="se", x=-85, y=-10)


    # System notification checkbox
    system_notification_enabled = ctk.BooleanVar(value=load_setting("system_notification", True))
    system_notification_enabled.trace_add(
        "write",
        lambda *_: save_setting("system_notification", system_notification_enabled.get()),
    )
    system_notification_checkbox = sidebar_checkbox(sidebar_content, variable=system_notification_enabled)
    system_notification_checkbox.pack(anchor="w", pady=(60, 20), padx=10, fill="x")
    registry.add(system_notification_checkbox, text="system_notification_checkbox")


    # Start in dark mode checkbox
    dark_mode_enabled = ctk.BooleanVar(value=load_setting("start_in_dark_mode", False))
    dark_mode_enabled.trace_add(
        "write",
        lambda *_: save_setting("start_in_dark_mode", dark_mode_enabled.get()),
    )
    start_in_dark_mode_checkbox = sidebar_checkbox(sidebar_content, variable=dark_mode_enabled)
    start_in_dark_mode_checkbox.pack(anchor="w", pady=10, padx=10, fill="x")
    registry.add(start_in_dark_mode_checkbox, text="start_in_dark_mode_checkbox")


    # Save location picker
    save_location_button = sidebar_button(sidebar_content, command=callbacks.choose_save_location)
    save_location_button.pack(anchor="w", pady=(10, 0), padx=10, fill="x")
    registry.add(save_location_button, text="save_location_button", icon=("folder.png", "#fbfbfb"))

    save_location_value_label = ctk.CTkLabel(
        sidebar_content,
        text="",
        font=("Helvetica", 11),
        text_color="#333333",
    )
    save_location_value_label.pack(anchor="w", pady=(2, 10), padx=10, fill="x")


    # Check for Updates button
    check_updates_button = sidebar_button(sidebar_content)
    check_updates_button.pack(anchor="w", pady=(0, 10), padx=10, fill="x")
    registry.add(check_updates_button, text="check_updates_button", icon=("refresh.png", "#fbfbfb"))
    # command= is wired up by main.py once its UpdateChecker exists.

    cookie = _build_cookie_section(sidebar_content, registry, callbacks)


    # Preview notification button: in the bottom row, centered between the
    # light/dark toggle (x=10, 45 wide) on the left and the language menu (70 wide,
    # 85px from the right edge) on the right.
    toggle_right_edge = 10 + 45
    language_left_edge = sidebar_width - 85 - 70
    preview_x = round((toggle_right_edge + language_left_edge - 45) / 2)
    preview_notification_button = sidebar_button(
        sidebar_content, command=callbacks.preview_notification, width=45, height=45,
    )
    preview_notification_button.place(x=preview_x, y=-10, relx=0, rely=1, anchor="sw")
    registry.add(preview_notification_button, text="preview_notification_button", icon=("notification.png", "#fbfbfb"))


    # Uninstall button
    uninstall_button = sidebar_button(
        sidebar_content,
        command=callbacks.uninstall_app,
        width=70,
        fg_color=DANGER,
        hover_color=DANGER_HOVER,
    )
    uninstall_button.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)
    registry.add(uninstall_button, text="uninstall_button", icon=("uninstall.png", "#fbfbfb"))


    return SimpleNamespace(
        sidebar_frame=sidebar_frame,
        sidebar_content=sidebar_content,
        close_button=close_button,
        menu_button=menu_button,
        light_dark=light_dark,
        language_options=language_options,
        language_var=language_var,
        language_menu=language_menu,
        system_notification_enabled=system_notification_enabled,
        system_notification_checkbox=system_notification_checkbox,
        dark_mode_enabled=dark_mode_enabled,
        start_in_dark_mode_checkbox=start_in_dark_mode_checkbox,
        save_location_button=save_location_button,
        save_location_value_label=save_location_value_label,
        check_updates_button=check_updates_button,
        preview_notification_button=preview_notification_button,
        uninstall_button=uninstall_button,
        **vars(cookie),
    )


def _build_cookie_section(sidebar_content, registry, callbacks) -> SimpleNamespace:
    """Cookie support (age-restricted / members-only videos). Packs its
    widgets into sidebar_content; returns them for ui/sidebar/cookie_panel.py's
    CookiePanel.bind_widgets()."""
    # Cookie support (age-restricted / members-only videos).
    # Only the mode menu is always visible. The browser menu (next to it, in
    # cookie_menu_row) and the file widgets (below, in cookie_extra_frame) are
    # shown/hidden by CookiePanel.update_widgets() (ui/sidebar/cookie_panel.py).
    # They start unpacked (hidden).
    cookie_section_label = ctk.CTkLabel(
        sidebar_content,
        text="",
        font=("Helvetica", 13, "bold"),
        text_color="black",
        anchor="w",
    )
    cookie_section_label.pack(anchor="w", pady=(6, 0), padx=10, fill="x")
    registry.add(cookie_section_label, text="cookie_section_label")

    # One row for both menus: mode menu on the left, browser menu right next to it
    # (only in "browser" mode). Both have the fixed widths from ui/sidebar/widgets.py;
    # dynamic_resizing=False keeps them as given, so a long text can't grow a menu
    # and push the other one out of the sidebar.
    cookie_menu_row = ctk.CTkFrame(sidebar_content, fg_color="transparent")
    cookie_menu_row.pack(anchor="w", pady=(4, 0), padx=10, fill="x")

    # Texts/values are set by CookiePanel.refresh_language() (translated per language).
    cookie_mode_var = ctk.StringVar()
    cookie_mode_menu = sidebar_option_menu(
        cookie_menu_row,
        variable=cookie_mode_var,
        values=[""],
        command=callbacks.change_cookie_mode,
        width=COOKIE_MODE_MENU_WIDTH,
        dynamic_resizing=False,
    )
    cookie_mode_menu.pack(side="left")

    # Holds the mode-dependent widgets. width/height=0 so the empty frame
    # takes no space while both children are hidden.
    cookie_extra_frame = ctk.CTkFrame(sidebar_content, width=0, height=0, fg_color="transparent")
    cookie_extra_frame.pack(fill="x")

    saved_cookie_browser = get_cookie_browser()
    cookie_browser_var = ctk.StringVar(
        value=COOKIE_BROWSERS.get(saved_cookie_browser, COOKIE_BROWSERS["firefox"])
    )
    cookie_browser_menu = sidebar_option_menu(
        cookie_menu_row,
        variable=cookie_browser_var,
        values=list(COOKIE_BROWSERS.values()),
        command=callbacks.change_cookie_browser,
        width=COOKIE_BROWSER_MENU_WIDTH,
        dynamic_resizing=False,
    )

    # One row (a grid) for the buttons that sit side by side: "Create from
    # Firefox" mode shows Create + Delete, "From file" mode shows the
    # "cookies.txt" button + Delete. CookiePanel._layout_buttons() grids them
    # and sets the column widths per mode.
    cookie_buttons_row = ctk.CTkFrame(cookie_extra_frame, fg_color="transparent")
    cookie_buttons_row.grid_columnconfigure((0, 1), weight=1, uniform="cookie_btn")

    cookie_create_button = sidebar_button(
        cookie_buttons_row, command=callbacks.create_cookie_file, width=100,
    )
    cookie_create_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
    registry.add(cookie_create_button, text="cookie_create_button", icon=("export.png", "#fbfbfb"))

    cookie_delete_button = sidebar_button(
        cookie_buttons_row,
        command=callbacks.delete_cookie_file,
        fg_color=DANGER,          # not part of the light/dark theme, stays fixed
        hover_color=DANGER_HOVER,
        width=100,
    )
    cookie_delete_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
    registry.add(cookie_delete_button, text="cookie_delete_button")

    # Same width as the mode menu above it; Delete sits right next to it, so it
    # lives in the same row (cookie_buttons_row). The text is a file name, the
    # same in every language, so there is no lang key: only the icon is registered.
    cookie_file_button = sidebar_button(
        cookie_buttons_row,
        command=callbacks.choose_cookie_file,
        width=COOKIE_MODE_MENU_WIDTH,
    )
    registry.add(cookie_file_button, text="cookie_choose_file_button", icon=("folder.png", "#fbfbfb"))

    # "From file" mode: Delete sits in the mode menu's row, right next to it
    # (same place and width as the browser menu). Packed/hidden by
    # CookiePanel.update_widgets().
    cookie_file_delete_button = sidebar_button(
        cookie_menu_row,
        command=callbacks.delete_cookie_file,
        fg_color=DANGER,
        hover_color=DANGER_HOVER,
        width=COOKIE_BROWSER_MENU_WIDTH,
    )
    registry.add(cookie_file_delete_button, text="cookie_delete_button")

    # Name of the selected cookies.txt (set by CookiePanel.update_widgets()).
    cookie_file_label = ctk.CTkLabel(
        cookie_extra_frame,
        text="",
        font=("Helvetica", 11),
        text_color="#333333",
    )

    return SimpleNamespace(
        cookie_section_label=cookie_section_label,
        cookie_mode_var=cookie_mode_var,
        cookie_menu_row=cookie_menu_row,
        cookie_mode_menu=cookie_mode_menu,
        cookie_extra_frame=cookie_extra_frame,
        saved_cookie_browser=saved_cookie_browser,
        cookie_browser_var=cookie_browser_var,
        cookie_browser_menu=cookie_browser_menu,
        cookie_buttons_row=cookie_buttons_row,
        cookie_create_button=cookie_create_button,
        cookie_delete_button=cookie_delete_button,
        cookie_file_button=cookie_file_button,
        cookie_file_delete_button=cookie_file_delete_button,
        cookie_file_label=cookie_file_label,
    )