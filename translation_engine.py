import threading
import traceback
from typing import Any, Callable, Optional, cast

from PIL.ImageQt import ImageQt
import pytesseract
from PyQt6.QtCore import QObject, pyqtSignal, QRect
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from cache_tab import CacheTab
from config import OCR_LANG, API_PARALLEL_LIMIT, TARGET_LANG
import config as app_config
from deep_translator import GoogleTranslator
from capture import ScreenCapture
from translation_task import TranslationTask
from deepseek_translator import DeepSeekTranslator
from utils import clean_text, is_target_language


def _lang_display(code: str) -> str:
    mapping: dict[str, str] = {
        'chi_sim': '中文', 'chi_tra': '繁体中文',
        'jpn': '日语', 'jpn_vert': '日语',
        'eng': '英语',
        'kor': '韩语',
        'fra': '法语', 'deu': '德语', 'spa': '西班牙语',
        'rus': '俄语', 'por': '葡萄牙语',
        'zh-CN': '中文', 'zh-TW': '繁体中文',
        'ja': '日语', 'en': '英语', 'ko': '韩语',
        'fr': '法语', 'de': '德语', 'es': '西班牙语',
        'ru': '俄语', 'pt': '葡萄牙语',
    }
    return mapping.get(code, code)


def _source_lang_display() -> str:
    """Derive a human-readable source language name from OCR_LANG."""
    langs = [l.strip() for l in OCR_LANG.split('+') if l.strip()]
    names = [_lang_display(l) for l in langs]
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return '、'.join(unique) if unique else '文本'


def _translate_via_deepseek(engine: 'TranslationEngine',
                            lines: list[dict[str, Any]],
                            init_results: list[dict[str, Any]],
                            force: bool,
                            generation: int,
                            _emit_line_done: Callable[[int, str, dict[str, Any]], None],
                            _progress: Callable[[int, int], None],
                            _on_cache_entry: Callable[[str, str, bool], None]) -> None:
    total = len(lines)
    uncached_items: list[dict[str, Any]] = []
    completed = 0

    for i, line in enumerate(lines):
        if generation != engine._generation:
            return
        cached = engine._cache_tab.get_from_cache(line['text'])
        if cached and not force:
            init_results[i]['translated'] = cached
            completed += 1
            _emit_line_done(i, cached, line)
            _on_cache_entry(line['text'], cached, True)
        elif not force and is_target_language(line['text'], TARGET_LANG):
            init_results[i]['translated'] = line['text']
            completed += 1
            _emit_line_done(i, line['text'], line)
        else:
            uncached_items.append({'id': i, 'text': line['text']})

    _progress(completed, total)

    if not uncached_items:
        return

    translator = DeepSeekTranslator(app_config.DEEPSEEK_API_KEY)

    def on_line(idx: int, translated_text: str) -> None:
        if generation != engine._generation:
            return
        line_info = lines[idx]
        init_results[idx]['translated'] = translated_text
        _emit_line_done(idx, translated_text, line_info)
        _on_cache_entry(line_info['text'], translated_text, False)
        nonlocal completed
        completed += 1
        _progress(completed, total)

    def on_prompt(prompt_text: str) -> None:
        if generation == engine._generation:
            engine.deepseek_prompt.emit(prompt_text)

    def on_stream(chunk: str) -> None:
        if generation == engine._generation:
            engine.deepseek_stream.emit(chunk)

    translator.translate_batch(
        items=uncached_items,
        source_lang=_source_lang_display(),
        target_lang=_lang_display(TARGET_LANG),
        on_line=on_line,
        on_cancelled=lambda: generation != engine._generation,
        on_prompt=on_prompt,
        on_stream=on_stream,
    )


