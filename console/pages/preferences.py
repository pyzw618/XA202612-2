"""偏好管理页面 — 偏好记忆列表 + 详情 + 版本链"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class PreferencesPage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="偏好管理")