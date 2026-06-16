import sys
import time
import traceback
from typing import Any, Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QTabWidget, QComboBox, QSlider,
    QLineEdit, QGroupBox, QSplitter, QCheckBox,
)
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QPixmap, QCloseEvent, QTextCursor

from config import (
    INTERVAL, API_PARALLEL_LIMIT, FOCUS_GUARD_ENABLED,
    DEEPSEEK_API_KEY, TRANSLATE_ENGINE, OCR_LANG, AVAILABLE_OCR_LANGS,
    save_settings,
)
from utils import is_window_foreground
from capture import set_window_display_affinity
from cache_tab import CacheTab
from overlay import TranslationOverlayManager
from translation_engine import TranslationEngine, reset_readers
from window_manager import WindowManager
from overlay_controller import OverlayController
from hotkey_controller import HotkeyController


class WindowTranslator(QWidget):
    """Main window — assembles UI and wires sub-controllers together.
    Responsibilities: layout, signal wiring, auto-timer, countdown,
    hide-mode (WDA) affinity, and top-level lifecycle coordination."""

    dpr: float
    cache_tab: CacheTab
    window_manager: WindowManager
    overlay_controller: OverlayController
    translation_engine: TranslationEngine
    hotkey_controller: HotkeyController

    running: bool
    auto_translate_enabled: bool
    current_interval: float
    _timer_paused: bool
    _last_capture_time: float
    _hide_mode: str
    _overlay_style: str
    _overlay_mode: int
    _overlay_bg_opacity: int
    _api_parallel: int
    _focus_guard_enabled: bool
    _translate_engine: str
    _deepseek_api_key: str
    _main_hwnd: int

    tab_widget: QTabWidget
    translate_tab: QWidget
    label: QLabel
    text_area: QTextEdit
    select_win_btn: QPushButton
    select_region_btn: QPushButton
    stop_btn: QPushButton
    abort_btn: QPushButton
    countdown_label: QLabel
    progress_label: QLabel
    preview_tab: QWidget
    cache_preview_label: QLabel
    ai_tab: QWidget
    ai_prompt_edit: QTextEdit
    ai_stream_edit: QTextEdit
    settings_tab: QWidget
    hide_mode_combo: QComboBox
    auto_translate_btn: QPushButton
    interval_combo: QComboBox
    hotkey_btn: QPushButton
    overlay_style_combo: QComboBox
    overlay_mode_combo: QComboBox
    opacity_slider: QSlider
    opacity_label: QLabel
    api_slider: QSlider
    api_label: QLabel
    focus_guard_btn: QPushButton
    engine_combo: QComboBox
    ocr_lang_group: QGroupBox
    ocr_lang_checkboxes: dict[str, Any]
    deepseek_group: QGroupBox
    api_key_input: QLineEdit
    api_key_toggle_btn: QPushButton

    _auto_timer: QTimer
    _visual_timer: QTimer
    _countdown_timer: QTimer

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("实时翻译小窗")
        self.resize(400, 520)

        screen = QApplication.primaryScreen()
        self.dpr = screen.devicePixelRatio() if screen else 1.0

        # ---- sub-controllers ----
        self.cache_tab = CacheTab()
        self.window_manager = WindowManager(self.dpr)
        self.overlay_controller = OverlayController()
        self.translation_engine = TranslationEngine(self.cache_tab)
        self.hotkey_controller = HotkeyController()

        # ---- coordinator state ----
        self.running = False
        self.auto_translate_enabled = False
        self.current_interval = INTERVAL
        self._timer_paused = False
        self._last_capture_time = 0.0
        self._hide_mode = 'wda'
        self._overlay_style = 'dark'
        self._overlay_mode = TranslationOverlayManager.MODE_ALWAYS
        self._overlay_bg_opacity = 50
        self._api_parallel = API_PARALLEL_LIMIT
        self._focus_guard_enabled = FOCUS_GUARD_ENABLED
        self._translate_engine = TRANSLATE_ENGINE
        self._deepseek_api_key = DEEPSEEK_API_KEY

        # ---- build UI ----
        self._setup_ui()
        self._connect_signals()

        self.hotkey_controller.set_enabled(True)

        # ---- timers ----
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._on_auto_tick)

        self._visual_timer = QTimer(self)
        self._visual_timer.timeout.connect(self._update_visuals)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start(500)

        # ---- anti-capture (WDA) ----
        self._main_hwnd = int(self.winId())
        self.hide_mode_combo.setCurrentIndex(0)
        self._apply_hide_mode('wda')

    # ==================================================================
    #  UI construction
    # ==================================================================

    def _setup_ui(self) -> None:
        self.tab_widget = QTabWidget()
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tab_widget)

        # --- 翻译 tab ---
        self.translate_tab = QWidget()
        tl = QVBoxLayout(self.translate_tab)

        self.label = QLabel("点击「选择窗口」后，再点击目标窗口")
        self.label.setStyleSheet("color: blue;")
        tl.addWidget(self.label)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        tl.addWidget(self.text_area)

        btn_layout = QHBoxLayout()
        self.select_win_btn = QPushButton("选择窗口")
        self.select_region_btn = QPushButton("划定区域")
        self.stop_btn = QPushButton("停止翻译")
        self.abort_btn = QPushButton("终止")
        self.select_region_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.abort_btn.setEnabled(False)
        btn_layout.addWidget(self.select_win_btn)
        btn_layout.addWidget(self.select_region_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.abort_btn)
        tl.addLayout(btn_layout)

        self.countdown_label = QLabel("就绪")
        self.countdown_label.setFixedWidth(120)
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_label.setStyleSheet("color: gray;")
        tl.addWidget(self.countdown_label)

        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setStyleSheet("color: #336699; font-weight: bold;")
        tl.addWidget(self.progress_label)

        self.tab_widget.addTab(self.translate_tab, "翻译")
        self.tab_widget.addTab(self.cache_tab, "缓存统计")

        # --- 截图预览 tab ---
        self.preview_tab = QWidget()
        pl = QVBoxLayout(self.preview_tab)
        self.cache_preview_label = QLabel("截图预览")
        self.cache_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cache_preview_label.setStyleSheet("border: 1px solid gray;")
        pl.addWidget(self.cache_preview_label)
        self.tab_widget.addTab(self.preview_tab, "截图预览")

        # --- AI 对话 tab ---
        self.ai_tab = QWidget()
        ai_layout = QVBoxLayout(self.ai_tab)

        ai_layout.addWidget(QLabel("发送给 AI 的完整对话 Prompt"))
        self.ai_prompt_edit = QTextEdit()
        self.ai_prompt_edit.setReadOnly(True)
        self.ai_prompt_edit.setPlaceholderText("非 AI 模式时此处为空")
        ai_layout.addWidget(self.ai_prompt_edit, 2)

        ai_layout.addWidget(QLabel("AI 流式输出"))
        self.ai_stream_edit = QTextEdit()
        self.ai_stream_edit.setReadOnly(True)
        self.ai_stream_edit.setPlaceholderText("等待 AI 流式响应...")
        ai_layout.addWidget(self.ai_stream_edit, 3)

        self.tab_widget.addTab(self.ai_tab, "AI 对话")

        # --- 设置 tab ---
        self.settings_tab = QWidget()
        sl = QVBoxLayout(self.settings_tab)

        hide_mode_row = QHBoxLayout()
        hide_mode_row.addWidget(QLabel("防截屏模式:"))
        self.hide_mode_combo = QComboBox()
        self.hide_mode_combo.addItems(["排除捕获 (WDA)", "隐藏窗口", "无"])
        self.hide_mode_combo.setToolTip(
            "WDA: 窗口始终不被截图捕获（Win10 2004+）\n"
            "隐藏窗口: 截图瞬间隐藏本窗\n"
            "无: 不处理，窗口可能被截图捕获"
        )
        hide_mode_row.addWidget(self.hide_mode_combo)
        hide_mode_row.addStretch()
        sl.addLayout(hide_mode_row)

        auto_row = QHBoxLayout()
        self.auto_translate_btn = QPushButton("自动翻译：关")
        self.auto_translate_btn.setCheckable(True)
        self.auto_translate_btn.setChecked(False)
        auto_row.addWidget(self.auto_translate_btn)
        auto_row.addWidget(QLabel("间隔:"))
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1s", "2s", "3s", "5s", "10s"])
        self.interval_combo.setCurrentText(f"{int(INTERVAL)}s")
        auto_row.addWidget(self.interval_combo)
        sl.addLayout(auto_row)

        self.hotkey_btn = QPushButton("快捷键翻译(Shift+F1)：开")
        self.hotkey_btn.setCheckable(True)
        self.hotkey_btn.setChecked(True)
        sl.addWidget(self.hotkey_btn)

        overlay_row = QHBoxLayout()
        overlay_row.addWidget(QLabel("覆盖样式:"))
        self.overlay_style_combo = QComboBox()
        self.overlay_style_combo.addItems(["黑底白字", "白底黑字"])
        overlay_row.addWidget(self.overlay_style_combo)
        overlay_row.addStretch()
        sl.addLayout(overlay_row)

        overlay_mode_row = QHBoxLayout()
        overlay_mode_row.addWidget(QLabel("覆盖模式:"))
        self.overlay_mode_combo = QComboBox()
        self.overlay_mode_combo.addItems(["不覆盖", "悬停隐藏", "悬停显示", "总是显示"])
        self.overlay_mode_combo.setCurrentIndex(3)
        overlay_mode_row.addWidget(self.overlay_mode_combo)
        overlay_mode_row.addStretch()
        sl.addLayout(overlay_mode_row)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("背景透明度:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        opacity_row.addWidget(self.opacity_slider, 1)
        self.opacity_label = QLabel("50%")
        self.opacity_label.setFixedWidth(40)
        opacity_row.addWidget(self.opacity_label)
        sl.addLayout(opacity_row)

        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("API并行上限:"))
        self.api_slider = QSlider(Qt.Orientation.Horizontal)
        self.api_slider.setRange(1, 50)
        self.api_slider.setValue(self._api_parallel)
        api_row.addWidget(self.api_slider, 1)
        self.api_label = QLabel(str(self._api_parallel))
        self.api_label.setFixedWidth(30)
        api_row.addWidget(self.api_label)
        sl.addLayout(api_row)

        focus_row = QHBoxLayout()
        self.focus_guard_btn = QPushButton("前台翻译控制：开")
        self.focus_guard_btn.setCheckable(True)
        self.focus_guard_btn.setChecked(self._focus_guard_enabled)
        self.focus_guard_btn.setToolTip(
            "启用后，仅当目标窗口在前台（获得焦点）时才发起翻译"
        )
        focus_row.addWidget(self.focus_guard_btn)
        focus_row.addStretch()
        sl.addLayout(focus_row)

        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("翻译引擎:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["Google 翻译", "DeepSeek AI"])
        self.engine_combo.setCurrentIndex(0 if self._translate_engine == "google" else 1)
        self.engine_combo.setToolTip("选择翻译引擎：Google 免费翻译 或 DeepSeek AI 翻译")
        engine_row.addWidget(self.engine_combo)
        engine_row.addStretch()
        sl.addLayout(engine_row)

        self.ocr_lang_group = QGroupBox("OCR 识别语言")
        ocr_lang_layout = QVBoxLayout(self.ocr_lang_group)
        ocr_lang_row = QHBoxLayout()
        self.ocr_lang_checkboxes = {}
        for code, name in AVAILABLE_OCR_LANGS.items():
            cb = QCheckBox(name)
            cb.setChecked(code in OCR_LANG)
            cb.setToolTip(f"启用 {name} 文字识别")
            self.ocr_lang_checkboxes[code] = cb
            ocr_lang_row.addWidget(cb)
        ocr_lang_row.addStretch()
        ocr_lang_layout.addLayout(ocr_lang_row)
        sl.addWidget(self.ocr_lang_group)

        self.deepseek_group = QGroupBox("DeepSeek API 设置")
        ds_layout = QVBoxLayout(self.deepseek_group)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        self.api_key_input.setText(self._deepseek_api_key)
        self.api_key_input.setToolTip("DeepSeek API Key，从 platform.deepseek.com 获取")
        key_row.addWidget(self.api_key_input, 1)
        self.api_key_toggle_btn = QPushButton("显示")
        self.api_key_toggle_btn.setCheckable(True)
        self.api_key_toggle_btn.clicked.connect(self._toggle_api_key_visibility)
        key_row.addWidget(self.api_key_toggle_btn)
        ds_layout.addLayout(key_row)
        self.deepseek_group.setVisible(self._translate_engine == "deepseek")
        sl.addWidget(self.deepseek_group)

        sl.addStretch()
        self.tab_widget.addTab(self.settings_tab, "设置")

    # ==================================================================
    #  Signal wiring
    # ==================================================================

    def _connect_signals(self) -> None:
        # -- buttons --
        self.select_win_btn.clicked.connect(self._on_select_window)
        self.select_region_btn.clicked.connect(self._on_select_region)
        self.stop_btn.clicked.connect(self.stop_translation)
        self.abort_btn.clicked.connect(self._on_abort_translation)
        self.auto_translate_btn.clicked.connect(self._toggle_auto_translate)
        self.hotkey_btn.clicked.connect(self._toggle_hotkey)
        self.interval_combo.currentTextChanged.connect(self._on_interval_changed)
        self.hide_mode_combo.currentIndexChanged.connect(self._on_hide_mode_changed)
        self.overlay_style_combo.currentIndexChanged.connect(self._on_overlay_style_changed)
        self.overlay_mode_combo.currentIndexChanged.connect(self._on_overlay_mode_changed)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.api_slider.valueChanged.connect(self._on_api_parallel_changed)
        self.focus_guard_btn.clicked.connect(self._toggle_focus_guard)
        self.cache_tab.force_translate_requested.connect(self._on_force_translate)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        self.api_key_input.textChanged.connect(self._on_api_key_changed)

        for code, cb in self.ocr_lang_checkboxes.items():
            cb.toggled.connect(lambda checked, c=code: self._on_ocr_lang_changed(c, checked))

        # -- window manager --
        self.window_manager.window_selected.connect(self._on_window_selected)
        self.window_manager.region_changed.connect(self._on_region_changed)

        # -- translation engine (cross-thread → main thread) --
        self.translation_engine.translation_ready.connect(self._on_translation_ready)
        self.translation_engine.translation_progress.connect(self._on_translation_progress)
        self.translation_engine.translation_done.connect(self._on_translation_done)
        self.translation_engine.screenshot_preview.connect(self._on_screenshot_preview)
        self.translation_engine.ocr_text_signal.connect(self.cache_tab.on_ocr_text)
        self.translation_engine.cache_hit.connect(self.cache_tab.on_cache_hit)
        self.translation_engine.api_call.connect(self.cache_tab.on_api_call)
        self.translation_engine.line_translations_ready.connect(
            self.overlay_controller.set_results)
        self.translation_engine.line_overlay_text.connect(
            self.overlay_controller.set_line_text)
        self.translation_engine.deepseek_prompt.connect(self._on_deepseek_prompt)
        self.translation_engine.deepseek_stream.connect(self._on_deepseek_stream)

        # -- hotkey --
        self.hotkey_controller.triggered.connect(self._on_hotkey_triggered)

    # ==================================================================
    #  Translation lifecycle
    # ==================================================================

    def _reset_and_start(self) -> None:
        self.cache_tab.reset_stats()
        self._start_translation()

    def _start_translation(self) -> None:
        hwnd = self.window_manager.hwnd
        if hwnd is None:
            return
        self.running = True
        self._last_capture_time = 0

        self.translation_engine.configure(
            hwnd=hwnd,
            region=self.window_manager.region,
            dpr=self.dpr,
            hide_mode=self._hide_mode,
            main_hwnd=self._main_hwnd,
            indicator_hwnd=self.window_manager.indicator_hwnd,
            api_parallel=self._api_parallel,
            guard_check=self._should_translate,
        )
        self.overlay_controller.configure(
            hwnd, self.window_manager.region, self.dpr,
        )

        self._visual_timer.start(50)
        if self.auto_translate_enabled:
            self._auto_timer.start(int(self.current_interval * 1000))

        self._set_button_states(True)

        if self.auto_translate_enabled:
            self._last_capture_time = time.time()
            self.translation_engine.request(force=False)

    def stop_translation(self) -> None:
        self.running = False
        self._auto_timer.stop()
        self._visual_timer.stop()
        self.window_manager.hide_indicator()
        self.translation_engine.cancel()
        self.overlay_controller.hide_all()
        self._timer_paused = False
        self.progress_label.setText("")
        self.abort_btn.setEnabled(False)
        self._set_button_states(False)
        self.label.setText("翻译已停止，可重新选择窗口")

    def _on_abort_translation(self) -> None:
        if not self.translation_engine.is_running:
            return
        self.translation_engine.cancel()
        self.abort_btn.setEnabled(False)
        self.progress_label.setText("已终止")

    def _set_button_states(self, running: bool) -> None:
        self.select_win_btn.setEnabled(not running)
        self.select_region_btn.setEnabled(running)
        self.stop_btn.setEnabled(running)

    # ==================================================================
    #  UI event handlers
    # ==================================================================

    def _on_select_window(self) -> None:
        self.showMinimized()
        self.label.setText("请在目标窗口上点击一下...")
        self.select_win_btn.setEnabled(False)
        self.window_manager.start_window_selection(self._main_hwnd)

    def _on_select_region(self) -> None:
        if self.window_manager.hwnd is None:
            return
        was_running = self.running
        if was_running:
            self.stop_translation()

        self.setEnabled(False)
        self.label.setText("请在目标窗口上拖拽选择翻译区域，按 ESC 取消并使用全窗口")
        self.window_manager.start_region_selection()

    def _on_window_selected(self, title: str) -> None:
        self.showNormal()
        self.label.setText(f"已选择窗口：{title[:30]}  默认全窗口翻译")
        self.window_manager.hide_indicator()
        self.translation_engine.reset_last_text()
        self._reset_and_start()

    def _on_region_changed(self) -> None:
        self.setEnabled(True)
        region = self.window_manager.region
        if region is None:
            self.label.setText("区域选择已取消，使用全窗口翻译")
            self.window_manager.hide_indicator()
        else:
            self.label.setText(
                f"翻译区域已设定：({region.x()},{region.y()}) "
                f"{region.width()}x{region.height()}"
            )
        self._reset_and_start()

    # ==================================================================
    #  Translation engine signal handlers (main thread)
    # ==================================================================

    def _on_translation_ready(self, text: str) -> None:
        self.text_area.setPlainText(text)
        self.cache_tab.on_translation_ready(
            self.cache_tab.current_original, text,
        )

    def _on_translation_progress(self, completed: int, total: int) -> None:
        self.abort_btn.setEnabled(True)
        if total > 0:
            self.progress_label.setText(f"已完成翻译 {completed}/{total}")
        else:
            self.progress_label.setText("")

    def _on_screenshot_preview(self, pixmap: QPixmap) -> None:
        self.cache_preview_label.setPixmap(pixmap)

    def _on_translation_done(self) -> None:
        self.abort_btn.setEnabled(False)
        if self._timer_paused:
            self._timer_paused = False
            if self.running and self.auto_translate_enabled:
                self._auto_timer.start(int(self.current_interval * 1000))
        if self.running and self.auto_translate_enabled:
            self._last_capture_time = time.time()

    def _on_deepseek_prompt(self, prompt_text: str) -> None:
        self.ai_prompt_edit.setPlainText(prompt_text)
        self.ai_stream_edit.clear()

    def _on_deepseek_stream(self, chunk: str) -> None:
        self.ai_stream_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.ai_stream_edit.insertPlainText(chunk)

    # ==================================================================
    #  Auto-timer
    # ==================================================================

    def _on_auto_tick(self) -> None:
        if not self.running or self.window_manager.hwnd is None:
            return
        if not self.auto_translate_enabled:
            return
        if not self._should_translate():
            return
        was_idle = not self.translation_engine.is_running
        self.translation_engine.request(force=False)
        if was_idle:
            self._last_capture_time = time.time()

    # ==================================================================
    #  Visuals (indicator + overlay)
    # ==================================================================

    def _update_visuals(self) -> None:
        if not self.running:
            return
        self.window_manager.update_indicator()
        self.overlay_controller.update_geometry()

    def changeEvent(self, a0: QEvent) -> None: # type: ignore
        if a0.type() == QEvent.Type.WindowStateChange:
            if not (self.windowState() & Qt.WindowState.WindowMinimized):
                if self.running and self.window_manager.hwnd is not None:
                    self.overlay_controller.update_geometry()

    # ==================================================================
    #  Focus guard
    # ==================================================================

    def _should_translate(self) -> bool:
        if not self._focus_guard_enabled:
            return True
        hwnd = self.window_manager.hwnd
        if hwnd is None:
            return False
        try:
            return is_window_foreground(hwnd)
        except Exception:
            return True

    # ==================================================================
    #  Force / hotkey
    # ==================================================================

    def _on_force_translate(self) -> None:
        if self.window_manager.hwnd is None:
            return
        if not self._should_translate():
            return
        if self.running and self.auto_translate_enabled:
            self._auto_timer.stop()
            self._timer_paused = True
        if not self.running:
            self.running = True
            self._visual_timer.start(50)
            self._set_button_states(True)
        self._last_capture_time = time.time()
        self.translation_engine.request(force=True)

    def _on_hotkey_triggered(self) -> None:
        if self.window_manager.hwnd is None:
            return
        if not self._should_translate():
            return
        if self.translation_engine.is_running:
            return
        if self.running and self.auto_translate_enabled:
            self._auto_timer.stop()
            self._timer_paused = True
        if not self.running:
            self.running = True
            self._visual_timer.start(50)
            self._set_button_states(True)
        self._last_capture_time = time.time()
        self.translation_engine.request(force=True)

    # ==================================================================
    #  Settings handlers
    # ==================================================================

    def _toggle_auto_translate(self) -> None:
        self.auto_translate_enabled = self.auto_translate_btn.isChecked()
        if self.auto_translate_enabled:
            self.auto_translate_btn.setText("自动翻译：开")
            if self.running:
                self._auto_timer.start(int(self.current_interval * 1000))
                self._last_capture_time = time.time()
        else:
            self.auto_translate_btn.setText("自动翻译：关")
            self._auto_timer.stop()

    def _toggle_hotkey(self) -> None:
        enabled = self.hotkey_btn.isChecked()
        self.hotkey_btn.setText(
            f"快捷键翻译(Shift+F1)：{'开' if enabled else '关'}"
        )
        self.hotkey_controller.set_enabled(enabled)

    def _on_interval_changed(self, text: str) -> None:
        self.current_interval = float(text.replace('s', ''))
        if self.running and self.auto_translate_enabled:
            self._auto_timer.start(int(self.current_interval * 1000))
            self._last_capture_time = time.time()

    def _on_hide_mode_changed(self, index: int) -> None:
        modes = ['wda', 'hide', 'none']
        self._hide_mode = modes[index]
        self._apply_hide_mode(self._hide_mode)
        if self.running:
            self.translation_engine.configure(hide_mode=self._hide_mode)

    def _on_overlay_style_changed(self, index: int) -> None:
        self._overlay_style = 'dark' if index == 0 else 'light'
        self.overlay_controller.set_style(self._overlay_style)

    def _on_overlay_mode_changed(self, index: int) -> None:
        modes = [
            TranslationOverlayManager.MODE_NONE,
            TranslationOverlayManager.MODE_HOVER_HIDE,
            TranslationOverlayManager.MODE_HOVER_SHOW,
            TranslationOverlayManager.MODE_ALWAYS,
        ]
        self._overlay_mode = modes[index]
        self.overlay_controller.set_mode(self._overlay_mode)

    def _on_opacity_changed(self, value: int) -> None:
        self._overlay_bg_opacity = value
        self.opacity_label.setText(f"{value}%")
        self.overlay_controller.set_bg_opacity(value)

    def _on_api_parallel_changed(self, value: int) -> None:
        self._api_parallel = value
        self.api_label.setText(str(value))
        if self.running:
            self.translation_engine.configure(api_parallel=value)

    def _toggle_focus_guard(self) -> None:
        self._focus_guard_enabled = self.focus_guard_btn.isChecked()
        self.focus_guard_btn.setText(
            f"前台翻译控制：{'开' if self._focus_guard_enabled else '关'}"
        )

    def _on_engine_changed(self, index: int) -> None:
        self._translate_engine = 'google' if index == 0 else 'deepseek'
        self.deepseek_group.setVisible(self._translate_engine == 'deepseek')
        self._save_settings()

    def _on_api_key_changed(self, text: str) -> None:
        self._deepseek_api_key = text.strip()
        self._save_settings()

    def _toggle_api_key_visibility(self) -> None:
        show = self.api_key_toggle_btn.isChecked()
        self.api_key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )
        self.api_key_toggle_btn.setText("隐藏" if show else "显示")

    def _on_ocr_lang_changed(self, code: str, checked: bool) -> None:
        import config
        if checked:
            if code not in config.OCR_LANG:
                config.OCR_LANG.append(code)
        else:
            if code in config.OCR_LANG and len(config.OCR_LANG) > 1:
                config.OCR_LANG.remove(code)
            else:
                cb = self.ocr_lang_checkboxes.get(code)
                if cb is not None:
                    cb.blockSignals(True)
                    cb.setChecked(True)
                    cb.blockSignals(False)
                return
        reset_readers()
        self._save_settings()

    def _save_settings(self) -> None:
        import config
        config.DEEPSEEK_API_KEY = self._deepseek_api_key
        config.TRANSLATE_ENGINE = self._translate_engine
        config.save_settings()

    # ==================================================================
    #  Countdown
    # ==================================================================

    def _update_countdown(self) -> None:
        if not self.running or not self.auto_translate_enabled:
            self.countdown_label.setText("就绪")
            self.countdown_label.setStyleSheet("color: gray;")
            return
        if not self._should_translate():
            self.countdown_label.setText("等待获取焦点")
            self.countdown_label.setStyleSheet("color: orange;")
            return
        elapsed = time.time() - self._last_capture_time
        remaining = max(0, self.current_interval - elapsed)
        if self.translation_engine.is_running and remaining <= 0:
            self.countdown_label.setText("等待已发起完成")
            self.countdown_label.setStyleSheet("color: orange;")
        else:
            self.countdown_label.setText(f"{remaining:.1f}s")
            if remaining < 0.5:
                self.countdown_label.setStyleSheet("color: red;")
            else:
                self.countdown_label.setStyleSheet("color: gray;")

    # ==================================================================
    #  Hide-mode (WDA) affinity
    # ==================================================================

    def _apply_hide_mode(self, mode: str) -> None:
        exclude = (mode == 'wda')
        set_window_display_affinity(self._main_hwnd, exclude)
        set_window_display_affinity(self.window_manager.indicator_hwnd, exclude)
        set_window_display_affinity(self.overlay_controller.overlay_hwnd, exclude)

    # ==================================================================
    #  Close / cleanup
    # ==================================================================

    def closeEvent(self, a0: QCloseEvent) -> None: # type: ignore
        self.stop_translation()
        self.hotkey_controller.close()
        set_window_display_affinity(self._main_hwnd, False)
        set_window_display_affinity(self.window_manager.indicator_hwnd, False)
        set_window_display_affinity(self.overlay_controller.overlay_hwnd, False)
        self.overlay_controller.close()
        self.window_manager.close()
        super().closeEvent(a0)


# ======================================================================
#  Entrypoint
# ======================================================================

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = WindowTranslator()
        window.show()
        sys.exit(app.exec())
    except Exception:
        traceback.print_exc()
        input("按回车键退出...")
        sys.exit(1)
