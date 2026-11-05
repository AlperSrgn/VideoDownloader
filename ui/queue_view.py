"""
On-screen rendering of the download queue, on top of a DownloadQueue.

QueueView owns one DownloadQueue (core/download_queue.py: waiting items plus
the one in flight), redraws it into a set of widgets, and fetches/attaches
a preview (title, duration, thumbnail) for an item. The queue methods are
thin pass-throughs to DownloadQueue.

It does not decide when items are added or started; that is
DownloadController's job (core/download_controller.py).
"""

import io
import logging
import os
import queue
import threading
import urllib.request

import customtkinter as ctk
from PIL import Image

from core.download_queue import DownloadQueue
from settings import get_appdata_path
from utils import format_duration
from ytdlp import fetch_preview_info, get_ytdlp_path

logger = logging.getLogger(__name__)

# Too many widgets cause the GUI to freeze. Only a limited number of rows
# are drawn; the remaining rows stay queued and appear as "+N more".
MAX_VISIBLE_ROWS = 40

# Lazy thumbnails for playlist rows (see QueueView.ensure_thumbnails): only the
# drawn rows get one, fetched by a few daemon threads with a plain HTTP request.
THUMB_WORKERS = 4
THUMB_TIMEOUT = 10                  # seconds
THUMB_MAX_BYTES = 2 * 1024 * 1024   # a 320x180 JPEG is ~15 KB; this is a safety cap


