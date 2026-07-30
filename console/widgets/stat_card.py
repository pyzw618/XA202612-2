"""
统计卡片组件

UKUI 风格圆角卡片，展示单个指标数值。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout


class StatCard(QFrame):
    """统计卡片：图标 + 数值 + 标签"""

    def __init__(self, icon: str, value: str, label: str, color: str = "#4A90D9"):
        super().__init__()
        self.setFixedSize(200, 120)
        self.setStyleSheet(f"""
            StatCard {{
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid rgba(0, 0, 0, 0.06);
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        # 图标
        icon_label = QLabel(icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 18))
        layout.addWidget(icon_label)

        # 数值
        value_label = QLabel(str(value))
        value_label.setFont(QFont("Microsoft YaHei", 24, QFont.Weight.Bold))
        value_label.setStyleSheet(f"color: {color};")
        layout.addWidget(value_label)

        # 标签
        text_label = QLabel(label)
        text_label.setFont(QFont("Microsoft YaHei", 10))
        text_label.setStyleSheet("color: #6c6f85;")
        layout.addWidget(text_label)