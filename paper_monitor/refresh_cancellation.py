"""Cooperative cancellation shared by refresh orchestration and source adapters."""

from __future__ import annotations

import time


class RefreshCancelled(RuntimeError):
    """Raised when the current refresh has been asked to stop."""


class RefreshCancellation:
    """No-op cancellation token used outside the Windows installed runtime."""

    def is_requested(self) -> bool:
        return False

    def checkpoint(self) -> None:
        if self.is_requested():
            raise RefreshCancelled("Paper Monitor refresh was cancelled.")

    def wait(self, seconds: float) -> None:
        delay = max(0.0, float(seconds))
        if delay:
            time.sleep(delay)
        self.checkpoint()

    def close(self) -> None:
        return
