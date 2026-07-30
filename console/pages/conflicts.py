"""冲突处理页面 — 冲突列表 + 手动解决（待实现）"""

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage


class ConflictsPage(BasePage):
    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        super().__init__(client, mock, title="冲突处理")