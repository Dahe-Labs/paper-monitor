"""Small Windows named-mutex helpers shared by tray and window processes."""

from __future__ import annotations

import os

ERROR_ALREADY_EXISTS = 183
TRAY_MUTEX_NAME = "Local\\PaperMonitorTray"
WINDOW_MUTEX_NAME = "Local\\PaperMonitorDashboardWindow"
REFRESH_MUTEX_NAME = "Local\\PaperMonitorRefresh"


def acquire_mutex(name: str):
    handle = create_mutex(name)
    if not handle:
        return None
    if last_error() == ERROR_ALREADY_EXISTS:
        close_handle(handle)
        return None
    return handle


def is_mutex_running(name: str) -> bool:
    handle = open_mutex(name)
    if not handle:
        return False
    close_handle(handle)
    return True


def create_mutex(name: str):
    if os.name != "nt":
        return object()
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return object()

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    return kernel32.CreateMutexW(None, False, name)


def open_mutex(name: str):
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    synchronize = 0x00100000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    return kernel32.OpenMutexW(synchronize, False, name)


def last_error() -> int:
    if os.name != "nt":
        return 0
    try:
        import ctypes
    except ImportError:
        return 0
    return int(ctypes.get_last_error())


def close_handle(handle) -> None:
    if os.name != "nt" or not handle:
        return
    try:
        import ctypes
    except ImportError:
        return
    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
