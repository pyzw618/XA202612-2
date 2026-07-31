"""
统计卡片组件 — 麒麟 UKUI 风格

白底圆角卡片，左侧色条 + 微阴影，展示数值 + 标签。
"""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget


class StatCard(QFrame):
    """统计卡片 — 左侧色条 + 数值 + 标签"""

    def __init__(self, value: str, label: str, color: str = "#4A90D9"):
        super().__init__()
        self.setFixedSize(200, 120)
        self.setStyleSheet("""
            StatCard {
                background-color: #ffffff;
                border-radius: 10px;
                border: 1px solid #e2e5ea;
            }
        """)

        # 外层水平布局
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 左侧色条
        stripe = QWidget()
        stripe.setFixedWidth(4)
        stripe.setStyleSheet(
            f"background: {color}; border-radius: 2px; border: none;"
        )
        outer.addWidget(stripe)

        # 右侧内容
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 20, 16)
        content_layout.setSpacing(4)

        value_label = QLabel(str(value))
        value_label.setFont(QFont("Microsoft YaHei", 26, QFont.Weight.Bold))
        value_label.setStyleSheet(f"color: {color}; border: none;")
        content_layout.addWidget(value_label)

        text_label = QLabel(label)
        text_label.setFont(QFont("Microsoft YaHei", 10))
        text_label.setStyleSheet("color: #6b7280; border: none;")
        content_layout.addWidget(text_label)

        outer.addWidget(content, 1)