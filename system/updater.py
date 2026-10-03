"""
App self-update checking: compares the installed version against the
latest GitHub release, and offers to download/launch the installer.

UpdateChecker only needs a handful of UI widgets, passed in explicitly
once they exist.
"""

import http.client
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
from tkinter import TclError, messagebox

from downloading.error_classifier import classify_generic_exception

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App version & "Check for Updates"
# ---------------------------------------------------------------------------
# Bump this on every release — must match the Inno Setup AppVersion so the
# comparison against GitHub's latest release tag is meaningful.
APP_VERSION = "3.9.0"

GITHUB_REPO = "AlperSrgn/VideoDownloader"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXPECTED_INSTALLER_NAME = "VideoDownloaderSetup.exe"

_USER_AGENT = "VideoDownloader-UpdateCheck"

# Installer check: Smaller files are treated as invalid downloads.
INSTALLER_MIN_SIZE_BYTES = 50 * 1024 * 1024

API_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 256 * 1024


class _DownloadCancelled(Exception):
    """The user pressed Cancel while the installer was downloading."""


class _InstallerInvalid(Exception):
    """The downloaded file failed the size / MZ-signature checks."""


def _github_request(url: str, extra_headers: dict = None) -> urllib.request.Request:
    """Builds a urllib Request carrying our identifying User-Agent header —
    shared by the release-info check (which also needs its own Accept
    header) and the installer download, so the header dict isn't
    duplicated at both call sites."""
    headers = {"User-Agent": _USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    return urllib.request.Request(url, headers=headers)


def _parse_version(v: str):
    """'v3.2.0' / '3.2.0' -> (3, 2, 0) so versions compare numerically
    instead of as strings (e.g. '3.10.0' > '3.9.0')."""
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        m = re.match(r"\d+", p)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def _looks_like_valid_installer(
    path: str,
    min_size_bytes: int = INSTALLER_MIN_SIZE_BYTES,
) -> bool:
    """Cheap sanity check: real Windows executables start with the "MZ"
    signature and the Inno Setup installer is always larger than
    INSTALLER_MIN_SIZE_BYTES. This catches e.g. an HTML error/redirect page
    saved with a .exe name, or a truncated file, before we ever try to run
    it."""
    try:
        if os.path.getsize(path) < min_size_bytes:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def _safe_remove(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug("Could not remove %s: %s", path, e)


def _is_network_failure(exc: Exception) -> bool:
    """True for connectivity-type failures (DNS, refused/reset/timeout,
    truncated response) as opposed to local file-system errors."""
    return isinstance(exc, (
        urllib.error.URLError, socket.timeout, TimeoutError,
        ConnectionError, http.client.HTTPException,
    ))


def _short_detail(exc: Exception, max_len: int = 160) -> str:
    text = str(exc).strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[:max_len - 1].rstrip() + "…"
    return text or exc.__class__.__name__


class UpdateChecker:
    """Wires the “Check for Updates” button to GitHub’s Releases API.
    Initialized after the required widgets exist.
    get_language is used as an accessor so the checker always gets the current UI language.
    The Download button is not controlled directly here, since its state depends on multiple conditions.
    This class only reports lock changes through refresh_download_button() and exposes is_locked.
    While the installer is downloading, update_cancel_button is shown below the progress label.
    Once the download is done, update_install_button appears next to it; the
    installer only runs when the user presses that button (install_update()).
    If the window closes during the download (or while the finished installer
    is waiting for the install button), cancel_download() should be called to
    remove the partial/finished file.
    """

    def __init__(self, root, get_language, refresh_download_button,
                 check_updates_button, uninstall_button,
                 ytdlp_status_label, action_buttons_frame,
                 update_buttons_frame, update_cancel_button, update_install_button):
        self.root = root
        self.get_language = get_language
        self.refresh_download_button = refresh_download_button
        self.check_updates_button = check_updates_button
        self.uninstall_button = uninstall_button
        self.ytdlp_status_label = ytdlp_status_label
        self.action_buttons_frame = action_buttons_frame
        self.update_buttons_frame = update_buttons_frame
        self.update_cancel_button = update_cancel_button
        self.update_install_button = update_install_button
        self._locked = False
        self._downloading = False
        self._ready_installer_path = None  # set once the installer is downloaded and validated
        self._cancel_event = threading.Event()

    @property
    def is_locked(self) -> bool:
        """True while an update check or installer download is running —
        one of the conditions that keeps the Download button disabled."""
        return self._locked

    @property
    def is_downloading(self) -> bool:
        """True from the start of the installer download until it is installed,
        cancelled or fails — including the time the finished installer waits
        for the user to press the install button."""
        return self._downloading

    def _set_update_lock(self, state: str):
        """Disable/enable the buttons that must stay locked while checking
        for or installing an update, then let the owner recompute the
        Download button (which re-enables only if nothing else — yt-dlp not
        ready, an active download — still needs it disabled)."""
        self._locked = state == "disabled"
        self.check_updates_button.configure(state=state)
        self.uninstall_button.configure(state=state)
        self.refresh_download_button()

    def _post(self, fn, *args):
        """Schedule `fn(*args)` on the Tk main thread from a worker thread.
        Silently ignored if the window is already gone."""
        try:
            self.root.after(0, lambda: fn(*args))
        except (RuntimeError, TclError):
            pass

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------
    def check_for_updates(self):
        """Triggered by the sidebar's 'Check for Updates' button. Hits the
        GitHub releases API in the background so the UI never freezes, then
        reports back on the main thread via root.after()."""
        self._set_update_lock("disabled")

        def worker():
            try:
                req = _github_request(
                    GITHUB_LATEST_RELEASE_API,
                    extra_headers={"Accept": "application/vnd.github+json"},
                )
                with urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                latest_tag = data.get("tag_name", "")
                assets = data.get("assets", [])
                # Only trust the exact installer asset — never fall back to
                # the release page URL, since that's an HTML page, not a
                # binary, and would fail (or worse, be executed as garbage)
                # if used as the "installer" to download and run.
                installer_url = next(
                    (a["browser_download_url"] for a in assets
                     if a.get("name", "").lower() == EXPECTED_INSTALLER_NAME.lower()),
                    None,
                )
                self._post(self._on_update_check_done, latest_tag, installer_url)
            except urllib.error.HTTPError as e:
                logger.warning("Update check failed (HTTP %s): %s", e.code, e)
                # Anonymous GitHub API calls are limited to 60/hour per IP;
                # 403/429 is almost always that limit.
                key = ("update_rate_limited_message" if e.code in (403, 429)
                       else "update_check_failed_message")
                self._post(self._on_update_check_failed, key)
            except Exception as e:
                logger.warning("Update check failed: %s", e, exc_info=True)
                self._post(self._on_update_check_failed, "update_check_failed_message")

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, latest_tag: str, installer_url: str):
        self._set_update_lock("normal")
        lang = self.get_language()

        if not latest_tag:
            self._on_update_check_failed()
            return

        try:
            is_newer = _parse_version(latest_tag) > _parse_version(APP_VERSION)
        except Exception:
            is_newer = latest_tag.lstrip("vV") != APP_VERSION

        if not is_newer:
            messagebox.showinfo(
                lang["update_check_title"],
                lang["already_latest_message"].replace("{version}", APP_VERSION),
                parent=self.root,
            )
            return

        if not installer_url:
            # A newer tag exists on GitHub, but it has no .exe asset attached
            # (e.g. the release was published without uploading the
            # installer). Offer the release page instead of failing silently
            # or, worse, trying to download/run something that isn't a real
            # installer.
            wants_browser = messagebox.askyesno(
                lang["update_available_title"],
                lang["update_no_installer_message"].replace("{version}", latest_tag),
                parent=self.root,
            )
            if wants_browser:
                webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/tag/{latest_tag}")
            return

        wants_update = messagebox.askyesno(
            lang["update_available_title"],
            lang["update_available_message"].replace("{version}", latest_tag),
            parent=self.root,
        )
        if wants_update:
            self._download_installer(installer_url)

    def _on_update_check_failed(self, message_key: str = "update_check_failed_message"):
        self._set_update_lock("normal")
        lang = self.get_language()
        messagebox.showerror(
            lang["error_title"],
            lang.get(message_key, lang["update_check_failed_message"]),
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Installer download
    # ------------------------------------------------------------------
    def cancel_download(self):
        """Cancel button handler (also safe to call from the app's close
        handler). While downloading, the worker stops at the next chunk and
        deletes the partial .part file. If the download already finished and
        is waiting for the install button, the finished installer is deleted."""
        if not self._downloading:
            return

        if self._ready_installer_path:
            _safe_remove(self._ready_installer_path)
            self._on_download_cancelled()
            return

        if self._cancel_event.is_set():
            return
        self._cancel_event.set()
        lang = self.get_language()
        self.update_cancel_button.configure(state="disabled")
        self.ytdlp_status_label.configure(text=lang["download_canceling_message"])

    def _show_download_ui(self):
        lang = self.get_language()
        self.ytdlp_status_label.configure(text=lang["update_downloading_message"])
        self.ytdlp_status_label.pack(pady=(0, 5), before=self.action_buttons_frame)
        self.update_cancel_button.configure(text=lang["cancel_button"], state="normal")
        self.update_cancel_button.pack(side="left", padx=5)
        self.update_install_button.pack_forget()  # appears only once the download is done
        self.update_buttons_frame.pack(pady=(0, 5), before=self.action_buttons_frame)

    def _hide_download_ui(self):
        """Idempotent: safe to call from every end-of-download path."""
        self._downloading = False
        self._ready_installer_path = None
        self.ytdlp_status_label.pack_forget()
        self.update_cancel_button.pack_forget()
        self.update_install_button.pack_forget()
        self.update_buttons_frame.pack_forget()

    def _show_progress(self, percent: int):
        if self._cancel_event.is_set():
            return  # keep showing the "canceling..." text
        lang = self.get_language()
        self.ytdlp_status_label.configure(
            text=lang["update_download_progress_message"].replace("{percent}", str(percent))
        )

    def _on_download_cancelled(self):
        self._hide_download_ui()
        self._set_update_lock("normal")

    def _on_download_error(self, message: str):
        self._hide_download_ui()
        self._set_update_lock("normal")
        lang = self.get_language()
        messagebox.showerror(lang["error_title"], message, parent=self.root)

    def _on_download_ready(self, installer_path: str):
        """The installer is fully downloaded and validated. Nothing is launched
        yet: show the install button next to Cancel and wait for the user."""
        self._ready_installer_path = installer_path
        lang = self.get_language()
        self.ytdlp_status_label.configure(text=lang["update_ready_message"])
        self.update_cancel_button.configure(state="normal")
        self.update_install_button.configure(text=lang["update_install_button"], state="normal")
        self.update_install_button.pack(side="left", padx=5)

    def install_update(self):
        """Install button handler: launches the downloaded installer and
        closes the app."""
        path = self._ready_installer_path
        if not path:
            return
        if not os.path.exists(path):
            lang = self.get_language()
            self._on_download_error(lang["update_download_failed_message"])
            return
        self._launch_installer_and_exit(path)

    def _download_installer(self, installer_url: str):
        """Downloads the installer .exe to a temp folder. It is NOT launched
        automatically: once the download is complete and validated, the
        install button appears and the user starts the installation (the
        same Inno Setup installer already overwrites the existing install in
        place, matching the manual update flow that was already tested).

        The file is written to "<name>.part" first and only renamed to its
        final name once it is complete AND passes the size/MZ checks, so a
        half-finished or invalid download can never be mistaken for (or
        launched as) the installer."""
        self._set_update_lock("disabled")
        self._downloading = True
        self._cancel_event.clear()
        self._show_download_ui()

        def worker():
            lang = self.get_language()
            final_path = os.path.join(tempfile.gettempdir(), "VideoDownloaderSetup_update.exe")
            part_path = final_path + ".part"
            try:
                req = _github_request(installer_url)
                with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as resp:
                    total = int(resp.headers.get("Content-Length") or 0)
                    # Reject early if the server already tells us the file
                    # is too small to be the installer — no point downloading.
                    if total and total < INSTALLER_MIN_SIZE_BYTES:
                        raise _InstallerInvalid(f"Content-Length {total} too small")

                    written = 0
                    last_percent = -1
                    with open(part_path, "wb") as f:
                        while True:
                            if self._cancel_event.is_set():
                                raise _DownloadCancelled()
                            chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
                            if not chunk:
                                break
                            written += len(chunk)
                            f.write(chunk)
                            if total:
                                percent = min(100, written * 100 // total)
                                if percent != last_percent:  # only repaint on change
                                    last_percent = percent
                                    self._post(self._show_progress, percent)

                if total and written != total:
                    raise ConnectionError(f"incomplete download ({written}/{total} bytes)")
                if self._cancel_event.is_set():
                    raise _DownloadCancelled()

                # Validate BEFORE the file gets its final name / is executed.
                if not _looks_like_valid_installer(part_path):
                    raise _InstallerInvalid("size or MZ signature check failed")

                os.replace(part_path, final_path)
                if self._cancel_event.is_set():
                    raise _DownloadCancelled()

                self._post(self._on_download_ready, final_path)

            except _DownloadCancelled:
                _safe_remove(final_path)
                self._post(self._on_download_cancelled)
            except _InstallerInvalid as e:
                logger.warning("Installer rejected: %s", e)
                self._post(self._on_download_error, lang["update_invalid_installer_message"])
            except Exception as e:
                logger.warning("Installer download failed: %s", e, exc_info=True)
                if _is_network_failure(e) or not isinstance(e, OSError):
                    message = lang["update_download_failed_message"]
                else:
                    # Local file problem: disk full, permission denied, ...
                    message = classify_generic_exception(e, lang)
                self._post(self._on_download_error, message)
            finally:
                _safe_remove(part_path)  # never leave a partial file behind

        threading.Thread(target=worker, daemon=True).start()

    def _launch_installer_and_exit(self, installer_path: str):
        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and k != "_MEIPASS2"
        }
        try:
            try:
                subprocess.Popen([installer_path], env=clean_env)
            except OSError as e:
                if getattr(e, "winerror", None) == 740:
                    # Installer requires elevation: let the shell show UAC.
                    os.startfile(installer_path)
                else:
                    raise
        except OSError as e:
            logger.warning("Installer launch failed: %s", e, exc_info=True)
            lang = self.get_language()
            self._on_download_error(
                lang["update_launch_failed_message"].replace("{error}", _short_detail(e))
            )
            return

        self.root.destroy()
        sys.exit()