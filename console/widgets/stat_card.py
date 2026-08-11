"""
统计卡片组件 — 麒麟 UKUI 风格

去线化设计：
- 白色卡片 + 微阴影（无 border）
- 大号数字 + 小号标签
- 可选顶部色条（3px）
"""

from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QGraphicsDropShadowEffect


class StatCard(QFrame):
    """统计卡片 — 无边框 + 微阴影 + 顶部色条"""

    def __init__(self, value: str, label: str, color: str = "#3B82F6"):
        super().__init__()
        self.setFixedSize(210, 110)

        # 外层
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部色条
        accent = QWidget()
        accent.setFixedHeight(3)
        accent.setStyleSheet(f"background: {color}; border-radius: 2px 2px 0 0;")
        outer.addWidget(accent)

        # 卡片主体
        card = QWidget()
        card.setStyleSheet("""
            background: #ffffff;
            border-radius: 0 0 10px 10px;
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 16))
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(6)

        value_label = QLabel(str(value))
        value_label.setFont(QFont("Microsoft YaHei", 28, QFont.Weight.Bold))
        value_label.setStyleSheet(f"color: {color};")
        card_layout.addWidget(value_label)

        text_label = QLabel(label)
        text_label.setFont(QFont("Microsoft YaHei", 11))
        text_label.setStyleSheet("color: #6B7280;")
        card_layout.addWidget(text_label)

        outer.addWidget(card, 1)