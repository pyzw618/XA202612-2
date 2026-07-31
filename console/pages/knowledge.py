"""知识管理页面 — 知识记忆列表 + 详情（待实现）"""

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage


class KnowledgePage(BasePage):
    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        super().__init__(client, mock, title="知识管理")