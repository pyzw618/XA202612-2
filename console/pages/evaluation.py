"""评测报告页面 — 指标卡片 + 报告列表"""

from console.api_client import MemoryHubClient
from console.pages.base import BasePage


class EvaluationPage(BasePage):
    def __init__(self, client: MemoryHubClient):
        super().__init__(client, title="评测报告")