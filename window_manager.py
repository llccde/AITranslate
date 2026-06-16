import win32gui
import win32con
from typing import Any, Optional

from pynput import mouse
from pynput.mouse import Listener as MouseListener

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QObject, pyqtSignal, QRect, Qt

from utils import get_true_window_rect, clamp_rect_to_window
from region_selector import RegionSelector


class WindowManager(QObject):
    """Manages target-window / region selection and the floating
    indicator rectangle.  Owns the indicator QWidget and its
    transient pynput / RegionSelector resources."""

    window_selected = pyqtSignal(str)
    region_changed = pyqtSignal()

    _dpr: float
    _hwnd: Optional[int]
    _region: Optional[QRect]
    _listener: Optional[MouseListener]
    _selector: Optional[RegionSelector]
    _main_hwnd: Optional[int]
    _indicator: QWidget

    def __init__(self, dpr: float) -> None:
        super().__init__()
        self._dpr = dpr
        self._hwnd = None
        self._region = None
        self._listener = None
        self._selector = None
        self._main_hwnd = None

        self._indicator = QWidget()
        self._indicator.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self._indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._indicator.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._indicator.setStyleSheet(
            "background-color: rgba(0, 120, 215, 60); border: 1px solid rgba(0, 120, 215, 150);"
        )
        self._indicator.hide()

    # ---------- properties ----------

    @property
    def hwnd(self) -> Optional[int]:
        return self._hwnd

    @property
    def region(self) -> Optional[QRect]:
        return self._region

    @property
    def indicator_hwnd(self) -> int:
        return int(self._indicator.winId())

    @property
    def indicator_widget(self) -> QWidget:
        return self._indicator

    # ---------- window selection ----------

    def start_window_selection(self, main_hwnd: int) -> None:
        self._main_hwnd = main_hwnd
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.start()

    def _on_click(self, x: int, y: int, button: 'Any',
                  pressed: bool) -> bool:
        if pressed:
            hwnd = win32gui.WindowFromPoint((x, y))
            if self._main_hwnd is not None and hwnd == self._main_hwnd:
                return False
            if hwnd == int(self._indicator.winId()):
                return False
            hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
            self._hwnd = hwnd
            title = win32gui.GetWindowText(hwnd)
            self.window_selected.emit(title)
            return False
        return False

    # ---------- region selection ----------

    def start_region_selection(self) -> None:
        self._selector = RegionSelector()
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.show()
        self._selector.raise_()

    def _on_region_selected(self, screen_rect: Optional[QRect]) -> None:
        if screen_rect is None or self._hwnd is None:
            self._region = None
            self._indicator.hide()
        else:
            ratio = self._dpr
            physical_rect = QRect(
                int(screen_rect.x() * ratio),
                int(screen_rect.y() * ratio),
                int(screen_rect.width() * ratio),
                int(screen_rect.height() * ratio),
            )
            win_rect = get_true_window_rect(self._hwnd)
            win_left, win_top = win_rect[0], win_rect[1]
            rel_x = physical_rect.x() - win_left
            rel_y = physical_rect.y() - win_top
            rel_w = physical_rect.width()
            rel_h = physical_rect.height()
            self._region = QRect(rel_x, rel_y, rel_w, rel_h)

        self._selector = None
        self.region_changed.emit()

    # ---------- indicator ----------

    def update_indicator(self) -> None:
        if self._hwnd is None or self._region is None:
            self._indicator.hide()
            return
        try:
            win_rect = get_true_window_rect(self._hwnd)
            x_phys = win_rect[0] + self._region.x()
            y_phys = win_rect[1] + self._region.y()
            w_phys = self._region.width()
            h_phys = self._region.height()

            clamped = clamp_rect_to_window(
                (x_phys, y_phys, w_phys, h_phys), win_rect,
            )
            if clamped is None:
                self._indicator.hide()
                return
            cx, cy, cw, ch = clamped
            ratio = self._dpr
            self._indicator.setGeometry(
                int(cx / ratio), int(cy / ratio),
                int(cw / ratio), int(ch / ratio),
            )
            self._indicator.show()
        except Exception:
            import traceback
            traceback.print_exc()
            self._indicator.hide()

    def hide_indicator(self) -> None:
        self._indicator.hide()

    # ---------- lifecycle ----------

    def stop(self) -> None:
        if self._listener and self._listener.is_alive():
            self._listener.stop()
            self._listener = None

    def close(self) -> None:
        self.stop()
        self._indicator.close()
