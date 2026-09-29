"""
App self-update checking: compares the installed version against the
latest GitHub release, and offers to download/launch the installer.

Split out of main.py as its own feature: it polls its own API, verifies
and runs its own installer, and only needs a handful of UI widgets
(passed in explicitly once they exist) rather than reaching into
main.py's App instance directly.
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
import webbrowser
from tkinter import messagebox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App version & "Check for Updates"
# ---------------------------------------------------------------------------
# Bump this on every release — must match the Inno Setup AppVersion so the
# comparison against GitHub's latest release tag is meaningful.
APP_VERSION = "3.7.0"

GITHUB_REPO = "AlperSrgn/VideoDownloader"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXPECTED_INSTALLER_NAME = "VideoDownloaderSetup.exe"

_USER_AGENT = "VideoDownloader-UpdateCheck"


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


def _looks_like_valid_installer(path: str, min_size_bytes: int = 500_000) -> bool:
    """Cheap sanity check: real Windows executables start with the "MZ"
    signature and Inno Setup installers are always well over 500 KB. This
    catches e.g. an HTML error/redirect page that got saved with a .exe
    name, before we ever try to run it."""
    try:
        if os.path.getsize(path) < min_size_bytes:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


class UpdateChecker:
    """Wires the "Check for Updates" button to GitHub's releases API.

    Constructed once the widgets it needs already exist. `get_language`
    and `is_download_active` are accessors (not values) because both the
    current UI language and whether a download is running change over
    the app's lifetime — the checker always wants the live value.
    """

    def __init__(self, root, get_language, is_download_active,
                 check_updates_button, uninstall_button, download_button,
                 ytdlp_status_label, action_buttons_frame):
        self.root = root
        self.get_language = get_language
        self.is_download_active = is_download_active
        self.check_updates_button = check_updates_button
        self.uninstall_button = uninstall_button
        self.download_button = download_button
        self.ytdlp_status_label = ytdlp_status_label
        self.action_buttons_frame = action_buttons_frame

    def _set_update_lock(self, state: str):
        """Disable/enable the buttons that must stay locked while checking
        for or installing an update. download_button only re-enables if
        nothing else (e.g. an active download) still needs it disabled."""
        self.check_updates_button.configure(state=state)
        self.uninstall_button.configure(state=state)
        if state == "disabled":
            self.download_button.configure(state="disabled")
        elif not self.is_download_active():
            self.download_button.configure(state="normal")

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
                with urllib.request.urlopen(req, timeout=10) as resp:
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
                self.root.after(0, lambda: self._on_update_check_done(latest_tag, installer_url))
            except Exception as e:
                logger.debug("Update check failed: %s", e)
                self.root.after(0, self._on_update_check_failed)

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
            )
            if wants_browser:
                webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/tag/{latest_tag}")
            return

        wants_update = messagebox.askyesno(
            lang["update_available_title"],
            lang["update_available_message"].replace("{version}", latest_tag),
        )
        if wants_update:
            self._download_and_run_installer(installer_url)

    def _on_update_check_failed(self):
        self._set_update_lock("normal")
        lang = self.get_language()
        messagebox.showerror(lang["error_title"], lang["update_check_failed_message"])

    def _download_and_run_installer(self, installer_url: str):
        """Downloads the installer .exe to a temp folder, then launches it
        and closes the app — the same Inno Setup installer already
        overwrites the existing install in place, matching the manual
        update flow that was already tested."""
        self._set_update_lock("disabled")
        lang = self.get_language()
        self.ytdlp_status_label.configure(text=lang["update_downloading_message"])
        self.ytdlp_status_label.pack(pady=(0, 5), before=self.action_buttons_frame)

        def worker():
            try:
                installer_path = os.path.join(tempfile.gettempdir(), "VideoDownloaderSetup_update.exe")
                req = _github_request(installer_url)
                with urllib.request.urlopen(req, timeout=30) as resp, open(installer_path, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)

                # Sanity check before executing anything: a valid Windows PE
                # binary starts with the "MZ" signature and Inno Setup
                # installers are never a few KB. Without this check, a bad
                # download (e.g. an HTML error page saved with a .exe name)
                # would get handed straight to subprocess.Popen().
                if not _looks_like_valid_installer(installer_path):
                    try:
                        os.remove(installer_path)
                    except OSError:
                        pass
                    self.root.after(0, self._on_update_check_failed)
                    self.root.after(0, self.ytdlp_status_label.pack_forget)
                    return

                self.root.after(0, lambda: self._launch_installer_and_exit(installer_path))
            except Exception as e:
                logger.debug("Installer download failed: %s", e)
                self.root.after(0, self._on_update_check_failed)
                self.root.after(0, self.ytdlp_status_label.pack_forget)

        threading.Thread(target=worker, daemon=True).start()

    def _launch_installer_and_exit(self, installer_path: str):
        clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI_") and k != "_MEIPASS2"
        }
        subprocess.Popen([installer_path], env=clean_env)
        self.root.destroy()
        sys.exit()