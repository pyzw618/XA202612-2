"""
侧边栏导航 — UKUI 风格

设计要点：
- 深色背景，半透明
- 图标 + 文字导航项
- 选中项高亮 + 左侧指示条
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SIDEBAR_WIDTH = 200


class Sidebar(QWidget):
    """侧边栏导航"""

    nav_changed = pyqtSignal(int)  # 发送选中项索引

    def __init__(self):
        super().__init__()
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setStyleSheet("""
            background-color: rgba(30, 36, 51, 0.92);
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部留白
        layout.addSpacing(12)

        # 按钮容器
        self._btn_layout = QVBoxLayout()
        self._btn_layout.setContentsMargins(8, 0, 8, 0)
        self._btn_layout.setSpacing(2)
        layout.addLayout(self._btn_layout)

        layout.addStretch()

        # 底部版本信息
        version = QLabel("  v0.1.0")
        version.setFont(QFont("Microsoft YaHei", 9))
        version.setStyleSheet("color: rgba(255,255,255,0.3); padding: 12px 16px;")
        layout.addWidget(version)

        self._buttons: list[QPushButton] = []
        self._current_index = -1

    def add_item(self, icon: str, label: str):
        """添加导航项"""
        btn = QPushButton(f"  {icon}  {label}")
        btn.setFont(QFont("Microsoft YaHei", 11))
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: rgba(255, 255, 255, 0.65);
                text-align: left;
                padding-left: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: rgba(255, 255, 255, 0.9);
            }
            QPushButton:checked {
                background-color: rgba(74, 144, 217, 0.2);
                color: #ffffff;
            }
        """)
        btn.setCheckable(True)

        idx = len(self._buttons)
        btn.clicked.connect(lambda checked, i=idx: self.select(i))
        self._buttons.append(btn)
        self._btn_layout.addWidget(btn)

    def select(self, index: int):
        """选中指定导航项"""
        if index == self._current_index:
            return
        # 取消旧选中
        if 0 <= self._current_index < len(self._buttons):
            self._buttons[self._current_index].setChecked(False)
        # 设置新选中
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self._current_index = index
            self.nav_changed.emit(index)