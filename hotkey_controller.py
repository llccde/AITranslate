from typing import Optional

from pynput.keyboard import GlobalHotKeys
from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyController(QObject):
    """Manages the Shift+F1 global hotkey listener lifecycle."""

    triggered = pyqtSignal()

    _listener: Optional[GlobalHotKeys]
    _enabled: bool

    def __init__(self) -> None:
        super().__init__()
        self._listener = None
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        if self._listener is not None:
            return
        self._listener = GlobalHotKeys({
            '<shift>+<f1>': self._on_hotkey,
        })
        self._listener.start()

    def _stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_hotkey(self) -> None:
        self.triggered.emit()

    def close(self) -> None:
        self._stop()
