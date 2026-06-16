from abc import ABC, abstractmethod
from typing import Any


class Lifecycle(ABC):
    """RAII-style lifecycle: acquire resources in start(), release in stop(),
    final cleanup in close(). Usable as context manager."""

    _active: bool

    def __init__(self) -> None:
        self._active = False

    def start(self) -> None:
        """Acquire runtime resources. Idempotent."""
        if self._active:
            return
        self._on_start()
        self._active = True

    def stop(self) -> None:
        """Release runtime resources. Idempotent."""
        if not self._active:
            return
        self._active = False
        self._on_stop()

    def close(self) -> None:
        """Final cleanup: calls stop() then releases all resources.
        After close(), the object should not be reused."""
        self.stop()
        self._on_close()

    @property
    def is_active(self) -> bool:
        return self._active

    @abstractmethod
    def _on_start(self) -> None: ...

    @abstractmethod
    def _on_stop(self) -> None: ...

    @abstractmethod
    def _on_close(self) -> None: ...

    def __enter__(self) -> 'Lifecycle':
        self.start()
        return self

    def __exit__(self, *args: Any) -> bool:
        self.close()
        return False
