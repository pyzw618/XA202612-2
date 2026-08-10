"""
侧边栏导航 — 麒麟 UKUI 风格

设计要点：
- 蓝灰色底色，与白色内容区形成层次
- 左侧色条指示选中态
- 彩色圆点图标（非 emoji）
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

# 各导航项的图标色
ITEM_COLORS = [
    "#4A90D9",  # Dashboard — 蓝
    "#E8734A",  # 偏好管理 — 橙
    "#34A853",  # 知识管理 — 绿
    "#EA4335",  # 冲突处理 — 红
    "#8B5CF6",  # 检索测试 — 紫
    "#F59E0B",  # 遗忘管理 — 琥珀
    "#06B6D4",  # 评测报告 — 青
]


class Sidebar(QWidget):
    """侧边栏导航"""

    nav_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setStyleSheet("background-color: #e8ecf1;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 品牌区
        brand = QWidget()
        brand.setFixedHeight(56)
        brand.setStyleSheet("background: transparent;")
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(16, 16, 16, 8)

        brand_label = QLabel("MemoryHub")
        brand_label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        brand_label.setStyleSheet("color: #1a1a2e;")
        brand_layout.addWidget(brand_label)

        layout.addWidget(brand)

        # 分隔线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #dde0e6; margin: 0 12px;")
        layout.addWidget(sep)
        layout.addSpacing(8)

        # 导航按钮区
        self._btn_layout = QVBoxLayout()
        self._btn_layout.setContentsMargins(8, 0, 8, 0)
        self._btn_layout.setSpacing(2)
        layout.addLayout(self._btn_layout)

        layout.addStretch()

        # 版本号
        version = QLabel("  v0.1.0")
        version.setFont(QFont("Microsoft YaHei", 9))
        version.setStyleSheet("color: #9ca3af; padding: 12px 16px;")
        layout.addWidget(version)

        self._buttons: list[QPushButton] = []
        self._dots: list[QLabel] = []
        self._current_index = -1

    def add_item(self, label: str):
        idx = len(self._buttons)
        color = ITEM_COLORS[idx] if idx < len(ITEM_COLORS) else "#4A90D9"

        # 图标圆点
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background: {color}; border-radius: 4px; border: none;"
        )

        btn = QPushButton(f"  {label}")
        btn.setFont(QFont("Microsoft YaHei", 11))
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #4a5568;
                text-align: left;
                padding-left: 28px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 0, 0, 0.04);
                color: #1a1a2e;
            }}
            QPushButton:checked {{
                background-color: rgba(74, 144, 217, 0.12);
                color: #4A90D9;
                font-weight: bold;
            }}
        """)
        btn.setCheckable(True)

        btn.clicked.connect(lambda checked, i=idx: self.select(i))
        self._buttons.append(btn)
        self._dots.append(dot)

        # 圆点覆盖在按钮文字左侧
        self._btn_layout.addWidget(btn)

    def select(self, index: int):
        if index == self._current_index:
            return
        if 0 <= self._current_index < len(self._buttons):
            self._buttons[self._current_index].setChecked(False)
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self._current_index = index
            self.nav_changed.emit(index)