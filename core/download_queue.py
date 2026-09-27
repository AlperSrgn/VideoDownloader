"""
Pure download-queue state: the items waiting to download, plus the one
currently in flight. No widget references, no threading, no image/network
I/O — this is the "data" half of what used to be QueueView's job (see
ui/queue_view.py, which now owns one DownloadQueue instance and handles
preview-fetching and drawing the queue into widgets on top of it).

Having no GUI import of its own means this class can be exercised directly
in a plain script or test, without customtkinter/tkinter ever loading.
"""

import itertools
from collections import deque


class DownloadQueue:
    def __init__(self):
        self.items = deque()      # waiting items: {"id", "url", "quality_key", "preview"}
        self.current_item = None  # the one item currently downloading, or None when idle
        self._id_counter = itertools.count(1)

    def enqueue(self, url: str, quality_key: str) -> dict:
        """Adds a new item to the end of the queue and returns it."""
        item = {"id": next(self._id_counter), "url": url, "quality_key": quality_key, "preview": None}
        self.items.append(item)
        return item

    def pop_next(self):
        """Moves the next waiting item (if any) into current_item and
        returns it (or None if the queue was empty). Assumes current_item
        is already None — i.e. nothing else is currently in flight."""
        self.current_item = self.items.popleft() if self.items else None
        return self.current_item

    def remove(self, item_id: int) -> None:
        self.items = deque(item for item in self.items if item["id"] != item_id)

    def clear(self) -> None:
        self.items = deque()

    def find(self, item_id: int):
        """Looks up an item by id among current_item and the waiting items.
        Used to apply a preview fetched in the background, since by the
        time it arrives the item may have moved between the two, or been
        removed/cleared entirely."""
        if self.current_item is not None and self.current_item["id"] == item_id:
            return self.current_item
        return next((i for i in self.items if i["id"] == item_id), None)

    @property
    def total(self) -> int:
        return len(self.items) + (1 if self.current_item else 0)
