"""偏好管理页面 — 偏好记忆列表 + 详情 + 版本链（待实现）"""

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage


class PreferencesPage(BasePage):
    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        super().__init__(client, mock, title="偏好管理")