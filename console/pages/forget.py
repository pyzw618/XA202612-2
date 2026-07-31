"""遗忘管理页面 — 自然语言遗忘 + 遗忘历史（待实现）"""

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage


class ForgetPage(BasePage):
    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        super().__init__(client, mock, title="遗忘管理")