"""Set the explicit Windows taskbar identity for a pywebview window."""

from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .app_identity import WINDOWS_APP_USER_MODEL_ID

_APP_USER_MODEL_FORMAT_ID = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"
_I_PROPERTY_STORE_ID = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
_VT_LPWSTR = 31
_HRESULT = ctypes.c_long


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_text(cls, value: str) -> "_Guid":
        parsed = uuid.UUID(value)
        return cls(
            parsed.time_low,
            parsed.time_mid,
            parsed.time_hi_version,
            (ctypes.c_ubyte * 8)(*parsed.bytes[8:]),
        )


class _PropertyKey(ctypes.Structure):
    _fields_ = [
        ("fmtid", _Guid),
        ("pid", wintypes.DWORD),
    ]


class _PropVariantValue(ctypes.Union):
    _fields_ = [
        ("pwsz_value", wintypes.LPWSTR),
        ("padding", ctypes.c_ubyte * 16),
    ]


class _PropVariant(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("variant_type", wintypes.USHORT),
        ("reserved1", wintypes.USHORT),
        ("reserved2", wintypes.USHORT),
        ("reserved3", wintypes.USHORT),
        ("value", _PropVariantValue),
    ]


_PKEY_APP_USER_MODEL_ID = _PropertyKey(
    _Guid.from_text(_APP_USER_MODEL_FORMAT_ID),
    5,
)
_PKEY_RELAUNCH_ICON_RESOURCE = _PropertyKey(
    _Guid.from_text(_APP_USER_MODEL_FORMAT_ID),
    3,
)
_IID_I_PROPERTY_STORE = _Guid.from_text(_I_PROPERTY_STORE_ID)


def _is_windows() -> bool:
    return os.name == "nt"


def configure_window_taskbar(
    window: object,
    icon_path: Path,
    *,
    app_id: str = WINDOWS_APP_USER_MODEL_ID,
) -> bool:
    """Give one native window an explicit AUMID and taskbar icon resource."""

    if not _is_windows():
        return False
    handle = _native_window_handle(window)
    if not handle:
        return False
    icon_resource = _taskbar_icon_resource(icon_path)
    _set_window_string_properties(
        handle,
        (
            (_PKEY_APP_USER_MODEL_ID, str(app_id)),
            (_PKEY_RELAUNCH_ICON_RESOURCE, icon_resource),
        ),
    )
    return True


def _native_window_handle(window: object) -> Optional[int]:
    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)
    if handle is None:
        return None
    for method_name in ("ToInt64", "ToInt32"):
        method = getattr(handle, method_name, None)
        if callable(method):
            value = int(method())
            return value if value else None
    value = getattr(handle, "value", handle)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed else None


def _taskbar_icon_resource(icon_path: Path) -> str:
    resolved_icon = Path(icon_path).expanduser().resolve()
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        try:
            resolved_icon.relative_to(Path(frozen_root).resolve())
        except ValueError:
            pass
        else:
            executable = Path(sys.executable).resolve()
            if executable.is_file():
                return f"{executable},0"
    return f"{resolved_icon},0"


def _set_window_string_properties(
    handle: int,
    properties: Iterable[Tuple[_PropertyKey, str]],
) -> None:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetPropertyStoreForWindow.restype = _HRESULT

    property_store = ctypes.c_void_p()
    result = shell32.SHGetPropertyStoreForWindow(
        wintypes.HWND(handle),
        ctypes.byref(_IID_I_PROPERTY_STORE),
        ctypes.byref(property_store),
    )
    _raise_for_hresult(result, "SHGetPropertyStoreForWindow")
    if not property_store.value:
        raise OSError("SHGetPropertyStoreForWindow returned an empty property store.")

    vtable = ctypes.cast(
        property_store,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
    set_value = ctypes.WINFUNCTYPE(
        _HRESULT,
        ctypes.c_void_p,
        ctypes.POINTER(_PropertyKey),
        ctypes.POINTER(_PropVariant),
    )(vtable[6])
    commit = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p)(vtable[7])

    try:
        for key, value in properties:
            text_buffer = ctypes.create_unicode_buffer(str(value))
            variant = _PropVariant()
            variant.variant_type = _VT_LPWSTR
            variant.pwsz_value = ctypes.cast(text_buffer, wintypes.LPWSTR)
            result = set_value(
                property_store,
                ctypes.byref(key),
                ctypes.byref(variant),
            )
            _raise_for_hresult(result, "IPropertyStore.SetValue")
        _raise_for_hresult(commit(property_store), "IPropertyStore.Commit")
    finally:
        release(property_store)


def _raise_for_hresult(result: int, operation: str) -> None:
    if int(result) < 0:
        code = ctypes.c_ulong(int(result)).value
        raise OSError(f"{operation} failed with HRESULT 0x{code:08x}.")
