"""
Application logic that has no widgets of its own: shared state, the download
queue, the quality options, the controller that drives each download, and the
error classification that several packages use.

    app_state.py            AppState: status flags shared by App,
                            DownloadController and the update/close logic
                            (cancel, pause, closing, current language, ...).
    download_queue.py       DownloadQueue: pure queue state (the waiting items
                            plus the one in flight). No GUI import, so it can
                            be exercised in a plain script or test.
    quality_options.py      QUALITY_OPTIONS, the one list the dropdown, the
                            resolution lookup and the mp4/mp3 tags are derived
                            from, plus the label / dropdown display helpers.
    download_controller.py  DownloadController: decides when the next queue
                            item starts, feeds progress into the progress bar
                            and reacts to a download finishing, failing or
                            being cancelled. Its widgets are attached after
                            construction via bind_widgets().
    error_classifier.py     The exceptions the download engine raises and the
                            classify_* functions that turn yt-dlp / ffmpeg
                            failures into translated, user-facing messages.
                            Lives here because both downloading/ and ytdlp/
                            import it.

Nothing is imported here on purpose, and that matters beyond tidiness:
error_classifier.py must stay importable without loading the rest of this
package. `ytdlp` imports it, while download_controller.py imports
`downloading`, which imports `ytdlp`; importing DownloadController from this
file would close that circle and make `import ytdlp` fail. Import the module
you need instead, e.g. `from core.error_classifier import DenoNotFoundError`.
"""