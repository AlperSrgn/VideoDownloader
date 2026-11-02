"""
Talking to the operating system and keeping the app itself up to date: the
Windows process/window helpers and the self-update.

Where to look (one concern per module):

  process_manager.py  Windows process/window helpers via ctypes: the
                      kill-on-close Job Object for yt-dlp/ffmpeg
                      (attach_to_job), suspend/resume of ffmpeg
                      (apply_pause_state, resume_if_suspended), terminating a
                      process together with its children
                      (terminate_process_tree), the line-reader thread helper
                      (enqueue_lines), sleep prevention while downloading
                      (set_keep_awake) and the single-instance mutex with
                      focusing the first copy's window
                      (acquire_single_instance, focus_existing_window).
                      NO_WINDOW is the Popen flag that hides console windows.
                      No-ops outside Windows.
  updater.py          UpdateChecker and APP_VERSION: compares the installed
                      version with the latest GitHub release, downloads and
                      validates the installer, and launches it when the user
                      presses the install button. Its widgets are passed in
                      explicitly once they exist. Uses
                      core/error_classifier.py for local file errors.

Not in here: the download engine that uses these helpers (downloading/), the
window-close and uninstall logic that cancels a running update download
(core/app_lifecycle.py) and the translated error messages
(core/error_classifier.py).

Other code imports from this package, not from the modules above:

    from system import attach_to_job, set_keep_awake, UpdateChecker

The names are loaded on first use (see __getattr__) instead of being imported
here, so importing this package has no side effects: process_manager.py
creates its Job Object as soon as it is imported, and updater.py pulls in
tkinter. Neither is loaded until a name from it is actually used.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # for editors and type checkers only; not executed
    from system.process_manager import (
        NO_WINDOW,
        acquire_single_instance,
        apply_pause_state,
        attach_to_job,
        enqueue_lines,
        focus_existing_window,
        resume_if_suspended,
        set_keep_awake,
        terminate_process_tree,
    )
    from system.updater import APP_VERSION, UpdateChecker

__all__ = [
    "APP_VERSION",
    "NO_WINDOW",
    "UpdateChecker",
    "acquire_single_instance",
    "apply_pause_state",
    "attach_to_job",
    "enqueue_lines",
    "focus_existing_window",
    "resume_if_suspended",
    "set_keep_awake",
    "terminate_process_tree",
]

_LAZY_EXPORTS = {
    "NO_WINDOW": "system.process_manager",
    "acquire_single_instance": "system.process_manager",
    "apply_pause_state": "system.process_manager",
    "attach_to_job": "system.process_manager",
    "enqueue_lines": "system.process_manager",
    "focus_existing_window": "system.process_manager",
    "resume_if_suspended": "system.process_manager",
    "set_keep_awake": "system.process_manager",
    "terminate_process_tree": "system.process_manager",
    "APP_VERSION": "system.updater",
    "UpdateChecker": "system.updater",
}


def __getattr__(name):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value  # cache so __getattr__ runs once per name
    return value