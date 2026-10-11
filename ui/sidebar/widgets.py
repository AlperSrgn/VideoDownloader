"""
Small factories for the sidebar's repeated widget definitions.

Every sidebar button, option menu and checkbox used to spell out the same
font/color/height keyword arguments. These helpers hold those defaults in one
place; anything passed as a keyword argument overrides its default, e.g.

    sidebar_button(parent, command=cb, width=100)
    sidebar_button(parent, command=cb, fg_color=DANGER, hover_color=DANGER_HOVER)

They only create the widget: placing it (pack/place/grid) and registering it
(registry.add(...)) stay at the call site in ui/sidebar/view.py.

Not covered on purpose: the light/dark toggle (icon only, no font) and the
sidebar's labels, whose settings differ from one another.

The colors below are the sidebar's own palette; like the hardcoded colors in
the builders they do not change between light and dark mode.

The two cookie menu widths at the end of the constants are tunable layout sizes,
not colors; they live here with the other sidebar values.
"""

import customtkinter as ctk

# Sidebar background and the hover shade used on it (close button, checkboxes).
SIDEBAR_BG = "#95aec9"
SIDEBAR_HOVER = "#6c8a9e"

# Regular sidebar buttons and option menus.
SIDEBAR_BUTTON = "#4c6a8c"
SIDEBAR_BUTTON_HOVER = "#3b556f"
SIDEBAR_BUTTON_TEXT = "#fbfbfb"
SIDEBAR_MENU_ARROW = "#004566"
SIDEBAR_MENU_TEXT = "#ebebeb"

# Destructive buttons (delete cookies, uninstall).
DANGER = "#cc3b3b"
DANGER_HOVER = "#ff4c4c"

# Cookie section (ui/sidebar/view.py): The mode menu is on the left and the
# browser menu (browser mode only) is on the right, on the same row.
# Both must fit within the sidebar width minus 20 px padding, with a 6 px gap.
COOKIE_MODE_MENU_WIDTH = 160
COOKIE_BROWSER_MENU_WIDTH = 90


def sidebar_button(parent, **kwargs) -> ctk.CTkButton:
    options = dict(
        font=("Helvetica", 13),
        fg_color=SIDEBAR_BUTTON,
        hover_color=SIDEBAR_BUTTON_HOVER,
        text_color=SIDEBAR_BUTTON_TEXT,
        height=30,
    )
    options.update(kwargs)
    return ctk.CTkButton(parent, **options)


def sidebar_option_menu(parent, **kwargs) -> ctk.CTkOptionMenu:
    options = dict(
        font=("Helvetica", 13),
        fg_color=SIDEBAR_BUTTON,
        button_color=SIDEBAR_MENU_ARROW,
        text_color=SIDEBAR_MENU_TEXT,
        height=30,
    )
    options.update(kwargs)
    return ctk.CTkOptionMenu(parent, **options)


def sidebar_checkbox(parent, **kwargs) -> ctk.CTkCheckBox:
    options = dict(
        onvalue=True, offvalue=False,
        font=("Helvetica", 14),
        text_color="black",
        fg_color=SIDEBAR_BG,
        hover_color=SIDEBAR_HOVER,
        border_color="black",
        border_width=2,
        checkbox_width=20, checkbox_height=20,
        corner_radius=4,
        checkmark_color="black",
    )
    options.update(kwargs)
    return ctk.CTkCheckBox(parent, **options)
