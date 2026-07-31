"""Compact Windows article notifications grouped by local delivery day."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import date
from html import escape
from pathlib import Path
from typing import Optional

from .article_lifecycle import (
    NotificationArticle,
    NotificationDelivery,
    RefreshNotification,
)
from .windows_icon import default_windows_icon_path

_HEADING_LIMIT = 120
_BODY_LIMIT = 350
_JOURNAL_LIMIT = 80
_DEFAULT_MAX_NOTIFICATIONS = 5
_WINDOWS_NOTIFICATION_LIMIT = 20


class WindowsSummaryNotificationAdapter:
    """Deliver one lifecycle batch as same-day grouped article notifications."""

    def __init__(
        self,
        *,
        sender: Optional[Callable[..., object]] = None,
        icon_path: Optional[Path] = None,
        dashboard_path: Optional[Path] = None,
        max_notifications: int = _DEFAULT_MAX_NOTIFICATIONS,
        today: Callable[[], date] = date.today,
    ) -> None:
        if (
            isinstance(max_notifications, bool)
            or not isinstance(max_notifications, int)
            or max_notifications < 0
        ):
            raise ValueError("max_notifications must be a non-negative integer")
        self._sender = sender
        self._today = today
        self.icon_path = Path(icon_path) if icon_path is not None else default_windows_icon_path()
        self.dashboard_path = Path(dashboard_path) if dashboard_path is not None else None
        self.max_notifications = min(max_notifications, _WINDOWS_NOTIFICATION_LIMIT)

    def deliver(self, notification: RefreshNotification) -> NotificationDelivery:
        if self.max_notifications == 0:
            return NotificationDelivery.ACCEPTED
        try:
            sender = self._sender or _load_windows_notifier()
        except ImportError:
            return NotificationDelivery.REJECTED

        if not notification.articles:
            _send_legacy_summary(sender, notification, self.icon_path)
            return NotificationDelivery.ACCEPTED

        group_date = self._today()
        prepared = tuple(
            (
                article,
                _notification_article_target(article, self.dashboard_path),
            )
            for article in notification.articles[: self.max_notifications]
        )
        # Windows places the most recently submitted toast first. Submit the
        # selected batch oldest-first so the newest article remains at the top.
        for article, target in reversed(prepared):
            _send_article_toast(
                sender,
                title=article.title,
                journal=article.journal or article.source,
                target=target,
                article_key=article.article_id,
                group_date=group_date,
            )
        return NotificationDelivery.ACCEPTED


class WindowsArticleNotificationAdapter:
    """Deliver one compact article notification without owning Article state."""

    def __init__(
        self,
        *,
        sender: Optional[Callable[..., object]] = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._sender = sender
        self._today = today

    def deliver(self, article: Mapping[str, object], dashboard_path: Path) -> bool:
        try:
            sender = self._sender or _load_windows_notifier()
        except ImportError:
            return False

        target = _article_target(article, dashboard_path)
        title = str(article.get("title") or "Paper Monitor")
        journal = str(article.get("journal") or article.get("source") or "")
        article_key = str(article.get("identity") or article.get("article_id") or target)
        try:
            _send_article_toast(
                sender,
                title=title,
                journal=journal,
                target=target,
                article_key=article_key,
                group_date=self._today(),
            )
        except Exception:
            return False
        return True


def _load_windows_notifier() -> Callable[..., object]:
    from .windows_toast_sender import ensure_available, send_toast

    ensure_available()
    return send_toast


def _send_article_toast(
    sender: Callable[..., object],
    *,
    title: str,
    journal: str,
    target: str,
    article_key: str,
    group_date: date,
) -> None:
    group_id = _day_group_id(group_date)
    kwargs = {
        "on_click": target,
        "xml": _article_toast_xml(
            title=title,
            journal=journal,
            target=target,
            group_id=group_id,
            group_title=group_date.isoformat(),
        ),
        "group": group_id,
        "tag": _article_tag(article_key),
    }
    sender(None, None, **kwargs)


def _send_legacy_summary(
    sender: Callable[..., object],
    notification: RefreshNotification,
    icon_path: Optional[Path],
) -> None:
    kwargs = {}
    if icon_path is not None and icon_path.is_file():
        kwargs["icon"] = str(icon_path)
    sender(
        _truncate(notification.heading, _HEADING_LIMIT),
        _truncate(notification.body, _BODY_LIMIT),
        **kwargs,
    )


def _article_toast_xml(
    *,
    title: str,
    journal: str,
    target: str,
    group_id: str,
    group_title: str,
) -> str:
    title_node = (
        '<text hint-style="base" hint-wrap="true" hint-maxLines="2">'
        f"{_xml_value(_truncate(title, _HEADING_LIMIT))}"
        "</text>"
    )
    compact_journal = _truncate(journal, _JOURNAL_LIMIT)
    journal_node = (
        '<text hint-style="captionSubtle" hint-wrap="false" hint-maxLines="1">'
        f"{_xml_value(compact_journal)}"
        "</text>"
        if compact_journal
        else ""
    )
    safe_target = _xml_value(target)
    return (
        f'<toast activationType="protocol" launch="{safe_target}">'
        f'<header id="{_xml_value(group_id)}" title="{_xml_value(group_title)}" '
        f'arguments="{safe_target}" activationType="protocol"/>'
        '<visual><binding template="ToastGeneric"><group><subgroup>'
        f"{title_node}{journal_node}"
        "</subgroup></group></binding></visual>"
        "</toast>"
    )


def _notification_article_target(
    article: NotificationArticle,
    dashboard_path: Optional[Path],
) -> str:
    target = _browser_target(article.url, article.doi)
    if target:
        return target
    if dashboard_path is not None:
        return dashboard_path.resolve().as_uri()
    raise ValueError(f"Notification article {article.article_id!r} has no browser target")


def _article_target(article: Mapping[str, object], dashboard_path: Path) -> str:
    target = _browser_target(
        str(article.get("url") or ""),
        str(article.get("doi") or ""),
    )
    return target or Path(dashboard_path).resolve().as_uri()


def _browser_target(url: str, doi: str) -> str:
    clean_url = str(url or "").strip()
    clean_doi = str(doi or "").strip()
    if clean_url.casefold().startswith(("http://", "https://")):
        return clean_url
    if clean_doi:
        return "https://doi.org/" + clean_doi
    return ""


def _day_group_id(group_date: date) -> str:
    return f"pm{group_date:%Y%m%d}"


def _article_tag(article_key: str) -> str:
    return hashlib.sha256(str(article_key).encode("utf-8", errors="replace")).hexdigest()[:16]


def _xml_value(value: object) -> str:
    return escape(str(value), quote=True)


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."[:limit]