class TranslationEngine(QObject):
    """State machine that manages the capture → OCR → translate pipeline.
    Runs the heavy work on a daemon thread; all results cross the thread
    boundary via Qt signals."""

    translation_ready = pyqtSignal(str)
    translation_progress = pyqtSignal(int, int)
    line_translations_ready = pyqtSignal(list)
    line_overlay_text = pyqtSignal(int, str)
    translation_done = pyqtSignal()
    cache_hit = pyqtSignal()
    api_call = pyqtSignal()
    screenshot_preview = pyqtSignal(QPixmap)
    ocr_text_signal = pyqtSignal(str)
    deepseek_prompt = pyqtSignal(str)
    deepseek_stream = pyqtSignal(str)

    IDLE: str = 'idle'
    RUNNING: str = 'running'

    _cache_tab: 'CacheTab'
    _hwnd: Optional[int]
    _region: Optional[QRect]
    _dpr: float
    _hide_mode: str
    _main_hwnd: Optional[int]
    _indicator_hwnd: Optional[int]
    _api_parallel: int
    _state: str
    _generation: int
    _pending: bool
    _last_text: str
    _guard_check: Callable[[], bool]

    def __init__(self, cache_tab: 'CacheTab') -> None:
        super().__init__()
        self._cache_tab = cache_tab

        self._hwnd = None
        self._region = None
        self._dpr = 1.0
        self._hide_mode = 'wda'
        self._main_hwnd = None
        self._indicator_hwnd = None
        self._api_parallel = API_PARALLEL_LIMIT

        self._state = self.IDLE
        self._generation = 0
        self._pending = False
        self._last_text = ""
        self._guard_check = lambda: True

        self.translation_done.connect(self._on_translation_done)

    # ---------- configuration ----------

    def configure(self, *, hwnd: Optional[int] = None,
                  region: Optional[QRect] = None,
                  dpr: Optional[float] = None,
                  hide_mode: Optional[str] = None,
                  main_hwnd: Optional[int] = None,
                  indicator_hwnd: Optional[int] = None,
                  api_parallel: Optional[int] = None,
                  guard_check: Optional[Callable[[], bool]] = None) -> None:
        if hwnd is not None:
            self._hwnd = hwnd
        if region is not None:
            self._region = region
        if dpr is not None:
            self._dpr = dpr
        if hide_mode is not None:
            self._hide_mode = hide_mode
        if main_hwnd is not None:
            self._main_hwnd = main_hwnd
        if indicator_hwnd is not None:
            self._indicator_hwnd = indicator_hwnd
        if api_parallel is not None:
            self._api_parallel = api_parallel
        if guard_check is not None:
            self._guard_check = guard_check

    # ---------- public API ----------

    @property
    def is_running(self) -> bool:
        return self._state == self.RUNNING

    def request(self, force: bool = False) -> None:
        """Request a translation cycle. If busy, non-force requests are
        queued; force requests cancel the current run and start a new one."""
        if self._hwnd is None:
            return
        if self._state == self.RUNNING:
            if force:
                self._generation += 1
            else:
                self._pending = True
                return
        self._execute(force)

    def cancel(self) -> None:
        """Cancel any in-flight translation and reset to idle."""
        self._generation += 1
        self._pending = False
        self._state = self.IDLE

    def reset_last_text(self) -> None:
        self._last_text = ""

    # ---------- internal ----------

    def _execute(self, force: bool) -> None:
        self._state = self.RUNNING
        self._generation += 1
        gen = self._generation
        self.translation_progress.emit(0, 0)

        hide_on_capture = (self._hide_mode == 'hide')
        threading.Thread(
            target=self._run,
            args=(force, gen, hide_on_capture),
            daemon=True,
        ).start()

    def _run(self, force: bool, generation: int, hide_on_capture: bool) -> None:
        try:
            capture = ScreenCapture(
                cast(int, self._hwnd), self._region,
                self._main_hwnd,
                self._indicator_hwnd if self._region is not None else None,
            )
            img = capture.capture(hide_windows=hide_on_capture)
            if img is None:
                if generation == self._generation:
                    self.translation_ready.emit("[提示] 选取区域已移出窗口范围")
                return

            img_rgb = img.convert("RGB")
            qimage = ImageQt(img_rgb)
            pixmap = QPixmap.fromImage(qimage)
            scaled = pixmap.scaled(
                640, 480,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.screenshot_preview.emit(scaled)

            data = pytesseract.image_to_data(
                img, lang=OCR_LANG, output_type=pytesseract.Output.DICT,
            )
            lines = self._extract_lines_from_data(data)
            if not lines:
                if generation == self._generation:
                    self.translation_ready.emit("")
                return

            full_text = '\n'.join(line['text'] for line in lines)
            if not full_text:
                if generation == self._generation:
                    self.translation_ready.emit("")
                return
            if not force and full_text == self._last_text:
                if generation == self._generation:
                    self.translation_ready.emit("")
                return
            self._last_text = full_text
            self.ocr_text_signal.emit(full_text)

            init_results: list[dict[str, Any]] = [{
                'original': l['text'],
                'translated': '…',
                'rel_x': l['x'],
                'rel_y': l['y'],
                'rel_w': l['w'],
                'rel_h': l['h'],
            } for l in lines]
            self.line_translations_ready.emit(init_results)

            def _emit_line_done(idx: int, translated: str,
                                line_info: dict[str, Any]) -> None:
                if generation == self._generation:
                    self.line_overlay_text.emit(idx, translated)

            def _progress(c: int, t: int) -> None:
                if generation == self._generation:
                    self.translation_progress.emit(c, t)

            def _on_cache_entry(original: str, translated: str,
                                from_cache: bool) -> None:
                if generation == self._generation:
                    self._cache_tab.translation_cache[original] = translated
                    if from_cache:
                        self.cache_hit.emit()
                    else:
                        self._cache_tab._save_cache_entry(original, translated)
                        self.api_call.emit()

            if app_config.TRANSLATE_ENGINE == 'deepseek':
                _translate_via_deepseek(
                    self, lines, init_results, force, generation,
                    _emit_line_done, _progress, _on_cache_entry,
                )
                line_results = [r for r in init_results
                                if r['translated'] != '…' or r['original']]
                if not line_results:
                    line_results = init_results

                full_translated = '\n'.join(
                    r['translated'] or '' for r in line_results
                )
                self.translation_ready.emit(full_translated)
            else:
                task = TranslationTask(
                    lines=lines,
                    force=force,
                    cache_get=self._cache_tab.get_from_cache,
                    cache_set=self._cache_store,
                    translate_fn=lambda text: (
                        text if is_target_language(text, TARGET_LANG)
                        else GoogleTranslator(
                            source='auto', target=TARGET_LANG,
                        ).translate(text)
                    ),
                    max_workers=self._api_parallel,
                    on_progress=_progress,
                    on_line_done=_emit_line_done,
                    on_cancelled=lambda: generation != self._generation,
                    on_cache_entry=_on_cache_entry,
                )
                result = task.execute()
                if result is None or generation != self._generation:
                    return

                line_results, _, _ = result

                full_translated = '\n'.join(
                    r['translated'] or '' for r in line_results
                )
                self.translation_ready.emit(full_translated)
        except Exception:
            traceback.print_exc()
            if generation == self._generation:
                self.translation_ready.emit(f"[错误] {traceback.format_exc()}")
        finally:
            if generation == self._generation:
                self.translation_done.emit()

    def _cache_store(self, text: str, translated: str) -> None:
        self._cache_tab.translation_cache[text] = translated

    def _on_translation_done(self) -> None:
        """Called on main thread after worker finishes."""
        self._state = self.IDLE
        if self._pending:
            self._pending = False
            if self._guard_check():
                self._execute(force=False)

    @staticmethod
    def _extract_lines_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
        lines: dict[tuple, dict] = {}
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            if not text or int(data['conf'][i]) < 0:
                continue
            key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            left = data['left'][i]
            right = left + data['width'][i]
            top = data['top'][i]
            bottom = top + data['height'][i]
            if key not in lines:
                lines[key] = {'words': []}
            lines[key]['words'].append((text, left, right, top, bottom))

        result: list[dict[str, Any]] = []
        for key in sorted(lines.keys()):
            words = sorted(lines[key]['words'], key=lambda w: w[1])
            if not words:
                continue

            segments: list[tuple] = []
            seg_texts: list[str] = [words[0][0]]
            seg_left = words[0][1]
            seg_top = words[0][3]
            seg_right = words[0][2]
            seg_bottom = words[0][4]

            for w in words[1:]:
                text, left, right, top, bottom = w
                gap = left - seg_right
                line_h = seg_bottom - seg_top
                if gap > line_h * 1.5:
                    segments.append((seg_texts, seg_left, seg_top, seg_right, seg_bottom))
                    seg_texts = [text]
                    seg_left = left
                    seg_top = top
                    seg_right = right
                    seg_bottom = bottom
                else:
                    seg_texts.append(text)
                    seg_right = max(seg_right, right)
                    seg_top = min(seg_top, top)
                    seg_bottom = max(seg_bottom, bottom)

            segments.append((seg_texts, seg_left, seg_top, seg_right, seg_bottom))

            for words_list, l, t, r, b in segments:
                line_text = clean_text(' '.join(words_list))
                if not line_text or len(line_text) < 2:
                    continue
                result.append({
                    'text': line_text,
                    'x': l,
                    'y': t,
                    'w': r - l,
                    'h': b - t,
                })
        return result