class QueueView:
    def __init__(self):
        self.queue = DownloadQueue()

        # Lazy thumbnail loading (playlist rows): work queue + worker threads
        # (started on first use) and the placeholder label of each drawn row,
        # so a finished thumbnail can be put into its row without redrawing
        # the whole list.
        self._thumb_queue = queue.Queue()
        self._thumb_workers_started = False
        self._thumb_labels = {}  # item id -> CTkLabel of the currently drawn row

    # -- pass-throughs to DownloadQueue --------------------------------------

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

        Nothing is scheduled if yt-dlp isn't ready yet, or the link is
        invalid/unsupported/unreachable — the item is simply left without
        a preview.
        """
        def fetch():
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

        def worker():
            # Without this, an unexpected error would end the thread silently
            # and the preview would just never show up.
            try:
                fetch()
            except Exception:
                logger.exception("Queue item preview failed: %s", item["url"])

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

    # -- lazy thumbnails (playlist rows) -------------------------------------
    # A playlist item has no per-video preview request (that was too heavy for
    # hundreds of videos), but its preview carries "thumb_url". The thumbnails
    # of the rows that are actually drawn are fetched here. preview["thumb_state"]
    # is None -> "loading" -> "done" / "failed", so a row is requested only once.

    def ensure_thumbnails(self, after, on_done) -> None:
        """Starts fetching the thumbnails of the visible rows that have a
        thumb_url but no image yet. Call it after render(), on the UI thread.
        Each result arrives as on_done(item_id, PIL image | None) on the UI
        thread via after(0, func) (pass root.after)."""
        visible = []
        if self.current_item:
            visible.append(self.current_item)
        visible.extend(self.items)  # same order and limit as render()
        for item in visible[:MAX_VISIBLE_ROWS]:
            preview = item.get("preview")
            if (not preview or not preview.get("thumb_url")
                    or preview.get("thumb_image") or preview.get("thumb_state")):
                continue
            preview["thumb_state"] = "loading"
            self._start_thumb_workers()
            self._thumb_queue.put((item["id"], preview["thumb_url"], after, on_done))

    def _start_thumb_workers(self) -> None:
        if self._thumb_workers_started:
            return
        self._thumb_workers_started = True
        for _ in range(THUMB_WORKERS):
            threading.Thread(target=self._thumb_worker, daemon=True).start()

    def _thumb_worker(self) -> None:
        while True:
            item_id, url, after, on_done = self._thumb_queue.get()
            image = None
            try:
                with urllib.request.urlopen(url, timeout=THUMB_TIMEOUT) as resp:
                    data = resp.read(THUMB_MAX_BYTES)
                image = Image.open(io.BytesIO(data))
                image.load()  # decode here, off the UI thread
            except Exception as e:
                logger.debug("Queue thumbnail failed (%s): %s", url, e)
                image = None
            try:
                after(0, lambda i=item_id, img=image: on_done(i, img))
            except Exception:
                pass  # window already destroyed (app closing)

    def apply_thumbnail(self, item_id: int, image) -> bool:
        """UI thread. Stores a fetched thumbnail on its item and puts it into
        the item's row if that row is currently drawn. Returns False if the
        item is gone (removed / cleared meanwhile)."""
        target = self.find(item_id)
        if target is None or not target.get("preview"):
            return False
        preview = target["preview"]

        thumb_image = None
        if image is not None:
            try:
                thumb_image = ctk.CTkImage(light_image=image, dark_image=image, size=(60, 34))
            except Exception as e:
                logger.debug("Queue thumbnail decode failed: %s", e)

        label = self._thumb_labels.get(item_id)
        label_alive = label is not None and label.winfo_exists()
        if thumb_image is not None:
            preview["thumb_image"] = thumb_image
            preview["thumb_state"] = "done"
            if label_alive:
                label.configure(image=thumb_image)
                label.image = thumb_image  # keep a reference so it isn't GC'd
        else:
            preview["thumb_state"] = "failed"
            if label_alive:
                label.destroy()  # no empty box for a row without a thumbnail
            self._thumb_labels.pop(item_id, None)
        return True

    # -- rendering ----------------------------------------------------------

    def render(self, widgets, text_color, make_icon, quality_label, current_language, on_remove) -> None:
        """Redraws the queue list. The active item (current_item), if any,
        is shown first — marked with ▶, no remove button (cancel_button,
        owned by DownloadController, is used for that instead) — followed
        by the waiting items in order.

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
        self._thumb_labels = {}  # the labels of the old rows were just destroyed

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

        for idx, item, is_active in rows[:MAX_VISIBLE_ROWS]:
            self._render_row(list_frame, idx, item, is_active, text_color, make_icon, quality_label, on_remove)

        hidden = len(rows) - MAX_VISIBLE_ROWS
        if hidden > 0:
            ctk.CTkLabel(
                list_frame,
                text=f"… +{hidden} {current_language.get('queue_more_label', 'more')}",
                font=("Helvetica", 12, "italic"), text_color=text_color,
            ).pack(pady=4)

        self._clamp_scroll(list_frame)

    @staticmethod
    def _clamp_scroll(list_frame) -> None:
        """Keeps the list's scroll position inside the (new) content.

        render() destroys and rebuilds the rows. If the list was scrolled down
        and then got much shorter (Clear Queue, removing rows, the queue
        running down), the canvas can stay scrolled past the end of the new
        content, so the remaining rows -- e.g. the item that is downloading --
        sit above the visible area and the list looks empty. Refresh the
        scroll region first, then pull the view back if it points past the end
        (when everything fits, that means back to the top)."""
        try:
            canvas = list_frame._parent_canvas  # CTkScrollableFrame's internal canvas
            list_frame.update_idletasks()       # lay out the new rows first
            canvas.configure(scrollregion=canvas.bbox("all"))
            first, last = canvas.yview()
            max_first = max(0.0, 1.0 - (last - first))
            if first > max_first:
                canvas.yview_moveto(max_first)
        except Exception:
            logger.debug("Could not clamp the queue scroll position", exc_info=True)

    def _render_row(self, list_frame, idx, item, is_active, text_color, make_icon, quality_label, on_remove):
        row = ctk.CTkFrame(list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2, padx=2)

        preview = item.get("preview")

        # Thumbnail. Single videos: only shown once fetched, the row starts
        # without one and gets it added when apply_preview()'s caller
        # re-renders. Playlist rows (preview has "thumb_url"): an empty
        # placeholder of the same size is drawn right away and filled in by
        # apply_thumbnail() when the image arrives, so rows do not jump.
        thumb_image = preview.get("thumb_image") if preview else None
        wants_placeholder = bool(
            preview and preview.get("thumb_url") and preview.get("thumb_state") != "failed"
        )
        if thumb_image is not None or wants_placeholder:
            thumb_label = ctk.CTkLabel(row, text="", image=thumb_image, width=60, height=34)
            if thumb_image is not None:
                thumb_label.image = thumb_image  # keep a reference so it isn't GC'd
            thumb_label.pack(side="left", padx=(5, 8))
            if preview.get("thumb_url"):
                self._thumb_labels[item["id"]] = thumb_label

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
                # Active item: a small download.png icon next to the subtitle.
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
            # Preview not fetched yet (or the fetch failed): plain [quality] url line.
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