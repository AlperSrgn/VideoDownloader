"""
Windows process/window management helpers.

Two related concerns live here:
  - Managing yt-dlp/ffmpeg child processes: keeping them tied to this
    app's lifetime (Job Object), pausing/resuming them, and terminating
    them together with their own children.
  - Single-instance enforcement: claiming a named mutex on startup and,
    if another copy already holds it, finding and focusing that copy's
    window instead of opening a second one.

Both are generic "talk to the Windows API via ctypes" plumbing that
doesn't belong to any one feature, which is why they're split out of
downloader.py / main.py into their own module.
"""

import logging
import os
import subprocess

import psutil

logger = logging.getLogger(__name__)

# Flag passed to subprocess.Popen/run so launched processes (yt-dlp.exe,
# ffmpeg) don't flash a console window on Windows. No-op elsewhere.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# ---------------------------------------------------------------------------
# Windows Job Object: kill child processes when the app exits
# ---------------------------------------------------------------------------
# ffmpeg / yt-dlp are child processes. On Windows they do NOT die when the
# parent dies (window X, crash, Task Manager kill). They would keep running
# and keep the temp files locked. Every process we launch is added to a job
# with KILL_ON_JOB_CLOSE, so Windows itself kills them when this app's
# process ends, however it ends.
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in (
            "ReadOps", "WriteOps", "OtherOps",
            "ReadBytes", "WriteBytes", "OtherBytes")]

    class _EXT_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    # Also used by the single-instance mutex below.
    _k32.CreateMutexW.restype = wintypes.HANDLE
    _k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    # Used only by set_keep_awake() below.
    _k32.SetThreadExecutionState.restype = wintypes.DWORD
    _k32.SetThreadExecutionState.argtypes = [wintypes.DWORD]

    # Used only by focus_existing_window() below.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]


def _create_kill_on_close_job():
    """Returns a job handle, or None if it can't be created (non-Windows or
    API failure). The app keeps working without it, just without the
    kill-on-exit safety net."""
    if os.name != "nt":
        return None
    try:
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _EXT_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        ok = _k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        return job if ok else None
    except Exception as e:
        logger.debug("Could not create job object: %s", e)
        return None


_JOB = _create_kill_on_close_job()  # must stay alive for the whole app lifetime


def attach_to_job(process: subprocess.Popen) -> None:
    """Adds `process` to the kill-on-close job. Best-effort, never raises."""
    if _JOB is None:
        return
    try:
        if not _k32.AssignProcessToJobObject(_JOB, int(process._handle)):
            logger.debug("Could not assign pid %s to job object", process.pid)
    except Exception as e:
        logger.debug("Job assign failed for pid %s: %s", process.pid, e)


def apply_pause_state(process: subprocess.Popen, on_pause_check, suspended: bool) -> bool:
    """Suspends or resumes `process` based on on_pause_check(), and returns
    the updated suspended state.

    Used by both the yt-dlp download loop and the ffmpeg merge loop, so
    pausing genuinely stops network/CPU usage instead of just freezing the
    progress bar. Callers reset their own "no output" timer while this
    returns True, so a pause is never mistaken for a stall.
    """
    if on_pause_check is None:
        return False

    try:
        want_paused = on_pause_check()
    except Exception as e:
        logger.debug("on_pause_check() raised, treating as not paused: %s", e)
        want_paused = False

    if want_paused and not suspended:
        try:
            psutil.Process(process.pid).suspend()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.debug("Could not suspend process %s: %s", process.pid, e)
            return False
        return True

    if not want_paused and suspended:
        try:
            psutil.Process(process.pid).resume()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.debug("Could not resume process %s: %s", process.pid, e)
        return False

    return suspended


def enqueue_lines(pipe, line_queue) -> None:
    """Runs in the background, pushing `pipe` lines to `line_queue` and adding
    None at the end. This allows the main loop to use a timeout; `readline()`
    has no timeout support, and Windows pipes can't be used with `select()`.

    Generic pipe-reading with no download-specific logic, used by
    downloader.py's yt-dlp download loop and its ffmpeg merge loop alike —
    moved here from downloader.py since it's process/IO plumbing rather
    than anything specific to a download.
    """
    try:
        for line in pipe:
            line_queue.put(line)
    finally:
        line_queue.put(None)


def resume_if_suspended(process: subprocess.Popen, suspended: bool) -> None:
    """Best-effort resume before terminating a process that may currently be
    suspended — a suspended process can't process its own termination signal
    cleanly on Windows. Used right before cancelling a paused download/merge."""
    if not suspended:
        return
    try:
        psutil.Process(process.pid).resume()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def terminate_process_tree(process: subprocess.Popen) -> None:
    """Terminates `process` together with its child processes.

    yt-dlp.exe is a PyInstaller build: the process we launch can be just a
    launcher, with the real yt-dlp running as its child. Terminating only the
    parent leaves the child alive and still holding the .part file open, so
    the temp-file cleanup can't delete it. Children are collected first
    because once the parent is gone they can no longer be found through it.
    """
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.Error:
        children = []
    process.terminate()
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    _, alive = psutil.wait_procs(children, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass


# ---------------------------------------------------------------------------
# Sleep prevention
# ---------------------------------------------------------------------------
# Windows may put the PC to sleep when the idle timeout expires,
# even during a long download, because network activity isn't considered user input.
# SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) prevents idle sleep.
# ES_DISPLAY_REQUIRED is not used, so the screen can still turn off.
#
# The state is tied to the calling thread and is cleared automatically when
# the thread or process ends. It does not prevent manual sleep, lid-close sleep,
# or sleep caused by critically low battery.


_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def set_keep_awake(enabled: bool) -> None:
    """Blocks (True) or re-allows (False) idle sleep. Best-effort, never
    raises, no-op outside Windows. Safe to call repeatedly with the same
    value. Call it only from the main (Tk) thread so set and clear always
    happen on the same thread."""
    if os.name != "nt":
        return
    try:
        flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if enabled else 0)
        if not _k32.SetThreadExecutionState(flags):
            logger.debug("SetThreadExecutionState(%s) failed", hex(flags))
    except Exception as e:
        logger.debug("Could not change keep-awake state: %s", e)


# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------
# The app shares config.json, the save folder, the startup temp-file sweep
# and the yt-dlp binary, so a second copy would interfere with the first.
# acquire_single_instance() claims a named mutex; if another copy already
# holds it, focus_existing_window() brings that copy's window to the front
# instead of opening a second one.

_single_instance_handle = None  # must stay alive for the whole process lifetime


def acquire_single_instance(mutex_name: str) -> bool:
    """True if this is the first copy holding `mutex_name`. Also True when
    the check can't be done (non-Windows or API failure) so the app never
    refuses to start because of it."""
    global _single_instance_handle
    if os.name != "nt":
        return True
    try:
        handle = _k32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            _k32.CloseHandle(handle)
            return False
        _single_instance_handle = handle
        return True
    except Exception:
        return True


def focus_existing_window(title_prefix: str) -> None:
    """Best-effort: restore and focus the first copy's window, identified by
    its title starting with `title_prefix`."""
    if os.name != "nt":
        return
    try:
        found = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _check(hwnd, _lparam):
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value.startswith(title_prefix):
                    found.append(hwnd)
                    return False  # stop enumerating
            return True

        _user32.EnumWindows(enum_proc(_check), 0)
        if found:
            if _user32.IsIconic(found[0]):
                _user32.ShowWindow(found[0], 9)  # SW_RESTORE
            _user32.SetForegroundWindow(found[0])
    except Exception as e:
        logger.debug("Could not focus existing window: %s", e)