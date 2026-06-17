from typing import Any, Dict, Optional, Tuple, Union

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QColor, QPainterPath, QPaintEvent
import ctypes
import traceback
from ctypes import wintypes

from utils import is_window_foreground

GWLP_HWNDPARENT = -8

RectType = Union[QRect, QRectF, Tuple[int, int, int, int]]


class TranslationOverlayManager:
    MODE_NONE: int = 0
    MODE_HOVER_HIDE: int = 1
    MODE_HOVER_SHOW: int = 2
    MODE_ALWAYS: int = 3

    STYLE_DARK: str = 'dark'
    STYLE_LIGHT: str = 'light'

    _window: QWidget
    _items: Dict[int, Dict[str, Any]]
    _next_id: int
    _mode: int
    _style: str
    _bg_opacity: int
    _target_focused: Optional[bool]

    def __init__(self) -> None:
        self._window = QWidget()
        self._window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self._window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._items = {}
        self._next_id = 1
        self._mode = self.MODE_ALWAYS
        self._style = self.STYLE_DARK
        self._bg_opacity = 50
        self._target_focused = None

        self._window.hide()

    @property
    def widget(self) -> QWidget:
        return self._window

    @property
    def count(self) -> int:
        return len(self._items)

    def set_style(self, style: str) -> None:
        self._style = style
        for item in self._items.values():
            item['frame']._style = style
            item['frame'].update()
        self._apply_label_styles()

    def set_bg_opacity(self, opacity: int) -> None:
        self._bg_opacity = max(0, min(100, opacity))
        for item in self._items.values():
            item['frame']._opacity = self._bg_opacity
            item['frame'].update()

    def set_mode(self, mode: int) -> None:
        self._mode = mode
        if mode == self.MODE_NONE:
            self.hide_all()

    # ---------- label CRUD ----------

    def addLable(self, text: str, rect: RectType) -> int:
        if isinstance(rect, (QRect, QRectF)):
            rx, ry, rw, rh = rect.x(), rect.y(), rect.width(), rect.height()
        else:
            rx, ry, rw, rh = rect

        rw = max(30, int(rw))
        rh = max(16, int(rh))

        fid = self._next_id
        self._next_id += 1

        frame = _LineFrame(self._window, self._style, self._bg_opacity)
        label = QLabel(frame)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        layout.addWidget(label)

        frame.setGeometry(int(rx), int(ry), rw, rh)
        label.setText(text)
        self._fit_font(label, text, rw, rh)

        self._items[fid] = {
            'frame': frame,
            'label': label,
            'text': text,
            'rect': (int(rx), int(ry), rw, rh),
        }

        self._apply_label_styles()

        return fid

    def replace(self, fid: int, newText: Optional[str] = None,
                newRect: Optional[RectType] = None) -> None:
        if fid not in self._items:
            return
        item = self._items[fid]

        if newText is not None:
            item['text'] = newText
            item['label'].setText(newText)

        if newRect is not None:
            if isinstance(newRect, (QRect, QRectF)):
                rx, ry, rw, rh = newRect.x(), newRect.y(), newRect.width(), newRect.height()
            else:
                rx, ry, rw, rh = newRect
            rw = max(30, int(rw))
            rh = max(16, int(rh))
            item['rect'] = (int(rx), int(ry), rw, rh)
            item['frame'].setGeometry(int(rx), int(ry), rw, rh)

        rx, ry, rw, rh = item['rect']
        self._fit_font(item['label'], item['text'], rw, rh)

    def delet(self, fid: int) -> None:
        if fid not in self._items:
            return
        item = self._items.pop(fid)
        item['frame'].hide()
        item['frame'].deleteLater()

    def clearall(self) -> None:
        for item in self._items.values():
            item['frame'].hide()
            item['frame'].deleteLater()
        self._items.clear()

    # ---------- geometry / visibility ----------

    def update_geometry(self, x: int, y: int, w: int, h: int,
                        target_hwnd: int) -> None:
        if not self._items or self._mode == self.MODE_NONE:
            self._window.hide()
            return

        self._window.setGeometry(x, y, w, h)

        if self._mode == self.MODE_NONE:
            self._window.hide()
        elif self._mode == self.MODE_ALWAYS:
            self._window.show()
            for item in self._items.values():
                item['frame'].show()
            self._fix_z_order(target_hwnd)
        else:
            self._window.show()
            self._fix_z_order(target_hwnd)

    def update_hover(self, cursor_x: int, cursor_y: int) -> None:
        if self._mode in (self.MODE_ALWAYS, self.MODE_NONE) or not self._items:
            return

        win_x = self._window.x()
        win_y = self._window.y()

        for item in self._items.values():
            frame = item['frame']
            rx = win_x + frame.x()
            ry = win_y + frame.y()
            rw = frame.width()
            rh = frame.height()
            inside = (rx <= cursor_x <= rx + rw and ry <= cursor_y <= ry + rh)

            if self._mode == self.MODE_HOVER_HIDE:
                should_show = not inside
            else:
                should_show = inside

            frame.setVisible(should_show)

    def hide_all(self) -> None:
        self._window.hide()
        for item in self._items.values():
            item['frame'].hide()

    def winId(self) -> int:
        return int(self._window.winId())

    def _fix_z_order(self, target_hwnd: int) -> None:
        try:
            overlay_hwnd = int(self._window.winId())
            ctypes.windll.user32.SetWindowLongPtrW(
                wintypes.HWND(overlay_hwnd),
                GWLP_HWNDPARENT,
                wintypes.HWND(target_hwnd)
            )
            focused = is_window_foreground(target_hwnd)
            if focused == self._target_focused:
                return
            self._target_focused = focused
            if focused:
                ctypes.windll.user32.SetWindowPos(
                    wintypes.HWND(overlay_hwnd),
                    wintypes.HWND(-1),
                    0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010
                )
            else:
                ctypes.windll.user32.SetWindowPos(
                    wintypes.HWND(overlay_hwnd),
                    wintypes.HWND(target_hwnd),
                    0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010
                )
                ctypes.windll.user32.SetWindowPos(
                    wintypes.HWND(target_hwnd),
                    wintypes.HWND(overlay_hwnd),
                    0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010
                )
        except Exception:
            traceback.print_exc()

    @staticmethod
    def _fit_font(label: QLabel, text: str, w: int, h: int) -> None:
        available_w = max(1, w - 8)
        available_h = max(1, h - 4)
        max_font = min(48, h * 2 // 3)
        min_font = 8

        font = QFont()

        def _fits(size: int) -> bool:
            font.setPixelSize(size)
            fm = QFontMetrics(font)
            bounds = fm.boundingRect(
                QRect(0, 0, available_w, available_h),
                Qt.TextFlag.TextWordWrap, text
            )
            return bounds.width() <= available_w and bounds.height() <= available_h

        if _fits(max_font):
            label.setFont(font)
            return

        lo, hi = min_font, max_font
        best = min_font
        while lo <= hi:
            mid = (lo + hi) // 2
            if _fits(mid):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1

        font.setPixelSize(best)
        label.setFont(font)

    def _apply_label_styles(self) -> None:
        if self._style == self.STYLE_DARK:
            ss = "color: rgba(255, 255, 255, 255); background: transparent;"
        else:
            ss = "color: rgba(0, 0, 0, 255); background: transparent;"
        for item in self._items.values():
            item['label'].setStyleSheet(ss)


class _LineFrame(QWidget):
    _style: str
    _opacity: int

    def __init__(self, parent: QWidget, style: str, opacity: int) -> None:
        super().__init__(parent)
        self._style = style
        self._opacity = opacity
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, a0: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = int(self._opacity * 255 / 100)
        if self._style == 'dark':
            color = QColor(0, 0, 0, alpha)
        else:
            color = QColor(255, 255, 255, alpha)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, -1, -1), 6, 6)
        painter.fillPath(path, color)
