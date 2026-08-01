"""
页面基类

所有页面继承此基类，统一接收 MemoryHubClient 和 MockDataController。
去线化设计：无边框标题栏，用背景色分层。
showEvent 通知子类页面被切换回来，用于重置筛选状态。
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

        # 标题栏 — 无边框，纯白背景
        title_bar = QWidget()
        title_bar.setFixedHeight(56)
        title_bar.setStyleSheet("background: #ffffff;")
        title_layout = QVBoxLayout(title_bar)
        title_layout.setContentsMargins(32, 18, 32, 10)
        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 17, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #111827;")
        title_layout.addWidget(title_label)
        root.addWidget(title_bar)

        # 内容区 — 极浅蓝灰底色，与白色标题栏形成层次
        self.content = QWidget()
        self.content.setStyleSheet("background: #f5f6fa;")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(32, 20, 32, 28)
        content_layout.setSpacing(16)
        root.addWidget(self.content, 1)

        self.setup_ui()

    def setup_ui(self):
        """子类重写此方法"""
        pass

    def on_page_shown(self):
        """子类重写此方法，在页面被切换回来时重置筛选状态"""
        pass

    def showEvent(self, event):
        super().showEvent(event)
        self.on_page_shown()
