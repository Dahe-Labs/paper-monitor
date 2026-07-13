"""Windows Adapter for one summary notification per Background Refresh Run."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, Optional

from .article_lifecycle import (
    NotificationDelivery,
    RefreshNotification,
)

_HEADING_LIMIT = 120
_BODY_LIMIT = 350


class WindowsSummaryNotificationAdapter:
    """Submit one Refresh Notification without owning Article state or retries."""

    def __init__(
        self,
        *,
        sender: Optional[Callable[..., object]] = None,
        icon_path: Optional[Path] = None,
    ) -> None:
        self._sender = sender
        self.icon_path = Path(icon_path) if icon_path is not None else default_windows_icon_path()

    def deliver(self, notification: RefreshNotification) -> NotificationDelivery:
        try:
            sender = self._sender or _load_windows_notifier()
        except ImportError:
            return NotificationDelivery.REJECTED

        kwargs = {}
        if self.icon_path is not None and self.icon_path.is_file():
            kwargs["icon"] = str(self.icon_path)
        sender(
            _truncate(notification.heading, _HEADING_LIMIT),
            _truncate(notification.body, _BODY_LIMIT),
            **kwargs,
        )
        return NotificationDelivery.ACCEPTED


class WindowsArticleNotificationAdapter:
    """Deliver one per-article notification without owning Article state."""

    def __init__(
        self,
        *,
        sender: Optional[Callable[..., object]] = None,
        icon_path: Optional[Path] = None,
    ) -> None:
        self._sender = sender
        self.icon_path = Path(icon_path) if icon_path is not None else default_windows_icon_path()

    def deliver(self, article: Mapping[str, object], dashboard_path: Path) -> bool:
        try:
            sender = self._sender or _load_windows_notifier()
        except ImportError:
            return False

        target = _article_target(article, dashboard_path)
        title = _truncate(str(article.get("title") or "Paper Monitor"), _HEADING_LIMIT)
        journal = _truncate(
            str(article.get("journal") or article.get("source") or ""),
            80,
        )
        message = str(article.get("doi") or article.get("url") or "Open dashboard")
        kwargs = {"on_click": target}
        if self.icon_path is not None and self.icon_path.is_file():
            kwargs["icon"] = str(self.icon_path)
        try:
            sender(title, f"{journal}\n{message}".strip(), **kwargs)
        except Exception:
            return False
        return True


def default_windows_icon_path() -> Optional[Path]:
    frozen_root = getattr(sys, "_MEIPASS", None)
    candidates = (
        Path(frozen_root) / "windows" / "assets" / "PaperMonitor.ico"
        if frozen_root
        else None,
        Path(sys.executable).resolve().parent / "PaperMonitor.ico",
        Path(__file__).resolve().parents[1] / "windows" / "assets" / "PaperMonitor.ico",
    )
    return next((path for path in candidates if path is not None and path.is_file()), None)


def _load_windows_notifier() -> Callable[..., object]:
    from win11toast import notify

    return notify


def _article_target(article: Mapping[str, object], dashboard_path: Path) -> str:
    url = str(article.get("url") or "")
    doi = str(article.get("doi") or "")
    if url.startswith(("http://", "https://")):
        return url
    if doi:
        return "https://doi.org/" + doi
    return Path(dashboard_path).resolve().as_uri()


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."[:limit]
