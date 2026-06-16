from typing import Any, List, Optional

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QColor, QPainterPath, QPaintEvent
import ctypes
import traceback
from ctypes import wintypes

from utils import is_window_foreground

GWLP_HWNDPARENT = -8


class TranslationOverlayManager:
    MODE_NONE: int = 0
    MODE_HOVER_HIDE: int = 1
    MODE_HOVER_SHOW: int = 2
    MODE_ALWAYS: int = 3

    STYLE_DARK: str = 'dark'
    STYLE_LIGHT: str = 'light'

    _window: QWidget
    _frames: list['_LineFrame']
    _labels: list[QLabel]
    _results: Optional[list[dict[str, Any]]]
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

        self._frames = []
        self._labels = []
        self._results = None
        self._mode = self.MODE_ALWAYS
        self._style = self.STYLE_DARK
        self._bg_opacity = 50
        self._target_focused = None

        self._window.hide()

    @property
    def widget(self) -> QWidget:
        return self._window

    def set_style(self, style: str) -> None:
        self._style = style
        for frame in self._frames:
            frame._style = style
            frame.update()
        self._apply_label_styles()

    def set_bg_opacity(self, opacity: int) -> None:
        self._bg_opacity = max(0, min(100, opacity))
        for frame in self._frames:
            frame._opacity = self._bg_opacity
            frame.update()

    def set_mode(self, mode: int) -> None:
        self._mode = mode
        if mode == self.MODE_NONE:
            self.hide_all()

    def set_results(self, results: list[dict[str, Any]]) -> None:
        self._results = results
        self._target_focused = None
        self._sync_frames(len(results))

    def set_line_text(self, index: int, text: str) -> None:
        if index < len(self._labels):
            self._labels[index].setText(text)
        if self._results and index < len(self._results):
            self._results[index]['translated'] = text

    def update_geometry(self, x: int, y: int, w: int, h: int,
                        target_hwnd: int, dpr: float) -> None:
        if not self._results or self._mode == self.MODE_NONE:
            self._window.hide()
            return

        self._window.setGeometry(x, y, w, h)

        for i, line in enumerate(self._results):
            if i >= len(self._frames):
                break
            frame = self._frames[i]
            label = self._labels[i]

            rx = int(line['rel_x'] / dpr)
            ry = int(line['rel_y'] / dpr)
            rw = max(30, int(line['rel_w'] / dpr))
            rh = max(16, int(line['rel_h'] / dpr))

            frame.setGeometry(rx, ry, rw, rh)
            label.setText(line['translated'])
            self._fit_font(label, line['translated'] or '', rw, rh)

        if self._mode == self.MODE_NONE:
            self._window.hide()
        elif self._mode == self.MODE_ALWAYS:
            self._window.show()
            for f in self._frames:
                f.show()
            self._fix_z_order(target_hwnd)
        else:
            self._window.show()
            self._fix_z_order(target_hwnd)

    def update_hover(self, cursor_x: int, cursor_y: int) -> None:
        if self._mode in (self.MODE_ALWAYS, self.MODE_NONE) or not self._results:
            return

        win_x = self._window.x()
        win_y = self._window.y()

        for i, frame in enumerate(self._frames):
            if i >= len(self._results):
                break
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
        for f in self._frames:
            f.hide()

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

    def _sync_frames(self, count: int) -> None:
        while len(self._frames) > count:
            self._frames.pop().deleteLater()
            self._labels.pop()
        while len(self._frames) < count:
            frame = _LineFrame(self._window, self._style, self._bg_opacity)
            label = QLabel(frame)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.setSpacing(0)
            layout.addWidget(label)
            self._frames.append(frame)
            self._labels.append(label)
        self._apply_label_styles()

    def _apply_label_styles(self) -> None:
        if self._style == self.STYLE_DARK:
            ss = "color: rgba(255, 255, 255, 255); background: transparent;"
        else:
            ss = "color: rgba(0, 0, 0, 255); background: transparent;"
        for label in self._labels:
            label.setStyleSheet(ss)


class _LineFrame(QWidget):
    _style: str
    _opacity: int

    def __init__(self, parent: QWidget, style: str, opacity: int) -> None:
        super().__init__(parent)
        self._style = style
        self._opacity = opacity
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, a0: QPaintEvent) -> None: # type: ignore
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
