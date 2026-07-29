"""
页面基类

所有页面继承此基类，统一接收 MemoryHubClient 实例。
"""

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from console.api_client import MemoryHubClient


class BasePage(QWidget):
    """页面基类"""

    def __init__(self, client: MemoryHubClient, title: str = ""):
        super().__init__()
        self.client = client
        self.title = title

        self.setup_ui()

    def setup_ui(self):
        """子类重写此方法，构建页面 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        label = QLabel(self.title)
        label.setStyleSheet("font-size: 20px; font-weight: bold; color: #1e1e2e;")
        layout.addWidget(label)
        layout.addStretch()