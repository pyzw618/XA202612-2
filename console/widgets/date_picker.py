"""
自定义日期选择器 — 完全替代 QDateEdit + calendarPopup

QDateEdit 的日历弹窗在 Windows 上是原生控件，stylesheet 不生效。
本组件用 QCalendarWidget 自建弹窗，样式完全可控。
"""

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from console.styles import CALENDAR_STYLE


class DatePicker(QWidget):
    """自定义日期选择器 — 点击按钮弹出可完全定制样式的日历"""

    date_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._date = QDate.currentDate()
        self._popup = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._btn = QPushButton(self._date.toString("yyyy-MM-dd"))
        self._btn.setFont(QFont("Microsoft YaHei", 10))
        self._btn.setFixedWidth(140)
        self._btn.setFixedHeight(32)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                color: #374151;
                text-align: left;
                padding-left: 12px;
            }
            QPushButton:hover { border-color: #3B82F6; }
        """)
        self._btn.clicked.connect(self._toggle_popup)
        layout.addWidget(self._btn)

        # 下拉箭头指示
        arrow = QLabel(" ▾")
        arrow.setFont(QFont("Microsoft YaHei", 10))
        arrow.setStyleSheet("color: #9CA3AF; background: transparent;")
        arrow.setFixedWidth(16)
        layout.addWidget(arrow)

    def date(self) -> QDate:
        return self._date

    def set_date(self, d: QDate):
        self._date = d
        self._btn.setText(d.toString("yyyy-MM-dd"))

    def _toggle_popup(self):
        if self._popup and self._popup.isVisible():
            self._popup.hide()
            return
        self._show_popup()

    def _show_popup(self):
        if self._popup:
            self._popup.deleteLater()

        self._popup = _CalendarPopup(self._date, self)
        self._popup.date_selected.connect(self._on_date_selected)

        # 定位到按钮下方
        gp = self._btn.mapToGlobal(self._btn.rect().bottomLeft())
        self._popup.move(gp.x(), gp.y() + 2)
        self._popup.show()

    def _on_date_selected(self, d: QDate):
        self._date = d
        self._btn.setText(d.toString("yyyy-MM-dd"))
        if self._popup:
            self._popup.hide()
        self.date_changed.emit()


class _CalendarPopup(QFrame):
    """日历弹窗 — 无边框 + 阴影 + 完全可控的 QCalendarWidget"""

    date_selected = pyqtSignal(QDate)

    def __init__(self, current_date: QDate, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Popup
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QFrame#cal_popup { background: #ffffff; border-radius: 8px; }")
        self.setObjectName("cal_popup")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        inner = QFrame()
        inner.setObjectName("cal_popup")
        inner.setStyleSheet("QFrame#cal_popup { background: #ffffff; border-radius: 8px; }")

        il = QVBoxLayout(inner)
        il.setContentsMargins(4, 4, 4, 4)

        self._calendar = QCalendarWidget()
        self._calendar.setSelectedDate(current_date)
        self._calendar.setGridVisible(True)
        self._calendar.setNavigationBarVisible(True)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setStyleSheet(CALENDAR_STYLE)
        self._calendar.clicked.connect(self._on_clicked)
        il.addWidget(self._calendar)

        layout.addWidget(inner)
        self.adjustSize()

    def _on_clicked(self, date: QDate):
        self.date_selected.emit(date)
        self.hide()
