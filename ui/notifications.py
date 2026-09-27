"""
System notifications (Windows toast via plyer).

Both call sites — a download finishing (core/download_controller.py) and
the sidebar's "preview notification" button (main.py) — share the same
"only if the user's checkbox is on" guard, so it's centralized here
rather than repeated at each call site. This is also the only place that
imports plyer, so neither of those two callers needs to know it exists.
"""

from plyer import notification


def notify(enabled: bool, title: str, message: str, icon: str, timeout: int = 3) -> None:
    """Shows a system notification, unless `enabled` is False — the
    user's "system_notification" checkbox setting in main.py."""
    if not enabled:
        return
    notification.notify(title=title, message=message, timeout=timeout, app_icon=icon)