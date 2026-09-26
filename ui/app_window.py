"""
Main window construction.

build_app_window() creates every widget of the main window and the
settings sidebar and returns them all as attributes of one object, for
main.py to unpack into its own module-level names — main.py's business
logic (add_to_queue, render_queue_list, toggle_theme, on_ytdlp_status,
etc.) was written against those bare names and keeps working unchanged.

This module owns none of the click-handling logic itself: every
command=... callback it wires up is supplied by the caller via
`callbacks` (an object with one attribute per callback, e.g.
callbacks.add_to_queue), since those functions live in main.py and need
things (state, other widgets, current_language) this module doesn't
have. The one thing NOT wired up here is the "Check for Updates" button
— its command depends on an UpdateChecker instance that itself needs
several of these widgets, so main.py constructs and wires that right
after calling this function.
"""

from types import SimpleNamespace

import customtkinter as ctk

from settings import load_setting, save_setting


def build_app_window(callbacks, app_version: str, app_icon: str,
                      sidebar_width: int, sidebar_x: int) -> SimpleNamespace:
    root = ctk.CTk()
    root.title(f"Video Downloader v{app_version}")
    root.geometry("800x600")
    root.iconbitmap(app_icon)
    root.protocol("WM_DELETE_WINDOW", callbacks.on_close_request)

    # Main frame
    frame = ctk.CTkFrame(root, fg_color="#ebebeb")
    frame.pack(pady=30, padx=30)

    # Quality label
    download_option_label = ctk.CTkLabel(frame, font=ctk.CTkFont(size=16))
    download_option_label.grid(row=0, column=0, padx=10, pady=5)

    # Quality dropdown
    option_var = ctk.StringVar(value="1080p ᴴᴰ")
    quality_options_menu = ctk.CTkOptionMenu(
        frame,
        variable=option_var,
        fg_color="#e0e0e0",
        text_color="#333333",
        button_color="#d0d0d0",
        button_hover_color="#c0c0c0",
    )
    quality_options_menu.grid(row=0, column=1, padx=10, pady=5)

    # URL label
    video_url_label = ctk.CTkLabel(frame, text="Video URL:", font=ctk.CTkFont(size=16))
    video_url_label.grid(row=0, column=2, padx=10, pady=5)

    # URL entry
    url_var = ctk.StringVar()
    url_var.trace_add("write", callbacks.url_changed)
    url_entry = ctk.CTkEntry(frame, width=300, textvariable=url_var)
    url_entry.grid(row=0, column=3, padx=10, pady=5)
    url_entry.bind("<Button-3>", lambda e: callbacks.show_entry_context_menu(e, url_entry))

    # Playlist checkbox (hidden until list= detected)
    frame.grid_rowconfigure(1, minsize=20)
    playlist_checkbox_var = ctk.BooleanVar()
    playlist_checkbox = ctk.CTkCheckBox(
        frame,
        #variable=playlist_checkbox_var,
        font=ctk.CTkFont(size=15),
        checkbox_height=20,
        checkbox_width=20,
        border_width=2,
        fg_color="#333333",
        hover_color="#cccccc",
        corner_radius=4,
    )
    #playlist_checkbox.grid(row=1, column=3, sticky="w", padx=10, pady=5)
    #playlist_checkbox.grid_remove()

    # Queue header + clear button (row 2, hidden until something is queued)
    queue_header_label = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=13, weight="bold"))
    queue_header_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")
    queue_header_label.grid_remove()

    clear_queue_button = ctk.CTkButton(
        frame,
        command=callbacks.clear_queue,
        width=100, height=24,
        font=("Helvetica", 13, "bold"),
        fg_color="#ebebeb", hover_color="#dddddd", text_color="#d9534f",
    )
    clear_queue_button.grid(row=2, column=2, columnspan=2, padx=10, pady=(1, 0), sticky="e")
    clear_queue_button.grid_remove()

    # Queue list (waiting items only — the active download shows in the progress area)
    queue_list_frame = ctk.CTkScrollableFrame(frame, width=440, height=160, fg_color="#f5f5f5")
    queue_list_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=(2, 10), sticky="ew")
    queue_list_frame.grid_remove()

    # Bottom action panel: fixed to the bottom with place().
    # Its contents use pack() among themselves.
    bottom_panel = ctk.CTkFrame(root, fg_color="transparent")
    bottom_panel.place(relx=0.5, rely=1.0, anchor="s", y=-15)

    # yt-dlp status message — shown on first run or during update checks.
    # Hidden otherwise. See on_ytdlp_status() in main.py.
    ytdlp_status_label = ctk.CTkLabel(
        bottom_panel, text="", font=("Helvetica", 14, "italic"), text_color="#888888",
    )
    ytdlp_status_label.pack(pady=(0, 5))
    ytdlp_status_label.pack_forget()

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

    # Action buttons: "Download" is always visible,
    # "➕ Add to Queue" is shown only while downloading.
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

    # Cancel button
    cancel_button = ctk.CTkButton(
        bottom_panel,
        command=callbacks.cancel_download,
        width=120,
        height=45,
        font=("Helvetica", 14, "bold"),
        fg_color="#ebebeb",
        hover_color="#dddddd",
        text_color="#d9534f",
        border_color="#d9534f",
        border_width=2,
        corner_radius=5,
    )
    cancel_button.pack(pady=0)
    cancel_button.pack_forget()

    # Progress bar
    progress_bar = ctk.CTkProgressBar(bottom_panel, orientation="horizontal", width=300, height=15)
    progress_bar.set(0)
    progress_bar.pack(pady=10)
    progress_bar.pack_forget()

    # Progress label
    progress_label = ctk.CTkLabel(bottom_panel, text="", font=("Helvetica", 13))
    progress_label.pack()
    progress_label.pack_forget()

    # Downloads folder button
    downloads_button = ctk.CTkButton(
        root,
        text="",
        command=callbacks.open_downloads_folder,
        width=50, height=50,
        fg_color="#dddddd",
        hover_color="#bbbbbb",
        text_color="black",
        corner_radius=8,
    )
    downloads_button.place(relx=0, rely=1, anchor="sw", x=10, y=-10)

    # Sidebar
    sidebar_frame = ctk.CTkFrame(root, width=sidebar_width, fg_color="#95aec9", corner_radius=0)
    sidebar_frame.place(x=sidebar_x, y=0, relheight=1)

    sidebar_content = ctk.CTkFrame(sidebar_frame, fg_color="#95aec9")
    sidebar_content.pack(padx=0, pady=0, anchor="nw", fill="both", expand=True)

    close_button = ctk.CTkButton(
        sidebar_frame,
        text="✕",
        font=("Helvetica", 19),
        fg_color="#95aec9",
        text_color="black",
        width=35, height=35,
        command=callbacks.toggle_sidebar,
        hover_color="#6c8a9e",
    )
    close_button.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

    # Menu (hamburger) button
    menu_button = ctk.CTkButton(
        root,
        text="☰",
        font=("Helvetica", 30, "bold"),
        fg_color="#ebebeb",
        text_color="#333333",
        width=50, height=50,
        command=callbacks.toggle_sidebar,
        hover_color="#d0d0d0",
    )
    menu_button.place(x=10, y=10)

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

    # Language selector
    language_options = ["De", "En", "Es", "Fr", "It", "Tr"]
    language_var = ctk.StringVar(value=language_options[0])
    language_menu = ctk.CTkOptionMenu(
        sidebar_content,
        variable=language_var,
        values=language_options,
        command=callbacks.change_language,
        width=70, height=30,
        font=("Helvetica", 13),
        fg_color="#4c6a8c",
        button_color="#004566",
        text_color="#ebebeb",
    )
    language_menu.place(relx=1.0, rely=1.0, anchor="se", x=-85, y=-10)

    # System notification checkbox
    system_notification_enabled = ctk.BooleanVar(value=load_setting("system_notification", True))
    system_notification_enabled.trace_add(
        "write",
        lambda *_: save_setting("system_notification", system_notification_enabled.get()),
    )
    system_notification_checkbox = ctk.CTkCheckBox(
        sidebar_content,
        variable=system_notification_enabled,
        onvalue=True, offvalue=False,
        font=("Helvetica", 14),
        text_color="black",
        fg_color="#95aec9",
        hover_color="#6c8a9e",
        border_color="black",
        border_width=2,
        checkbox_width=20, checkbox_height=20,
        corner_radius=4,
        checkmark_color="black",
    )
    system_notification_checkbox.pack(anchor="w", pady=(60, 20), padx=10, fill="x")

    # Start in dark mode checkbox
    dark_mode_enabled = ctk.BooleanVar(value=load_setting("start_in_dark_mode", False))
    dark_mode_enabled.trace_add(
        "write",
        lambda *_: save_setting("start_in_dark_mode", dark_mode_enabled.get()),
    )
    start_in_dark_mode_checkbox = ctk.CTkCheckBox(
        sidebar_content,
        variable=dark_mode_enabled,
        onvalue=True, offvalue=False,
        font=("Helvetica", 14),
        text_color="black",
        fg_color="#95aec9",
        hover_color="#6c8a9e",
        border_color="black",
        border_width=2,
        checkbox_width=20, checkbox_height=20,
        corner_radius=4,
        checkmark_color="black",
    )
    start_in_dark_mode_checkbox.pack(anchor="w", pady=10, padx=10, fill="x")

    # Save location picker
    save_location_button = ctk.CTkButton(
        sidebar_content,
        command=callbacks.choose_save_location,
        font=("Helvetica", 13),
        fg_color="#4c6a8c",
        hover_color="#3b556f",
        text_color="#fbfbfb",
        height=30,
    )
    save_location_button.pack(anchor="w", pady=(10, 0), padx=10, fill="x")

    save_location_value_label = ctk.CTkLabel(
        sidebar_content,
        text="",
        font=("Helvetica", 11),
        text_color="#333333",
    )
    save_location_value_label.pack(anchor="w", pady=(2, 10), padx=10, fill="x")
    # NOTE: the initial update_save_location_label() call that used to happen
    # right here now happens in main.py, right after unpacking this
    # function's return value — that function is defined in main.py and
    # needs save_location_value_label to already be one of its own globals.

    # Check for Updates button
    check_updates_button = ctk.CTkButton(
        sidebar_content,
        font=("Helvetica", 13),
        fg_color="#4c6a8c",
        hover_color="#3b556f",
        text_color="#fbfbfb",
        height=30,
    )
    check_updates_button.pack(anchor="w", pady=(0, 10), padx=10, fill="x")
    # command= is wired up by main.py once its UpdateChecker exists (see
    # this module's docstring).

    # Preview notification button
    preview_notification_button = ctk.CTkButton(
        sidebar_content,
        font=("Helvetica", 13),
        command=callbacks.preview_notification,
        fg_color="#4c6a8c",
        hover_color="#3b556f",
        text_color="#fbfbfb",
        width=35, height=35,
    )
    preview_notification_button.place(x=10, y=-70, relx=0, rely=1, anchor="sw")

    # Uninstall button
    uninstall_button = ctk.CTkButton(
        sidebar_content,
        command=callbacks.uninstall_app,
        font=("Helvetica", 13),
        width=70, height=30,
        fg_color="#cc3b3b",
        hover_color="#ff4c4c",
        text_color="#fbfbfb",
    )
    uninstall_button.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)

    return SimpleNamespace(**locals())
