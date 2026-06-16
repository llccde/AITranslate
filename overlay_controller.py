from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtCore import QRect

from overlay import TranslationOverlayManager
from utils import get_true_window_rect


class OverlayController(QObject):
    """Manages the lifecycle of the translation overlay window.
    Wraps TranslationOverlayManager and adds coordinate / hover logic."""

    _mgr: TranslationOverlayManager
    _hwnd: Optional[int]
    _region: Optional[QRect]
    _dpr: float
    _results: Optional[list[dict[str, Any]]]
    _mouse_timer: QTimer

    def __init__(self) -> None:
        super().__init__()
        self._mgr = TranslationOverlayManager()
        self._hwnd = None
        self._region = None
        self._dpr = 1.0
        self._results = None

        self._mouse_timer = QTimer(self)
        self._mouse_timer.timeout.connect(self._check_hover)
        self._mouse_timer.start(100)

    # ---------- properties ----------

    @property
    def overlay_hwnd(self) -> int:
        return int(self._mgr.winId())

    # ---------- configuration ----------

    def configure(self, hwnd: int, region: Optional[QRect], dpr: float) -> None:
        self._hwnd = hwnd
        self._region = region
        self._dpr = dpr

    # ---------- results ----------

    def set_results(self, results: list[dict[str, Any]]) -> None:
        self._results = results
        self._mgr.set_results(results)
        self.update_geometry()

    def set_line_text(self, index: int, text: str) -> None:
        self._mgr.set_line_text(index, text)

    # ---------- geometry ----------

    def update_geometry(self) -> None:
        if self._hwnd is None or self._results is None:
            self._mgr.hide_all()
            return
        try:
            win_rect = get_true_window_rect(self._hwnd)
            ratio = self._dpr
            if self._region: # type: ignore
                cx = int((win_rect[0] + self._region.x()) / ratio)
                cy = int((win_rect[1] + self._region.y()) / ratio)
                cw = max(30, int(self._region.width() / ratio))
                ch = max(16, int(self._region.height() / ratio))
            else:
                cx = int(win_rect[0] / ratio)
                cy = int(win_rect[1] / ratio)
                cw = int((win_rect[2] - win_rect[0]) / ratio)
                ch = int((win_rect[3] - win_rect[1]) / ratio)
            self._mgr.update_geometry(cx, cy, cw, ch, self._hwnd, self._dpr)
        except Exception:
            import traceback
            traceback.print_exc()
            self._mgr.hide_all()

    # ---------- style / mode ----------

    def set_mode(self, mode: int) -> None:
        self._mgr.set_mode(mode)

    def set_style(self, style: str) -> None:
        self._mgr.set_style(style)

    def set_bg_opacity(self, opacity: int) -> None:
        self._mgr.set_bg_opacity(opacity)

    # ---------- hover ----------

    def _check_hover(self) -> None:
        if self._mgr._mode in (
            TranslationOverlayManager.MODE_ALWAYS,
            TranslationOverlayManager.MODE_NONE,
        ):
            return
        if self._results is None:
            return
        cursor_pos = QCursor.pos()
        self._mgr.update_hover(cursor_pos.x(), cursor_pos.y())

    # ---------- lifecycle ----------

    def hide_all(self) -> None:
        self._mgr.hide_all()

    def close(self) -> None:
        self._mouse_timer.stop()
        self._mgr.hide_all()
