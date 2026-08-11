"""
侧边栏导航 — 麒麟 UKUI 风格

设计原则：
- 无边框，用背景色差创造层次
- 选中态：蓝色圆角框 + 白色文字，高辨识度
- 点击已选中项保持选中状态，不会取消
- QProxyStyle 彻底屏蔽 Windows 焦点框
"""

from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QPainter
from PyQt6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SIDEBAR_WIDTH = 210


class _NoFocusStyle(QProxyStyle):
    """彻底屏蔽焦点矩形绘制 — Windows 原生样式也压不住"""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorFocusRect:
            return  # 不绘制焦点框
        super().drawPrimitive(element, option, painter, widget)


class Sidebar(QWidget):
    """侧边栏导航"""

    nav_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setStyleSheet("background-color: #f0f2f7;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 品牌区
        brand = QWidget()
        brand.setFixedHeight(64)
        brand.setStyleSheet("background: transparent;")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(24, 24, 24, 12)

        brand_label = QLabel("MemoryHub")
        brand_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        brand_label.setStyleSheet("color: #111827;")
        brand_layout.addWidget(brand_label)

        layout.addWidget(brand)

        # 导航按钮区
        self._btn_layout = QVBoxLayout()
        self._btn_layout.setContentsMargins(10, 4, 10, 4)
        self._btn_layout.setSpacing(2)
        layout.addLayout(self._btn_layout)

        layout.addStretch()

        # 版本号
        version = QLabel("  v0.1.0")
        version.setFont(QFont("Microsoft YaHei", 9))
        version.setStyleSheet("color: #b0b5c0; padding: 16px 24px;")
        layout.addWidget(version)

        self._buttons: list[QPushButton] = []
        self._current_index = -1

    def add_item(self, label: str):
        idx = len(self._buttons)

        btn = QPushButton(label)
        btn.setFont(QFont("Microsoft YaHei", 11))
        btn.setFixedHeight(42)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyle(_NoFocusStyle())  # 终极方案：自定义 Style 不绘制焦点框
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #6B7280;
                text-align: left;
                padding-left: 14px;
                outline: none;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.04);
                color: #374151;
            }
        """)
        # 不用 setCheckable — 手动管理选中态，防止点击已选项取消选中
        btn.clicked.connect(lambda: self.select(idx))
        self._buttons.append(btn)
        self._btn_layout.addWidget(btn)

    def select(self, index: int):
        # 点击已选中项：保持选中，不重复发射信号
        if index == self._current_index:
            return
        if 0 <= self._current_index < len(self._buttons):
            self._buttons[self._current_index].setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    color: #6B7280;
                    text-align: left;
                    padding-left: 14px;
                    outline: none;
                }
                QPushButton:hover {
                    background-color: rgba(0, 0, 0, 0.04);
                    color: #374151;
                }
            """)
        if 0 <= index < len(self._buttons):
            self._buttons[index].setStyleSheet("""
                QPushButton {
                    background-color: #3B82F6;
                    border: none;
                    border-radius: 8px;
                    color: #ffffff;
                    font-weight: 600;
                    text-align: left;
                    padding-left: 14px;
                    outline: none;
                }
                QPushButton:hover {
                    background-color: #2563EB;
                    color: #ffffff;
                }
            """)
            self._current_index = index
            self.nav_changed.emit(index)
