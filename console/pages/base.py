"""
页面基类

所有页面继承此基类，统一接收 MemoryHubClient 和 MockDataController。
"""

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController


class BasePage(QWidget):
    """页面基类 — 提供统一的标题栏和内容区"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController, title: str):
        super().__init__()
        self.client = client
        self.mock = mock
        self.setFont(QFont("Microsoft YaHei", 10))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 标题栏
        title_bar = QWidget()
        title_bar.setStyleSheet("background: #ffffff;")
        title_bar.setFixedHeight(52)
        title_layout = QVBoxLayout(title_bar)
        title_layout.setContentsMargins(28, 14, 28, 6)
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #1a1a2e;")
        title_layout.addWidget(title_label)
        root.addWidget(title_bar)

        # 内容区 — 浅灰蓝底色，降低刺眼感
        self.content = QWidget()
        self.content.setStyleSheet("background: #f5f6f8;")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(28, 0, 28, 24)
        content_layout.setSpacing(16)
        root.addWidget(self.content, 1)

        self.setup_ui()

    def setup_ui(self):
        """子类重写此方法"""
        pass