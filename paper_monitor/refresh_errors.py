from __future__ import annotations

from typing import Mapping, Optional


class RefreshAlreadyRunning(RuntimeError):
    """Raised when another process already owns the application refresh."""

    def __init__(self, message: str, state: Optional[Mapping[str, object]] = None):
        super().__init__(message)
        self.state = dict(state) if state is not None else None


class RefreshSourcesFailed(RuntimeError):
    """Raised when every configured article source failed during a refresh."""

    def __init__(self, message: str, result: Optional[Mapping[str, object]] = None):
        super().__init__(message)
        self.result = dict(result) if result is not None else None
