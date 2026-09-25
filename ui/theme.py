"""
Theme definitions (light/dark) for the main window's widgets.

Pure data — no widget references, no logic. Each top-level key ("dark",
"light") maps widget-role names (matched against a widget_map built in
main.py) to the CTk keyword arguments applied when that theme is active.
"""

THEMES = {
    "dark": {
        "root":                {"fg_color": "#333333"},
        "frame":               {"fg_color": "#333333"},
        "video_url_label":     {"text_color": "#ebebeb"},
        "download_option_label": {"text_color": "#ebebeb"},
        "light_dark":          {"text": ""},
        "light_dark_icon":     "sun.png",   # shown in dark mode — hints "tap for light"
        "downloads_button":    {"fg_color": "#565656"},
        "menu_button":         {"fg_color": "#333333", "text_color": "#d0d0d0", "hover_color": "#565656"},
        "progress_label":      {"text_color": "#ebebeb", "bg_color": "#333333"},
        "cancel_button":       {"fg_color": "#333333", "hover_color": "#565656"},
        "url_entry":           {"fg_color": "#565656", "text_color": "#ebebeb"},
        "playlist_checkbox":   {
            "text_color": "#ebebeb", "bg_color": "#333333",
            "border_color": "#ebebeb", "fg_color": "#ebebeb", "checkmark_color": "#333333"
        },
        "quality_options_menu": {
            "fg_color": "#565656", "text_color": "#ebebeb",
            "button_color": "#444444", "button_hover_color": "#666666"
        },
        "queue_header_label":  {"text_color": "#ebebeb"},
        "queue_list_frame":    {"fg_color": "#3d3d3d"},
        "queue_item_label":    {"text_color": "#ebebeb"},
        "clear_queue_button":  {"fg_color": "#333333", "hover_color": "#565656"},
    },
    "light": {
        "root":                {"fg_color": "#ebebeb"},
        "frame":               {"fg_color": "#ebebeb"},
        "video_url_label":     {"text_color": "#333333"},
        "download_option_label": {"text_color": "#333333"},
        "light_dark":          {"text": ""},
        "light_dark_icon":     "moon.png",   # shown in light mode — hints "tap for dark"
        "downloads_button":    {"fg_color": "#dddddd"},
        "menu_button":         {"fg_color": "#ebebeb", "text_color": "#333333", "hover_color": "#d0d0d0"},
        "progress_label":      {"text_color": "#333333", "bg_color": "#ebebeb"},
        "cancel_button":       {"fg_color": "#ebebeb", "hover_color": "#dddddd"},
        "url_entry":           {"fg_color": "#ffffff", "text_color": "#333333"},
        "playlist_checkbox":   {
            "text_color": "#333333", "bg_color": "#ebebeb",
            "border_color": "#333333", "fg_color": "#333333", "checkmark_color": "#ebebeb"
        },
        "quality_options_menu": {
            "fg_color": "#e0e0e0", "text_color": "#333333",
            "button_color": "#d0d0d0", "button_hover_color": "#c0c0c0"
        },
        "queue_header_label":  {"text_color": "#333333"},
        "queue_list_frame":    {"fg_color": "#f5f5f5"},
        "queue_item_label":    {"text_color": "#333333"},
        "clear_queue_button":  {"fg_color": "#ebebeb", "hover_color": "#dddddd"},
    },
}


class ThemeManager:
    """Tracks which theme ("light"/"dark") is active and which text color
    the queue list should currently use, and applies THEMES' style dict to
    a widget map when toggled.

    Has no ctk/tkinter import of its own — the widgets it styles are built
    and owned by main.py, so toggle() takes the current widget_map (role
    name -> widget) and an icon factory as arguments rather than holding
    widget references itself.
    """

    def __init__(self, start_dark: bool = False):
        self.dark_mode = start_dark
        self.queue_item_text_color = THEMES["light"]["queue_item_label"]["text_color"]

    def toggle(self, widget_map: dict, make_icon) -> None:
        """Applies the opposite theme to every widget in widget_map, updates
        dark_mode and queue_item_text_color, and sets the light/dark
        button's icon via make_icon(filename, color, size).

        Does NOT re-render the queue list itself — the caller (main.py)
        still owns that, since it involves widgets and state (the queue
        contents) this module knows nothing about.
        """
        theme_key = "dark" if not self.dark_mode else "light"
        theme = THEMES[theme_key]

        for key, widget in widget_map.items():
            widget.configure(**theme[key])

        icon = make_icon(theme["light_dark_icon"], "#fbfbfb", (24, 24))
        if icon is not None:
            widget_map["light_dark"].configure(image=icon)

        self.queue_item_text_color = theme["queue_item_label"]["text_color"]
        self.dark_mode = not self.dark_mode