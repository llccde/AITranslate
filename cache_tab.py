import csv
import hashlib
import os
import traceback
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QDialog, QTextEdit, QAbstractItemView,
    QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from config import get_translation_config


class CacheTab(QWidget):
    force_translate_requested = pyqtSignal()

    text_cache: list[str]
    translation_cache: dict[str, str]
    current_original: str
    total_strings: int
    current_word_count: int
    api_calls: int
    cache_hits: int
    csv_path: str

    stats_toggle_btn: QPushButton
    stats_container: QWidget
    cache_count_label: QLabel
    word_count_label: QLabel
    total_strings_label: QLabel
    attempts_label: QLabel
    cache_hits_label: QLabel
    force_btn: QPushButton
    current_section_label: QLabel
    current_list: QListWidget
    history_section_label: QLabel
    history_list: QListWidget

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.text_cache = []
        self.translation_cache = {}
        self.current_original = ""
        self.total_strings = 0
        self.current_word_count = 0
        self.api_calls = 0
        self.cache_hits = 0

        self.csv_path = os.path.join(os.path.dirname(__file__), "translation_cache.csv")
        self._load_cache()

        self._setup_ui()

    def _load_cache(self) -> None:
        current_config = get_translation_config()
        if not os.path.exists(self.csv_path):
            return
        try:
            with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("translation_config", "") == current_config:
                        original = row.get("original_text", "")
                        translated = row.get("translated_text", "")
                        if original and translated:
                            self.translation_cache[original] = translated
        except Exception:
            traceback.print_exc()

    def _save_cache_entry(self, original: str, translated: str) -> None:
        config_str = get_translation_config()
        text_hash = hashlib.md5(original.encode("utf-8")).hexdigest()
        try:
            write_header = not os.path.exists(self.csv_path)
            with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["original_text", "translated_text", "text_hash", "translation_config"])
                writer.writerow([original, translated, text_hash, config_str])
        except Exception:
            traceback.print_exc()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.stats_toggle_btn = QPushButton("统计信息 ▲")
        self.stats_toggle_btn.setStyleSheet("font-size: 13px; font-weight: bold; text-align: left; padding: 4px;")
        self.stats_toggle_btn.clicked.connect(self._toggle_stats)
        layout.addWidget(self.stats_toggle_btn)

        self.stats_container = QWidget()
        stats_layout = QVBoxLayout(self.stats_container)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(2)

        self.cache_count_label = QLabel("缓存字符串数：0")
        self.cache_count_label.setStyleSheet("font-size: 14px;")
        stats_layout.addWidget(self.cache_count_label)

        self.word_count_label = QLabel("当前屏幕总字数：0")
        self.word_count_label.setStyleSheet("font-size: 14px;")
        stats_layout.addWidget(self.word_count_label)

        self.total_strings_label = QLabel("总处理字符串数：0")
        self.total_strings_label.setStyleSheet("font-size: 14px;")
        stats_layout.addWidget(self.total_strings_label)

        self.attempts_label = QLabel("API调用次数：0")
        self.attempts_label.setStyleSheet("font-size: 14px;")
        stats_layout.addWidget(self.attempts_label)

        self.cache_hits_label = QLabel("缓存命中次数：0")
        self.cache_hits_label.setStyleSheet("font-size: 14px;")
        stats_layout.addWidget(self.cache_hits_label)

        layout.addWidget(self.stats_container)

        self.force_btn = QPushButton("覆盖缓存")
        self.force_btn.setToolTip("终止当前翻译，冻结计时，发起无视缓存的翻译任务，完成后重置计时")
        self.force_btn.clicked.connect(self.force_translate_requested.emit)
        layout.addWidget(self.force_btn)

        self.current_section_label = QLabel("当前屏幕文字")
        self.current_section_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #333;")
        layout.addWidget(self.current_section_label)

        self.current_list = QListWidget()
        self.current_list.setMaximumHeight(100)
        self.current_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.current_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.current_list)

        self.history_section_label = QLabel("已缓存文字")
        self.history_section_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #333;")
        layout.addWidget(self.history_section_label)

        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)
        self.history_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.history_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.history_list, 1)

    # ---------- public API ----------

    def on_ocr_text(self, text: str) -> None:
        self.current_original = text
        if text not in self.text_cache:
            self.text_cache.append(text)
        self.total_strings += 1
        self.current_word_count = len(text)
        self._refresh()

    def on_translation_ready(self, original: str, translated: str) -> None:
        if original:
            self.translation_cache[original] = translated
            self._save_cache_entry(original, translated)
            self._refresh()

    def get_from_cache(self, original: str) -> Optional[str]:
        return self.translation_cache.get(original)

    def on_cache_hit(self) -> None:
        self.cache_hits += 1
        self._refresh()

    def on_api_call(self) -> None:
        self.api_calls += 1
        self._refresh()

    def reset_stats(self) -> None:
        self.api_calls = 0
        self.cache_hits = 0
        self._refresh()

    def reset(self) -> None:
        self.text_cache.clear()
        self.current_original = ""
        self.total_strings = 0
        self.current_word_count = 0
        self.api_calls = 0
        self.cache_hits = 0
        self._refresh()

    # ---------- internal ----------

    def _toggle_stats(self) -> None:
        visible = self.stats_container.isVisible()
        self.stats_container.setVisible(not visible)
        self.stats_toggle_btn.setText("统计信息 ▲" if visible else "统计信息 ▼")

    def _refresh(self) -> None:
        self.cache_count_label.setText(f"缓存字符串数：{len(self.text_cache)}")
        self.word_count_label.setText(f"当前屏幕总字数：{self.current_word_count}")
        self.total_strings_label.setText(f"总处理字符串数：{self.total_strings}")
        self.attempts_label.setText(f"API调用次数：{self.api_calls}")
        self.cache_hits_label.setText(f"缓存命中次数：{self.cache_hits}")
        self._update_list()

    def _make_item_widget(self, original: str, translated: str) -> QWidget:
        widget = QWidget()
        widget.setAutoFillBackground(True)
        vl = QVBoxLayout(widget)
        vl.setContentsMargins(4, 2, 4, 2)
        vl.setSpacing(1)

        main_label = QLabel(translated)
        main_label.setWordWrap(True)
        main_label.setStyleSheet("font-size: 12px;")
        main_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        vl.addWidget(main_label)

        sub_label = QLabel(original)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("font-size: 9px; color: #888;")
        sub_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        vl.addWidget(sub_label)

        return widget

    def _add_item(self, list_widget: QListWidget, original: str,
                  translated: str, highlight: bool) -> None:
        translated = translated if translated else "翻译中..."
        display_trans = translated if len(translated) <= 100 else translated[:100] + "..."
        widget = self._make_item_widget(original, display_trans)
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, original)
        if highlight:
            item.setBackground(QColor(173, 216, 230))
        list_widget.addItem(item)
        list_widget.setItemWidget(item, widget)

    def _update_list(self) -> None:
        self.current_list.clear()
        self.history_list.clear()

        if self.current_original:
            translated = self.translation_cache.get(self.current_original, "")
            self._add_item(self.current_list, self.current_original, translated, True)

        for original in reversed(self.text_cache):
            if original == self.current_original:
                continue
            translated = self.translation_cache.get(original, "")
            self._add_item(self.history_list, original, translated, False)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        original = item.data(Qt.ItemDataRole.UserRole)
        if not original:
            return
        full_translated = self.translation_cache.get(original, "")
        if len(original) <= 80 and len(full_translated) <= 80:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("文本详情")
        dialog.resize(520, 420)
        vl = QVBoxLayout(dialog)
        vl.addWidget(QLabel("原文："))
        te_orig = QTextEdit()
        te_orig.setReadOnly(True)
        te_orig.setPlainText(original)
        vl.addWidget(te_orig)
        vl.addWidget(QLabel("译文："))
        te_trans = QTextEdit()
        te_trans.setReadOnly(True)
        te_trans.setPlainText(full_translated)
        vl.addWidget(te_trans)
        dialog.exec()
