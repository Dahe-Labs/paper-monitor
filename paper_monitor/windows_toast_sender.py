"""Minimal Windows Toast sender with an explicit Paper Monitor identity."""

from __future__ import annotations

from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Optional

from .app_identity import WINDOWS_APP_USER_MODEL_ID


def ensure_available() -> None:
    _winrt_types()


def send_toast(
    title: Optional[str] = None,
    body: Optional[str] = None,
    *,
    xml: Optional[str] = None,
    group: Optional[str] = None,
    tag: Optional[str] = None,
    on_click: Optional[str] = None,
    icon: Optional[str] = None,
) -> object:
    """Show one toast through the two WinRT namespaces this app actually uses."""

    xml_document_type, toast_type, manager = _winrt_types()
    toast_xml = xml or _summary_xml(
        title or "Paper Monitor",
        body or "",
        on_click=on_click,
        icon=icon,
    )
    document = xml_document_type()
    document.load_xml(toast_xml)
    toast = toast_type(document)
    if tag:
        toast.tag = str(tag)
    if group:
        toast.group = str(group)
    notifier = manager.create_toast_notifier_with_id(WINDOWS_APP_USER_MODEL_ID)
    notifier.show(toast)
    return toast


@lru_cache(maxsize=1)
def _winrt_types():
    from winrt.windows.data.xml.dom import XmlDocument
    from winrt.windows.ui.notifications import (
        ToastNotification,
        ToastNotificationManager,
    )

    return XmlDocument, ToastNotification, ToastNotificationManager


def _summary_xml(
    title: str,
    body: str,
    *,
    on_click: Optional[str],
    icon: Optional[str],
) -> str:
    launch = ""
    if on_click:
        launch = (
            f' activationType="protocol" launch="{escape(str(on_click), quote=True)}"'
        )
    image = ""
    if icon:
        try:
            source = Path(icon).expanduser().resolve().as_uri()
        except (OSError, ValueError):
            source = ""
        if source:
            image = (
                '<image placement="appLogoOverride" hint-crop="circle" '
                f'src="{escape(source, quote=True)}"/>'
            )
    return (
        f"<toast{launch}><visual><binding template=\"ToastGeneric\">"
        f"{image}<text>{escape(str(title))}</text>"
        f"<text>{escape(str(body))}</text>"
        "</binding></visual></toast>"
    )
