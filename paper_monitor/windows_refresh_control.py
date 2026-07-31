"""Windows named-event adapter for cooperatively stopping a refresh process."""

from __future__ import annotations

import os

from .refresh_cancellation import RefreshCancellation

REFRESH_STOP_EVENT_NAME = "Local\\PaperMonitorRefreshStop"
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class WindowsRefreshCancellation(RefreshCancellation):
    """Cancellation token backed by one process-shared Windows event."""

    def __init__(self, handle=None) -> None:
        self._handle = handle if handle is not None else _create_stop_event()

    def is_requested(self) -> bool:
        if os.name != "nt" or not self._handle:
            return False
        result = _wait_for_handle(self._handle, 0)
        return result == WAIT_OBJECT_0

    def wait(self, seconds: float) -> None:
        delay = max(0.0, float(seconds))
        if os.name != "nt" or not self._handle:
            super().wait(delay)
            return
        result = _wait_for_handle(self._handle, _milliseconds(delay))
        if result not in {WAIT_OBJECT_0, WAIT_TIMEOUT}:
            raise OSError("Could not wait for the Paper Monitor refresh stop event.")
        self.checkpoint()

    def close(self) -> None:
        handle, self._handle = self._handle, None
        _close_handle(handle)


def create_refresh_cancellation() -> RefreshCancellation:
    if os.name != "nt":
        return RefreshCancellation()
    return WindowsRefreshCancellation()


def request_refresh_stop() -> bool:
    """Signal an active refresh, returning False when no refresh owns the event."""

    if os.name != "nt":
        return False
    handle = _open_stop_event()
    if not handle:
        return False
    try:
        return bool(_set_event(handle))
    finally:
        _close_handle(handle)


def _milliseconds(seconds: float) -> int:
    return min(0xFFFFFFFE, max(0, int(round(float(seconds) * 1000))))


def _create_stop_event():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    handle = kernel32.CreateEventW(None, True, False, REFRESH_STOP_EVENT_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _open_stop_event():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    return kernel32.OpenEventW(
        EVENT_MODIFY_STATE | SYNCHRONIZE,
        False,
        REFRESH_STOP_EVENT_NAME,
    )


def _set_event(handle) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    return bool(kernel32.SetEvent(handle))


def _wait_for_handle(handle, milliseconds: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return int(kernel32.WaitForSingleObject(handle, milliseconds))


def _close_handle(handle) -> None:
    if os.name != "nt" or not handle:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)
