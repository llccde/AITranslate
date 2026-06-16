# AITranslate

Windows-only real-time screen OCR + Google Translate desktop app (PyQt6).

## Run

```powershell
python main.py
```

## Project structure

| File | Purpose |
|---|---|
| `main.py` | Entrypoint + `WindowTranslator` — UI assembly, signal wiring, auto-timer, countdown, WDA affinity |
| `translation_engine.py` | `TranslationEngine(QObject)` — state machine: capture → OCR → translate pipeline on daemon threads |
| `window_manager.py` | `WindowManager(QObject)` — window/region selection, indicator overlay, mouse listener |
| `overlay_controller.py` | `OverlayController(QObject)` — lifecycle wrapper around `TranslationOverlayManager` |
| `hotkey_controller.py` | `HotkeyController(QObject)` — Shift+F1 global hotkey lifecycle |
| `lifecycle.py` | `Lifecycle(ABC)` — RAII base class with `start()`/`stop()`/`close()` and context manager |
| `capture.py` | `ScreenCapture` + `set_window_display_affinity()` — hide/show windows, screenshot with region clamping |
| `overlay.py` | `TranslationOverlayManager` + `_LineFrame` — floating translation overlay widgets on target window |
| `cache_tab.py` | `CacheTab(QWidget)` — two-list display, CSV-backed translation cache |
| `translation_task.py` | `TranslationTask` — parallel translate with `ThreadPoolExecutor`, cache integration |
| `config.py` | OCR lang, target lang, interval, `GoogleTranslator` instance |
| `region_selector.py` | Fullscreen translucent overlay for drag-selecting a screen region |
| `utils.py` | `get_true_window_rect()`, `clean_text()`, `clamp_rect_to_window()` |

## Key gotchas

- **Windows-only** — depends on `win32gui`, `win32con`, `pynput`, `ctypes.windll.dwmapi`
- **System requirement**: [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) must be installed (set path in `config.py` if not in `PATH`)
- **No requirements.txt** — deps: `PyQt6`, `Pillow`, `pytesseract`, `deep-translator`, `pywin32`, `pynput`
- **No tests, no linter, no formatter config**
- **Run as admin** for region selection overlay to work on some windows
- **Threading**: OCR+translate runs in daemon threads; results cross thread boundary via PyQt signals (`ocr_text_signal`, `translation_ready`, `screenshot_preview`)
- **DPI**: `get_true_window_rect` returns physical pixels; Qt window APIs use logical pixels — conversion via `self.dpr = screen.devicePixelRatio()`
- **Cache reset**: triggered on every window or region change
