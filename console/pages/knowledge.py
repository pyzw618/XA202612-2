"""知识管理页面 — 知识记忆列表 + 详情"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class KnowledgePage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="知识管理")