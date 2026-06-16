import ctypes
import traceback
from ctypes import wintypes
from typing import Optional, Tuple

from PIL import ImageGrab, Image
from PIL.Image import Image as PilImage
import win32gui
import win32con
from PyQt6.QtCore import QRect

from utils import get_true_window_rect, clamp_rect_to_window

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def set_window_display_affinity(hwnd: Optional[int], exclude_from_capture: bool) -> bool:
    if hwnd is None:
        return False
    affinity = WDA_EXCLUDEFROMCAPTURE if exclude_from_capture else WDA_NONE
    try:
        result = ctypes.windll.user32.SetWindowDisplayAffinity(
            wintypes.HWND(hwnd),
            wintypes.DWORD(affinity)
        )
        return result != 0
    except Exception:
        traceback.print_exc()
        return False


class ScreenCapture:
    hwnd: int
    region: Optional[QRect]
    main_hwnd: Optional[int]
    indicator_hwnd: Optional[int]

    def __init__(self, hwnd: int, region: Optional[QRect] = None,
                 main_hwnd: Optional[int] = None,
                 indicator_hwnd: Optional[int] = None) -> None:
        self.hwnd = hwnd
        self.region = region
        self.main_hwnd = main_hwnd
        self.indicator_hwnd = indicator_hwnd

    def get_capture_rect(self) -> Optional[Tuple[int, int, int, int]]:
        win_rect = get_true_window_rect(self.hwnd)
        if self.region is None:
            return win_rect

        win_left, win_top = win_rect[0], win_rect[1]
        cap_left = win_left + self.region.x()
        cap_top = win_top + self.region.y()
        cap_w = self.region.width()
        cap_h = self.region.height()

        clamped = clamp_rect_to_window((cap_left, cap_top, cap_w, cap_h), win_rect)
        if clamped is None:
            return None
        cx, cy, cw, ch = clamped
        return (cx, cy, cx + cw, cy + ch)

    def capture(self, hide_windows: bool = False) -> Optional[PilImage]:
        capture_rect = self.get_capture_rect()
        if capture_rect is None:
            return None

        if hide_windows:
            self._set_windows_visible(False)

        try:
            return ImageGrab.grab(bbox=capture_rect)
        finally:
            if hide_windows:
                self._set_windows_visible(True)

    def _set_windows_visible(self, visible: bool) -> None:
        show_flag = win32con.SW_SHOWNOACTIVATE if visible else win32con.SW_HIDE
        if self.main_hwnd is not None:
            win32gui.ShowWindow(self.main_hwnd, show_flag)
        if self.indicator_hwnd is not None:
            win32gui.ShowWindow(self.indicator_hwnd, show_flag)
