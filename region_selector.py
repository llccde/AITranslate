from typing import Optional

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QPaintEvent
from PyQt6.QtGui import QMouseEvent, QKeyEvent


class RegionSelector(QWidget):
    region_selected = pyqtSignal(object)

    start_point: QPoint
    end_point: QPoint
    drawing: bool

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        else:
            self.setGeometry(0, 0, 1920, 1080)

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.drawing = False

    def mousePressEvent(self, a0: QMouseEvent) -> None: # type: ignore
        if a0.button() == Qt.MouseButton.LeftButton:
            self.start_point = a0.position().toPoint()
            self.end_point = self.start_point
            self.drawing = True
            self.update()
        elif a0.button() == Qt.MouseButton.RightButton:
            self.cancel_selection()

    def mouseMoveEvent(self, a0: QMouseEvent) -> None: # type: ignore
        if self.drawing:
            self.end_point = a0.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, a0: QMouseEvent) -> None: # type: ignore
        if a0.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            self.end_point = a0.position().toPoint()
            rect = QRect(self.start_point, self.end_point).normalized()
            if rect.width() > 10 and rect.height() > 10:
                self.region_selected.emit(rect)
            else:
                self.region_selected.emit(None)
            self.close()

    def keyPressEvent(self, a0: QKeyEvent) -> None: # type: ignore
        if a0.key() == Qt.Key.Key_Escape:
            self.cancel_selection()

    def cancel_selection(self) -> None:
        self.region_selected.emit(None)
        self.close()

    def paintEvent(self, a0: QPaintEvent) -> None: # type: ignore
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self.drawing:
            painter.setBrush(QColor(0, 120, 215, 80))
            painter.setPen(QPen(QColor(0, 120, 215), 2))
            rect = QRect(self.start_point, self.end_point).normalized()
            painter.drawRect(rect)
