"""
Main window construction.

build_app_window() creates the root window, the main panel (URL row + queue
list), the bottom action panel and the toast label, builds the settings
sidebar through ui/sidebar/view.py, and returns every widget as attributes of one
flat SimpleNamespace, which main.py's App keeps as self.ui
(self.ui.download_button, ...).

The file is split into one builder per area, each returning the widgets it
created as a SimpleNamespace:
    _build_main_panel()    - quality menu, URL entry, playlist checkbox, queue list
    _build_bottom_panel()  - status/update/retry buttons, Download/Pause/Queue,
                             Cancel, progress bar and label, downloads folder button
    ui/sidebar/view.py     - build_sidebar(): the settings sidebar, incl. cookies

Click handling is not implemented here: every command=... callback is
supplied by the caller via `callbacks` (one attribute per callback, e.g.
callbacks.add_to_queue). Three commands are wired up by main.py afterwards,
because they need an UpdateChecker, which itself needs several of these
widgets: the "Check for Updates" button, update_cancel_button and
update_install_button.

Every widget that needs a translated label, a button icon and/or theme
colors is registered where it is created (registry.add(...), see
ui/registry.py); the registry is returned as self.ui.registry.

Every widget starts in light mode, so its colors come from ui/theme.py's
THEMES["light"] (aliased as _LIGHT), the same dict toggle_theme() applies
later. Colors that don't change between themes (e.g. the red text of the
cancel/clear buttons, some hover colors) are hardcoded here and marked
with a comment.

Creation order matters: widgets placed on root with place() stack in the
order they are created, so the builders are called main panel -> bottom
panel -> sidebar -> toast (the toast must stay last to sit above the sidebar).
"""

from types import SimpleNamespace

import customtkinter as ctk

from ui.registry import UiRegistry
from ui.sidebar.view import build_sidebar
from ui.theme import THEMES

_LIGHT = THEMES["light"]

# Window title = WINDOW_TITLE_PREFIX + app version. main.py's single-instance
# check finds an already-running copy by this same prefix, so never retype it.
WINDOW_TITLE_PREFIX = "Video Downloader v"


def build_app_window(callbacks, app_version: str, app_icon: str,
                      sidebar_width: int, sidebar_x: int) -> SimpleNamespace:
    registry = UiRegistry()

    root = ctk.CTk()
    root.configure(fg_color=_LIGHT["root"]["fg_color"])
    root.title(f"{WINDOW_TITLE_PREFIX}{app_version}")
    root.geometry("800x600")
    root.iconbitmap(app_icon)
    root.protocol("WM_DELETE_WINDOW", callbacks.on_close_request)
    registry.add(root, theme="root")

    main_widgets = _build_main_panel(root, registry, callbacks)
    bottom_widgets = _build_bottom_panel(root, registry, callbacks)
    sidebar_widgets = build_sidebar(root, registry, callbacks, sidebar_width, sidebar_x)

    # Toast (brief bottom-right notice, e.g. "download cancelled"). Created
    # hidden; shown/hidden via place()/place_forget() by ToastNotifier
    # (ui/notifications.py). Created last, so it stacks above every other
    # widget placed on root, including the sidebar.
    toast_label = ctk.CTkLabel(
        root,
        text="",
        font=ctk.CTkFont(family="Helvetica", size=13, weight="bold"),
        fg_color="#d9534f",
        text_color="#ebebeb",
        corner_radius=5,
        padx=14,
        pady=14,
    )

    return SimpleNamespace(
        registry=registry,
        root=root,
        **vars(main_widgets),
        **vars(bottom_widgets),
        **vars(sidebar_widgets),
        toast_label=toast_label,
    )


