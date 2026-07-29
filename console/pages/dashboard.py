"""Dashboard 页面 — 记忆总览看板"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class DashboardPage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="Dashboard")