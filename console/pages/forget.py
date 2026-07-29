"""遗忘管理页面 — 自然语言遗忘 + 遗忘历史"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class ForgetPage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="遗忘管理")