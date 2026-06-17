import sys
import time
import traceback
from typing import Any, Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QTabWidget, QComboBox, QSlider,
    QLineEdit, QGroupBox, QSplitter, QCheckBox, QFrame,
    QStackedWidget, QButtonGroup,
)
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtGui import QPixmap, QCloseEvent, QTextCursor

from config import (
    INTERVAL, API_PARALLEL_LIMIT, FOCUS_GUARD_ENABLED,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_THINKING, TRANSLATE_ENGINE,
    OCR_LANG, AVAILABLE_OCR_LANGS,
    save_settings,
)
from utils import is_window_foreground
from capture import set_window_display_affinity
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
    _base_url: str
    _thinking: bool
    _quick_dirty: bool
    _main_hwnd: int

    tab_widget: QTabWidget
    translate_tab: QWidget
    label: QLabel
    select_win_btn: QPushButton
    select_region_btn: QPushButton
    abort_btn: QPushButton
    status_label: QLabel
    preview_tab: QWidget
    cache_preview_label: QLabel
    ai_tab: QWidget
    ai_prompt_edit: QTextEdit
    ai_stream_edit: QTextEdit
    ai_usage_label: QLabel
    quick_settings_frame: QFrame
    engine_quick_combo: QComboBox
    apply_btn: QPushButton
    quick_stack: QStackedWidget
    quick_api_key_input: QLineEdit
    advanced_toggle_btn: QPushButton
    advanced_container: QWidget
    base_url_input: QLineEdit
    thinking_checkbox: QCheckBox
    mt_source_group: QButtonGroup
    google_checkbox: QCheckBox
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
        self.window_manager = WindowManager(self.dpr)
        self.overlay_controller = OverlayController()
        self.translation_engine = TranslationEngine()
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
        self._base_url = DEEPSEEK_BASE_URL
        self._thinking = DEEPSEEK_THINKING
        self._quick_dirty = False

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

        # ---- 左右分栏 ----
        split_layout = QHBoxLayout()

        # 左半边
        left_panel = QVBoxLayout()

        # 框1：窗口操作
        box1 = QFrame()
        box1.setObjectName("leftBox1")
        box1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        box1.setFrameShape(QFrame.Shape.StyledPanel)
        box1.setStyleSheet("#leftBox1 { border: 1px solid #ccc; border-radius: 8px; }")
        b1_layout = QVBoxLayout(box1)
        self.select_win_btn = QPushButton("选择窗口")
        self.select_win_btn.setMinimumHeight(60)
        self.select_win_btn.setStyleSheet(
            "QPushButton { font-size: 18px; font-weight: bold; color: white; "
            "background-color: #3498db; border: none; border-radius: 6px; padding: 6px; }"
            "QPushButton:hover { background-color: #2980b9; }"
            "QPushButton:pressed { background-color: #1c6ea4; }"
        )
        b1_layout.addWidget(self.select_win_btn)
        self.select_region_btn = QPushButton("划定区域")
        self.select_region_btn.setMinimumHeight(32)
        self.select_region_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; color: #3498db; "
            "background-color: #eaf2fb; border: 1px solid #3498db; border-radius: 6px; padding: 4px; }"
            "QPushButton:hover { background-color: #d4e6f9; }"
            "QPushButton:disabled { color: #aaa; border-color: #ccc; background-color: #f0f0f0; }"
        )
        self.select_region_btn.setEnabled(False)
        b1_layout.addWidget(self.select_region_btn)
        left_panel.addWidget(box1)

        # 框2：状态 + 终止
        box2 = QFrame()
        box2.setObjectName("leftBox2")
        box2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        box2.setFrameShape(QFrame.Shape.StyledPanel)
        box2.setStyleSheet("#leftBox2 { border: 1px solid #ccc; border-radius: 8px; }")
        b2_layout = QVBoxLayout(box2)
        self.status_label = QLabel("当前任务: 就绪")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.status_label.setStyleSheet("color: gray;")
        b2_layout.addWidget(self.status_label)
        abort_row = QHBoxLayout()
        self.abort_btn = QPushButton("终止")
        self.abort_btn.setEnabled(False)
        abort_row.addWidget(self.abort_btn)
        b2_layout.addLayout(abort_row)
        left_panel.addWidget(box2)

        split_layout.addLayout(left_panel, 1)

        # 右半边：快速设置
        self.quick_settings_frame = QFrame()
        self.quick_settings_frame.setObjectName("quickSettingsFrame")
        self.quick_settings_frame.setFrameShape(QFrame.Shape.StyledPanel)
        qs_layout = QVBoxLayout(self.quick_settings_frame)

        engine_row = QHBoxLayout()
        self.engine_quick_combo = QComboBox()
        self.engine_quick_combo.addItems(["AI 翻译", "机翻"])
        self.engine_quick_combo.setCurrentIndex(1 if self._translate_engine == "google" else 0)
        engine_row.addWidget(self.engine_quick_combo, 2)
        self.apply_btn = QPushButton("应用")
        engine_row.addWidget(self.apply_btn, 1)
        qs_layout.addLayout(engine_row)

        self.quick_stack = QStackedWidget()

        # --- AI 翻译页 ---
        ai_page = QWidget()
        ai_layout = QVBoxLayout(ai_page)
        ai_layout.setContentsMargins(0, 4, 0, 0)
        self.quick_api_key_input = QLineEdit()
        self.quick_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.quick_api_key_input.setPlaceholderText("API Key (sk-...)")
        self.quick_api_key_input.setText(self._deepseek_api_key)
        ai_layout.addWidget(self.quick_api_key_input)

        self.advanced_toggle_btn = QPushButton("高级设置 ▼")
        self.advanced_toggle_btn.setStyleSheet("text-align: left; font-weight: bold; padding: 2px;")
        ai_layout.addWidget(self.advanced_toggle_btn)

        self.advanced_container = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_container)
        advanced_layout.setContentsMargins(4, 0, 0, 0)
        advanced_layout.addWidget(QLabel("Base URL:"))
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://api.deepseek.com/v1")
        self.base_url_input.setText(self._base_url)
        advanced_layout.addWidget(self.base_url_input)
        self.thinking_checkbox = QCheckBox("启用思考模式 (reasoner)")
        self.thinking_checkbox.setChecked(self._thinking)
        advanced_layout.addWidget(self.thinking_checkbox)
        self.advanced_container.setVisible(False)
        ai_layout.addWidget(self.advanced_container)
        ai_layout.addStretch()
        self.quick_stack.addWidget(ai_page)

        # --- 机翻页 ---
        mt_page = QWidget()
        mt_layout = QVBoxLayout(mt_page)
        mt_layout.setContentsMargins(0, 4, 0, 0)
        mt_layout.addWidget(QLabel("翻译源（单选）："))
        self.mt_source_group = QButtonGroup(mt_page)
        self.mt_source_group.setExclusive(True)
        self.google_checkbox = QCheckBox("Google 翻译")
        self.google_checkbox.setChecked(True)
        self.mt_source_group.addButton(self.google_checkbox)
        mt_layout.addWidget(self.google_checkbox)
        mt_layout.addStretch()
        self.quick_stack.addWidget(mt_page)

        qs_layout.addWidget(self.quick_stack)
        split_layout.addWidget(self.quick_settings_frame, 1)

        tl.addLayout(split_layout)

        self.tab_widget.addTab(self.translate_tab, "翻译")

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

        self.ai_usage_label = QLabel("")
        self.ai_usage_label.setStyleSheet("color: #666; font-size: 12px; padding: 2px;")
        ai_layout.addWidget(self.ai_usage_label)

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
        self.select_win_btn.clicked.connect(self._on_select_win_toggle)
        self.select_region_btn.clicked.connect(self._on_select_region)
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
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        self.api_key_input.textChanged.connect(self._on_api_key_changed)

        # -- quick settings --
        self.engine_quick_combo.currentIndexChanged.connect(self._on_quick_engine_changed)
        self.apply_btn.clicked.connect(self._on_quick_apply)
        self.advanced_toggle_btn.clicked.connect(self._on_advanced_toggle)
        self.quick_api_key_input.textChanged.connect(lambda: self._mark_dirty())
        self.base_url_input.textChanged.connect(lambda: self._mark_dirty())
        self.thinking_checkbox.toggled.connect(lambda: self._mark_dirty())
        self.google_checkbox.toggled.connect(lambda: self._mark_dirty())

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
        self.translation_engine.line_translations_ready.connect(
            self.overlay_controller.set_results)
        self.translation_engine.line_overlay_text.connect(
            self.overlay_controller.set_line_text)
        self.translation_engine.deepseek_prompt.connect(self._on_deepseek_prompt)
        self.translation_engine.deepseek_stream.connect(self._on_deepseek_stream)
        self.translation_engine.deepseek_usage.connect(self._on_deepseek_usage)

        # -- hotkey --
        self.hotkey_controller.triggered.connect(self._on_hotkey_triggered)

    # ==================================================================
    #  Translation lifecycle
    # ==================================================================

    def _reset_and_start(self) -> None:
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
        self.status_label.setText("当前任务: 就绪")
        self.status_label.setStyleSheet("color: #5b7a9a; font-weight: bold;")
        self.abort_btn.setEnabled(False)
        self.abort_btn.setStyleSheet("")
        self._set_button_states(False)
        self.label.setText("翻译已停止，可重新选择窗口")

    def _on_abort_translation(self) -> None:
        if not self.translation_engine.is_running:
            return
        self.translation_engine.cancel()
        self.abort_btn.setEnabled(False)
        self.abort_btn.setStyleSheet("")
        self.status_label.setText("当前任务: 已终止")
        self.status_label.setStyleSheet("color: #5b7a9a;")

    def _set_button_states(self, running: bool) -> None:
        if running:
            self.select_win_btn.setText("更换窗口")
            self.select_win_btn.setStyleSheet(
                "QPushButton { font-size: 18px; font-weight: bold; color: white; "
                "background-color: #27ae60; border: none; border-radius: 6px; padding: 6px; }"
                "QPushButton:hover { background-color: #219a52; }"
                "QPushButton:pressed { background-color: #1a7a40; }"
            )
        else:
            self.select_win_btn.setText("选择窗口")
            self.select_win_btn.setStyleSheet(
                "QPushButton { font-size: 18px; font-weight: bold; color: white; "
                "background-color: #3498db; border: none; border-radius: 6px; padding: 6px; }"
                "QPushButton:hover { background-color: #2980b9; }"
                "QPushButton:pressed { background-color: #1c6ea4; }"
            )
        self.select_region_btn.setEnabled(running)
        self.abort_btn.setEnabled(running)

    # ==================================================================
    #  UI event handlers
    # ==================================================================

    def _on_select_win_toggle(self) -> None:
        if self.running:
            self.stop_translation()
        else:
            self._on_select_window()

    def _on_select_window(self) -> None:
        self.showMinimized()
        self.label.setText("请在目标窗口上点击一下...")
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
        pass

    def _on_translation_progress(self, completed: int, total: int) -> None:
        self.abort_btn.setEnabled(True)
        self.abort_btn.setStyleSheet(
            "QPushButton { color: white; background-color: #e74c3c; "
            "border: none; border-radius: 4px; padding: 3px 8px; font-weight: bold; }"
            "QPushButton:hover { background-color: #c0392b; }"
        )
        if completed == 0 and total == 0:
            self.status_label.setText("当前任务: OCR识别中")
            self.status_label.setStyleSheet("color: #3498db; font-weight: bold;")
        elif total > 0:
            self.status_label.setText(f"当前任务: 已完成翻译 {completed}/{total}")
            self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.status_label.setText("当前任务: 正在翻译")
            self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")

    def _on_screenshot_preview(self, pixmap: QPixmap) -> None:
        self.cache_preview_label.setPixmap(pixmap)

    def _on_translation_done(self) -> None:
        self.abort_btn.setEnabled(False)
        self.abort_btn.setStyleSheet("")
        if self._timer_paused:
            self._timer_paused = False
            if self.running and self.auto_translate_enabled:
                self._auto_timer.start(int(self.current_interval * 1000))
        if self.running and self.auto_translate_enabled:
            self._last_capture_time = time.time()

    def _on_deepseek_prompt(self, prompt_text: str) -> None:
        self.ai_prompt_edit.setPlainText(prompt_text)
        self.ai_stream_edit.clear()
        self.ai_usage_label.setText("")

    def _on_deepseek_stream(self, chunk: str) -> None:
        self.ai_stream_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.ai_stream_edit.insertPlainText(chunk)

    def _on_deepseek_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        USD_TO_CNY = 7.25
        API_INPUT_PRICE = 0.27
        API_OUTPUT_PRICE = 1.10
        cost_usd = (prompt_tokens * API_INPUT_PRICE + completion_tokens * API_OUTPUT_PRICE) / 1_000_000
        cost_cny = cost_usd * USD_TO_CNY
        self.ai_usage_label.setText(
            f"Token消耗：输入 {prompt_tokens} + 输出 {completion_tokens} = "
            f"共 {prompt_tokens + completion_tokens} token"
            f"  |  费用：¥{cost_cny:.2f}"
        )

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
    #  Hotkey
    # ==================================================================

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
        self.engine_quick_combo.blockSignals(True)
        self.engine_quick_combo.setCurrentIndex(1 if self._translate_engine == 'google' else 0)
        self.engine_quick_combo.blockSignals(False)
        self._clear_dirty()
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

    # ==================================================================
    #  Quick settings handlers
    # ==================================================================

    def _mark_dirty(self) -> None:
        if self._quick_dirty:
            return
        self._quick_dirty = True
        self.quick_settings_frame.setStyleSheet(
            "#quickSettingsFrame { border: 2px solid #e74c3c; border-radius: 8px; }"
        )

    def _clear_dirty(self) -> None:
        self._quick_dirty = False
        self.quick_settings_frame.setStyleSheet("")

    def _on_quick_engine_changed(self, index: int) -> None:
        self.quick_stack.setCurrentIndex(index)
        self._mark_dirty()

    def _on_advanced_toggle(self) -> None:
        visible = not self.advanced_container.isVisible()
        self.advanced_container.setVisible(visible)
        self.advanced_toggle_btn.setText("高级设置 ▲" if visible else "高级设置 ▼")

    def _on_quick_apply(self) -> None:
        new_engine = 'google' if self.engine_quick_combo.currentIndex() == 1 else 'deepseek'
        new_api_key = self.quick_api_key_input.text().strip()
        new_base_url = self.base_url_input.text().strip()
        new_thinking = self.thinking_checkbox.isChecked()

        self._translate_engine = new_engine
        self._deepseek_api_key = new_api_key
        self._base_url = new_base_url
        self._thinking = new_thinking

        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(1 if new_engine == 'deepseek' else 0)
        self.engine_combo.blockSignals(False)
        self.deepseek_group.setVisible(new_engine == 'deepseek')
        self.api_key_input.blockSignals(True)
        self.api_key_input.setText(new_api_key)
        self.api_key_input.blockSignals(False)

        self._save_settings()
        self._clear_dirty()

    # ==================================================================
    #  Settings persistence
    # ==================================================================

    def _save_settings(self) -> None:
        import config
        config.DEEPSEEK_API_KEY = self._deepseek_api_key
        config.DEEPSEEK_BASE_URL = self._base_url
        config.DEEPSEEK_THINKING = self._thinking
        config.TRANSLATE_ENGINE = self._translate_engine
        config.save_settings()

    # ==================================================================
    #  Countdown
    # ==================================================================

    def _update_countdown(self) -> None:
        if not self.running or not self.auto_translate_enabled:
            self.status_label.setText("当前任务: 就绪")
            self.status_label.setStyleSheet("color: #5b7a9a; font-weight: bold;")
            return
        if not self._should_translate():
            self.status_label.setText("当前任务: 等待获取焦点")
            self.status_label.setStyleSheet("color: #e67e22;")
            return
        elapsed = time.time() - self._last_capture_time
        remaining = max(0, self.current_interval - elapsed)
        if self.translation_engine.is_running and remaining <= 0:
            self.status_label.setText("当前任务: 等待已发起完成")
            self.status_label.setStyleSheet("color: #e67e22;")
        else:
            self.status_label.setText(f"当前任务: {remaining:.1f}s")
            self.status_label.setStyleSheet("color: #e67e22; font-weight: bold;")

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
