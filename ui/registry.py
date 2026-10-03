"""
Single place where each widget declares what the app needs to do with it.

build_app_window() registers each widget right where it is created, and
main.py loops over the registry in change_language() (texts),
apply_button_icons() (icons) and toggle_theme() (themed). Adding a button
therefore only means one registry.add(...) call next to its constructor.

    registry.add(
        export_button,
        text="export_button",                  # key in languages.py (every language)
        icon=("export.png", "#fbfbfb"),        # (file in icons/, color[, (w, h)])
        theme="export_button",                 # key in ui/theme.py THEMES (light AND dark)
    )

All three arguments are optional — pass only what applies to the widget.
"""


class UiRegistry:
    def __init__(self):
        # widget -> language key; applied by App.change_language()
        self.texts: dict = {}
        # widget -> (icon filename, color) or (icon filename, color, (w, h));
        # applied by App.apply_button_icons()
        self.icons: dict = {}
        # THEMES key -> widget; passed to ThemeManager.toggle() by App.toggle_theme()
        self.themed: dict = {}

    def add(self, widget, *, text: str | None = None, icon: tuple | None = None,
            theme: str | None = None):
        """Registers `widget` and returns it, so this can also wrap a
        constructor call."""
        if text is not None:
            self.texts[widget] = text
        if icon is not None:
            self.icons[widget] = icon
        if theme is not None:
            if theme in self.themed:
                raise ValueError(f"theme key {theme!r} is already registered")
            self.themed[theme] = widget
        return widget