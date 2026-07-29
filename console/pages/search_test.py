"""检索测试页面 — 输入查询 + 展示召回结果"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class SearchTestPage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="检索测试")