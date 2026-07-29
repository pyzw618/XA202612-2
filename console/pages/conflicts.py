"""冲突处理页面 — 冲突列表 + 手动解决"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class ConflictsPage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="冲突处理")