"""
On-screen rendering of the download queue, on top of a DownloadQueue.

QueueView owns one DownloadQueue instance (see download_queue.py — items
waiting to download, plus the one currently in flight) and knows how to
redraw it into a set of widgets and how to fetch/attach a preview (title,
duration, thumbnail) for an item. The queue mutation methods below
(enqueue/pop_next/remove/clear/find) and the current_item/items/total
accessors are thin pass-throughs to that DownloadQueue, kept here so every
existing call site (main.py's queue_view.current_item, queue_view.items,
queue_view.enqueue(...), etc.) keeps working unchanged — only the state
itself moved, not the interface.

It has no opinion on when items get added or when the next one should
start downloading — that's still main.py's job (add_to_queue,
process_next_in_queue), since it involves widgets and download state
(pause/cancel, save location, etc.) this module knows nothing about.
Those call into QueueView to read or mutate the queue and then trigger a
redraw the same way the moved functions used to.
"""

import io
import logging
import os
import threading
import urllib.request

import customtkinter as ctk
from PIL import Image

from core.download_queue import DownloadQueue
from utils import format_duration

logger = logging.getLogger(__name__)


class QueueView:
    def __init__(self):
        self.queue = DownloadQueue()

    # -- pass-throughs to DownloadQueue, so existing call sites (main.py's
    # queue_view.current_item / .items / .enqueue(...) etc.) don't need to
    # change -----------------------------------------------------------

    @property
    def current_item(self):
        return self.queue.current_item

    @current_item.setter
    def current_item(self, value):
        self.queue.current_item = value

    @property
    def items(self):
        return self.queue.items

    @property
    def total(self) -> int:
        return self.queue.total

    def enqueue(self, url: str, quality_key: str) -> dict:
        return self.queue.enqueue(url, quality_key)

    def pop_next(self):
        return self.queue.pop_next()

    def remove(self, item_id: int) -> None:
        self.queue.remove(item_id)

    def clear(self) -> None:
        self.queue.clear()

    def find(self, item_id: int):
        return self.queue.find(item_id)

    # -- preview fetching ----------------------------------------------------

    def fetch_preview(self, item: dict, after, on_done) -> None:
        """Fetches preview info (title/duration/thumbnail) for `item` in a
        background thread. Once done (or if it fails/skips), schedules
        on_done(item_id, info, thumb_bytes) back onto the UI thread via
        after(delay_ms, func) — pass root.after for that.

        info is None and nothing is scheduled if yt-dlp isn't ready yet, or
        the link is invalid/unsupported/unreachable — the item is simply
        left without a preview, same as before.
        """
        def worker():
            from settings import get_appdata_path
            from downloading.ytdlp_manager import get_ytdlp_path, fetch_preview_info

            exe_path = get_ytdlp_path(get_appdata_path())
            if not os.path.exists(exe_path):
                return  # yt-dlp isn't ready yet — leave the plain url line as-is

            info = fetch_preview_info(exe_path, item["url"])
            if info is None:
                return  # invalid link / unsupported site / no network — leave the plain url line

            thumb_bytes = None
            thumb_url = info.get("thumbnail")
            if thumb_url:
                try:
                    with urllib.request.urlopen(thumb_url, timeout=10) as resp:
                        thumb_bytes = resp.read()
                except Exception as e:
                    logger.debug("Queue item thumbnail download failed: %s", e)

            after(0, lambda: on_done(item["id"], info, thumb_bytes))

        threading.Thread(target=worker, daemon=True).start()

    def apply_preview(self, item_id: int, info: dict, thumb_bytes) -> bool:
        """Attaches fetched preview info to the queue item with this id, if
        it's still around (see find()). Returns whether it was applied —
        the caller still needs to trigger its own re-render either way."""
        target = self.find(item_id)
        if target is None:
            return False

        thumb_image = None
        if thumb_bytes:
            try:
                image = Image.open(io.BytesIO(thumb_bytes))
                thumb_image = ctk.CTkImage(light_image=image, dark_image=image, size=(60, 34))
            except Exception as e:
                logger.debug("Queue item thumbnail decode failed: %s", e)

        target["preview"] = {
            "title": info.get("title") or target["url"],
            "duration": format_duration(info.get("duration")),
            "thumb_image": thumb_image,
        }
        return True

    # -- rendering ----------------------------------------------------------

    def render(self, widgets, text_color, make_icon, quality_label, current_language, on_remove) -> None:
        """Redraws the queue list. The active item (current_item), if any,
        is shown first — marked with ▶, no remove button (cancel_button,
        owned by main.py, is used for that instead) — followed by the
        waiting items in order.

        widgets: {"list_frame", "header_label", "clear_button"}
        make_icon(filename, color, size) -> CTkImage | None
        quality_label(quality_key) -> str
        on_remove(item_id) -> called when a row's ❌ is clicked
        """
        list_frame = widgets["list_frame"]
        header_label = widgets["header_label"]
        clear_button = widgets["clear_button"]

        for child in list_frame.winfo_children():
            child.destroy()

        total = self.total
        if not total:
            list_frame.grid_remove()
            header_label.grid_remove()
            clear_button.grid_remove()
            return

        header_label.configure(text=f"{current_language['queue_title_label']} ({total})")
        header_label.grid()
        clear_button.grid()
        list_frame.grid()

        # (display_index, item, is_active) — the active item gets no number
        # (shown with ▶ instead), waiting items keep their original 1-based
        # position in self.items.
        rows = []
        if self.current_item:
            rows.append((None, self.current_item, True))
        rows.extend((idx, item, False) for idx, item in enumerate(self.items, start=1))

        for idx, item, is_active in rows:
            self._render_row(list_frame, idx, item, is_active, text_color, make_icon, quality_label, on_remove)

    def _render_row(self, list_frame, idx, item, is_active, text_color, make_icon, quality_label, on_remove):
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2, padx=2)

        preview = item.get("preview")

        # Thumbnail — only shown once fetched; the row just starts without
        # one and gets it added in when apply_preview()'s caller re-renders.
        if preview and preview.get("thumb_image"):
            thumb_label = ctk.CTkLabel(row, text="", image=preview["thumb_image"], width=60, height=34)
            thumb_label.image = preview["thumb_image"]  # keep a reference so it isn't GC'd
            thumb_label.pack(side="left", padx=(5, 8))

        text_frame = ctk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True)

        prefix = "▶ " if is_active else f"{idx}. "

        if preview:
            title = preview["title"]
            display_title = title if len(title) <= 55 else title[:52] + "..."
            title_label = ctk.CTkLabel(
                text_frame, text=f"{prefix}{display_title}",
                anchor="w", font=("Helvetica", 12, "bold"),
                text_color=text_color, justify="left",
            )
            title_label.pack(anchor="w", fill="x")

            subtitle = f"[{quality_label(item['quality_key'])}]"
            if preview.get("duration"):
                subtitle += f"  {preview['duration']}"

            if is_active:
                # Active item: show the status as a small download.png icon
                # next to the subtitle text instead of the old text label.
                subtitle_row = ctk.CTkFrame(text_frame, fg_color="transparent")
                subtitle_row.pack(anchor="w", fill="x")

                subtitle_label = ctk.CTkLabel(
                    subtitle_row, text=subtitle,
                    anchor="w", font=("Helvetica", 11),
                    text_color=text_color,
                )
                subtitle_label.pack(side="left")

                status_icon = make_icon("download.png", text_color, (14, 14))
                if status_icon is not None:
                    status_icon_label = ctk.CTkLabel(subtitle_row, text="", image=status_icon)
                    status_icon_label.image = status_icon  # keep a reference so it isn't GC'd
                    status_icon_label.pack(side="left", padx=(10, 0))
            else:
                subtitle_label = ctk.CTkLabel(
                    text_frame, text=subtitle,
                    anchor="w", font=("Helvetica", 11),
                    text_color=text_color,
                )
                subtitle_label.pack(anchor="w", fill="x")
        else:
            # Preview not fetched yet (or fetch failed/timed out) — same
            # plain [quality] url line as before, so nothing looks broken.
            display_url = item["url"] if len(item["url"]) <= 60 else item["url"][:57] + "..."
            label = ctk.CTkLabel(
                text_frame,
                text=f"{prefix}[{quality_label(item['quality_key'])}] {display_url}",
                anchor="w", font=("Helvetica", 12),
                text_color=text_color,
            )
            label.pack(anchor="w", fill="x")

        if not is_active:
            remove_btn = ctk.CTkButton(
                row, text="❌", width=24, height=24,
                fg_color="transparent", hover_color="#dddddd", text_color="#d9534f",
                command=lambda item_id=item["id"]: on_remove(item_id),
            )
            remove_btn.pack(side="right", padx=5)