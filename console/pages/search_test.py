"""检索测试页面 — 输入查询 + 展示召回结果（待实现）"""

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage


class SearchTestPage(BasePage):
    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        super().__init__(client, mock, title="检索测试")