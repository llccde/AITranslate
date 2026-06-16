import ctypes
from ctypes import wintypes
from typing import Optional, Tuple

import win32gui
import win32con
from cleantext import clean

dwmapi = ctypes.windll.dwmapi
DWMWA_EXTENDED_FRAME_BOUNDS = 9


def get_true_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    rect = wintypes.RECT()
    dwmapi.DwmGetWindowAttribute(
        hwnd,
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect)
    )
    return (rect.left, rect.top, rect.right, rect.bottom)


def clean_text(text: str) -> str:
    return clean(text,
        clean_all=False,
        extra_spaces=True,
    )


def clamp_rect_to_window(rect: Tuple[int, int, int, int], win_rect: Tuple[int, int, int, int]) -> Optional[Tuple[int, int, int, int]]:
    """Clamp (x, y, w, h) to window bounds (left, top, right, bottom).
    Returns (x, y, w, h) or None if out of bounds."""
    win_left, win_top, win_right, win_bottom = win_rect
    x, y, w, h = rect
    x2, y2 = x + w, y + h

    x = max(win_left, x)
    y = max(win_top, y)
    x2 = min(win_right, x2)
    y2 = min(win_bottom, y2)

    w = x2 - x
    h = y2 - y
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def is_window_foreground(hwnd: int) -> bool:
    fg = win32gui.GetForegroundWindow()
    if fg == hwnd:
        return True
    if not fg or not win32gui.IsWindow(fg):
        return False
    if not win32gui.IsWindow(hwnd):
        return False
    return win32gui.GetAncestor(fg, win32con.GA_ROOT) == hwnd


def is_target_language(text: str, target_lang: str) -> bool:
    if not text or len(text) < 2:
        return True
    target = target_lang.split('-')[0]
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    kana = sum(1 for c in text if '\u3040' <= c <= '\u30ff')
    hangul = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04ff')
    total = max(cjk + kana + hangul + latin + cyrillic, 1)
    if target == 'ja':
        return (cjk + kana) / total > 0.5 and kana > 0
    if target == 'ko':
        return hangul / total > 0.5
    if target == 'zh':
        return cjk / total > 0.5 and kana == 0
    if target == 'ru':
        return cyrillic / total > 0.5
    return latin / total > 0.7