def _build_main_panel(root, registry, callbacks) -> SimpleNamespace:
    """Main frame: quality menu, URL entry, playlist checkbox (not shown yet)
    and the queue header/clear button/list."""
    # Main frame
    frame = ctk.CTkFrame(root, fg_color=_LIGHT["frame"]["fg_color"])
    frame.pack(pady=30, padx=30)
    registry.add(frame, theme="frame")

    # Quality label
    download_option_label = ctk.CTkLabel(
        frame, font=ctk.CTkFont(size=16), text_color=_LIGHT["download_option_label"]["text_color"],
    )
    download_option_label.grid(row=0, column=0, padx=10, pady=5)
    registry.add(download_option_label, text="download_option_label", theme="download_option_label")

    # Quality dropdown
    option_var = ctk.StringVar(value="1080p ᴴᴰ")
    quality_options_menu = ctk.CTkOptionMenu(
        frame,
        variable=option_var,
        fg_color=_LIGHT["quality_options_menu"]["fg_color"],
        text_color=_LIGHT["quality_options_menu"]["text_color"],
        button_color=_LIGHT["quality_options_menu"]["button_color"],
        button_hover_color=_LIGHT["quality_options_menu"]["button_hover_color"],
    )
    quality_options_menu.grid(row=0, column=1, padx=10, pady=5)
    registry.add(quality_options_menu, theme="quality_options_menu")

    # URL label
    video_url_label = ctk.CTkLabel(
        frame, text="Video URL:", font=ctk.CTkFont(size=16),
        text_color=_LIGHT["video_url_label"]["text_color"],
    )
    video_url_label.grid(row=0, column=2, padx=10, pady=5)
    registry.add(video_url_label, theme="video_url_label")

    # URL entry
    url_var = ctk.StringVar()
    url_var.trace_add("write", callbacks.url_changed)
    url_entry = ctk.CTkEntry(
        frame, width=300, textvariable=url_var,
        fg_color=_LIGHT["url_entry"]["fg_color"],
        text_color=_LIGHT["url_entry"]["text_color"],
    )
    url_entry.grid(row=0, column=3, padx=10, pady=5)
    registry.add(url_entry, theme="url_entry")
    url_entry.bind("<Button-3>", lambda e: callbacks.show_entry_context_menu(e, url_entry))

    # Playlist checkbox — playlist support is pending, so it is created and
    # registered (text/theme) but never gridded for now. The commented-out
    # variable=/grid() lines below are what to enable with it; see
    # App.url_changed() in main.py.
    frame.grid_rowconfigure(1, minsize=20)
    playlist_checkbox_var = ctk.BooleanVar()
    playlist_checkbox = ctk.CTkCheckBox(
        frame,
        #variable=playlist_checkbox_var,
        font=ctk.CTkFont(size=15),
        checkbox_height=20,
        checkbox_width=20,
        border_width=2,
        fg_color=_LIGHT["playlist_checkbox"]["fg_color"],
        hover_color="#cccccc",  # not part of the light/dark theme, stays fixed
        corner_radius=4,
        text_color=_LIGHT["playlist_checkbox"]["text_color"],
        bg_color=_LIGHT["playlist_checkbox"]["bg_color"],
        border_color=_LIGHT["playlist_checkbox"]["border_color"],
        checkmark_color=_LIGHT["playlist_checkbox"]["checkmark_color"],
    )
    #playlist_checkbox.grid(row=1, column=3, sticky="w", padx=10, pady=5)
    #playlist_checkbox.grid_remove()
    registry.add(playlist_checkbox, text="playlist_checkbox", theme="playlist_checkbox")

    # Queue header + clear button (row 2, hidden until something is queued)
    queue_header_label = ctk.CTkLabel(
        frame, text="", font=ctk.CTkFont(size=13, weight="bold"),
        text_color=_LIGHT["queue_header_label"]["text_color"],
    )
    queue_header_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")
    queue_header_label.grid_remove()
    registry.add(queue_header_label, theme="queue_header_label")

    clear_queue_button = ctk.CTkButton(
        frame,
        command=callbacks.clear_queue,
        width=100, height=24,
        font=("Helvetica", 13, "bold"),
        fg_color=_LIGHT["clear_queue_button"]["fg_color"],
        hover_color=_LIGHT["clear_queue_button"]["hover_color"],
        text_color="#d9534f",  # not part of the light/dark theme, stays fixed
    )
    clear_queue_button.grid(row=2, column=2, columnspan=2, padx=10, pady=(1, 0), sticky="e")
    clear_queue_button.grid_remove()
    registry.add(clear_queue_button, text="clear_queue_button", icon=("clear.png", "#d9534f"), theme="clear_queue_button")

    # Queue list (waiting items only — the active download shows in the progress area)
    queue_list_frame = ctk.CTkScrollableFrame(
        frame, width=440, height=160, fg_color=_LIGHT["queue_list_frame"]["fg_color"],
    )
    queue_list_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=(2, 10), sticky="ew")
    queue_list_frame.grid_remove()
    registry.add(queue_list_frame, theme="queue_list_frame")

    return SimpleNamespace(
        frame=frame,
        download_option_label=download_option_label,
        option_var=option_var,
        quality_options_menu=quality_options_menu,
        video_url_label=video_url_label,
        url_var=url_var,
        url_entry=url_entry,
        playlist_checkbox_var=playlist_checkbox_var,
        playlist_checkbox=playlist_checkbox,
        queue_header_label=queue_header_label,
        clear_queue_button=clear_queue_button,
        queue_list_frame=queue_list_frame,
    )


def _build_bottom_panel(root, registry, callbacks) -> SimpleNamespace:
    """Bottom action panel (status/update/retry buttons, Download/Pause/Queue,
    Cancel, progress) plus the downloads folder button in the corner."""
    # Bottom action panel: fixed to the bottom with place().
    # Its contents use pack() among themselves.
    bottom_panel = ctk.CTkFrame(root, fg_color="transparent")
    bottom_panel.place(relx=0.5, rely=1.0, anchor="s", y=-15)

    # yt-dlp status message — shown on first run or during update checks,
    # hidden otherwise. See on_ytdlp_status() in main.py.
    ytdlp_status_label = ctk.CTkLabel(
        bottom_panel, text="", font=("Helvetica", 14, "italic"), text_color="#888888",
    )
    ytdlp_status_label.pack(pady=(0, 5))
    ytdlp_status_label.pack_forget()

    # Buttons for the app-update installer download (see updater.py). Both sit
    # side by side in update_buttons_frame, which UpdateChecker packs just
    # below ytdlp_status_label (which shows the "%" progress / ready message).
    # Separate from `cancel_button` below, which belongs to video downloads.
    # command= for both is wired up by main.py; their texts are set by
    # change_language() and refreshed by UpdateChecker when shown.
    update_buttons_frame = ctk.CTkFrame(bottom_panel, fg_color="transparent")
    update_buttons_frame.pack(pady=(0, 5))
    update_buttons_frame.pack_forget()

    update_cancel_button = ctk.CTkButton(
        update_buttons_frame,
        width=120,
        height=32,
        font=("Helvetica", 13, "bold"),
        fg_color=_LIGHT["cancel_button"]["fg_color"],
        hover_color=_LIGHT["cancel_button"]["hover_color"],
        text_color="#d9534f",       # not part of the light/dark theme, stays fixed
        border_color="#d9534f",     # same
        border_width=2,
        corner_radius=5,
    )
    update_cancel_button.pack(side="left", padx=5)
    update_cancel_button.pack_forget()
    registry.add(update_cancel_button, text="cancel_button", icon=("cancel.png", "#d9534f"))

    # Shown next to update_cancel_button once the installer is fully
    # downloaded; pressing it starts the installation. Fixed colors: it is not
    # part of the light/dark theme, so it is not registered with theme=.
    update_install_button = ctk.CTkButton(
        update_buttons_frame,
        width=200,
        height=32,
        font=("Helvetica", 13, "bold"),
        fg_color="#5cb85c",
        hover_color="#449d44",
        text_color="#fbfbfb",
        corner_radius=5,
    )
    update_install_button.pack(side="left", padx=5)
    update_install_button.pack_forget()
    registry.add(update_install_button, text="update_install_button", icon=("install.png", "#fbfbfb"))
    # Shown only if the first-run yt-dlp.exe download fails (e.g. no internet).
    # Lets the user retry without having to restart the whole app.
    ytdlp_retry_button = ctk.CTkButton(
        bottom_panel,
        command=callbacks.retry_ytdlp_setup,
        width=140,
        height=32,
        font=("Helvetica", 13),
        fg_color="#565656",
        hover_color="#787878",
        text_color="#fbfbfb",
        corner_radius=5,
    )
    ytdlp_retry_button.pack(pady=(0, 5))
    ytdlp_retry_button.pack_forget()
    registry.add(ytdlp_retry_button, text="ytdlp_retry_button", icon=("refresh.png", "#fbfbfb"))

    # Action buttons: idle -> only "Download". While a download is active,
    # DownloadController hides "Download" and shows "Pause" and "Add to Queue"
    # in its place (see _show_downloading_ui / _show_idle_ui).
    action_buttons_frame = ctk.CTkFrame(bottom_panel, fg_color="transparent")
    action_buttons_frame.pack(pady=(0, 10))

    download_button = ctk.CTkButton(
        action_buttons_frame,
        command=callbacks.add_to_queue,
        width=120,
        height=45,
        font=("Helvetica", 14, "bold"),
        fg_color="#458bc6",
        hover_color="#1f567a",
        text_color="#fbfbfb",
        corner_radius=5,
        state="disabled",  # re-enabled once on_ytdlp_status reports "ready"
    )
    download_button.pack(side="left", padx=5)
    registry.add(download_button, text="download_button", icon=("download.png", "#fbfbfb"))

    # Shown in place of "download_button" while a download is active.
    pause_button = ctk.CTkButton(
        action_buttons_frame,
        command=callbacks.pause_download,
        width=120,
        height=45,
        font=("Helvetica", 14, "bold"),
        fg_color="#e0a12e",
        hover_color="#b87f1f",
        text_color="#fbfbfb",
        corner_radius=5,
    )
    pause_button.pack(side="left", padx=5)
    pause_button.pack_forget()
    # icon is swapped between pause/resume at runtime (DownloadController), so only text is registered
    registry.add(pause_button, text="pause_button")

    queue_add_button = ctk.CTkButton(
        action_buttons_frame,
        command=callbacks.add_to_queue,
        width=150,
        height=45,
        font=("Helvetica", 14, "bold"),
        fg_color="#5cb85c",
        hover_color="#449d44",
        text_color="#fbfbfb",
        corner_radius=5,
    )
    queue_add_button.pack(side="left", padx=5)
    queue_add_button.pack_forget()
    registry.add(queue_add_button, text="queue_add_button", icon=("add.png", "#fbfbfb"))

    # Cancel button
    cancel_button = ctk.CTkButton(
        bottom_panel,
        command=callbacks.cancel_download,
        width=120,
        height=45,
        font=("Helvetica", 14, "bold"),
        fg_color=_LIGHT["cancel_button"]["fg_color"],
        hover_color=_LIGHT["cancel_button"]["hover_color"],
        text_color="#d9534f",       # not part of the light/dark theme, stays fixed
        border_color="#d9534f",     # same
        border_width=2,
        corner_radius=5,
    )
    cancel_button.pack(pady=0)
    cancel_button.pack_forget()
    registry.add(cancel_button, text="cancel_button", icon=("cancel.png", "#d9534f"), theme="cancel_button")

    # Progress bar
    progress_bar = ctk.CTkProgressBar(bottom_panel, orientation="horizontal", width=300, height=15)
    progress_bar.set(0)
    progress_bar.pack(pady=10)
    progress_bar.pack_forget()

    # Progress label
    progress_label = ctk.CTkLabel(
        bottom_panel, text="", font=("Helvetica", 13),
        text_color=_LIGHT["progress_label"]["text_color"],
        bg_color=_LIGHT["progress_label"]["bg_color"],
    )
    progress_label.pack()
    progress_label.pack_forget()
    registry.add(progress_label, theme="progress_label")

    # Downloads folder button
    downloads_button = ctk.CTkButton(
        root,
        text="",
        command=callbacks.open_downloads_folder,
        width=50, height=50,
        fg_color=_LIGHT["downloads_button"]["fg_color"],
        hover_color="#bbbbbb",  # not part of the light/dark theme, stays fixed
        text_color="black",
        corner_radius=8,
    )
    downloads_button.place(relx=0, rely=1, anchor="sw", x=10, y=-10)
    registry.add(downloads_button, icon=("folder.png", "black", (30, 30)), theme="downloads_button")

    return SimpleNamespace(
        bottom_panel=bottom_panel,
        ytdlp_status_label=ytdlp_status_label,
        update_buttons_frame=update_buttons_frame,
        update_cancel_button=update_cancel_button,
        update_install_button=update_install_button,
        ytdlp_retry_button=ytdlp_retry_button,
        action_buttons_frame=action_buttons_frame,
        download_button=download_button,
        pause_button=pause_button,
        queue_add_button=queue_add_button,
        cancel_button=cancel_button,
        progress_bar=progress_bar,
        progress_label=progress_label,
        downloads_button=downloads_button,
    )
