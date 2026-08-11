"""
Dashboard 页面 — 记忆总览看板

展示：
- 4 个统计卡片（顶部色条 + 微阴影）
- 检索延迟信息
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage
from console.widgets.stat_card import StatCard


class DashboardPage(BasePage):
    """Dashboard — 总览看板"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        super().__init__(client, mock, title="Dashboard")

    def setup_ui(self):
        layout = self.content.layout()

        # 加载提示
        self._loading = QLabel("正在加载数据...")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet(
            "color: #9CA3AF; font-size: 14px; padding: 40px; background: transparent;"
        )
        layout.addWidget(self._loading)

        # 卡片区域
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background: transparent;")
        self._cards_container.hide()
        cards_layout = QHBoxLayout(self._cards_container)
        cards_layout.setSpacing(20)

        self._card_total = StatCard("—", "记忆总数", "#3B82F6")
        self._card_prefs = StatCard("—", "偏好记忆", "#F59E0B")
        self._card_know = StatCard("—", "知识记忆", "#10B981")
        self._card_conflicts = StatCard("—", "待处理冲突", "#EF4444")

        cards_layout.addWidget(self._card_total)
        cards_layout.addWidget(self._card_prefs)
        cards_layout.addWidget(self._card_know)
        cards_layout.addWidget(self._card_conflicts)
        cards_layout.addStretch()
        layout.addWidget(self._cards_container)

        # 延迟信息
        self._latency_label = QLabel()
        self._latency_label.setStyleSheet(
            "color: #9CA3AF; font-size: 12px; padding: 8px 0; background: transparent;"
        )
        self._latency_label.hide()
        layout.addWidget(self._latency_label)

        layout.addStretch()

        self.mock.dashboard_stats_ready.connect(self._on_stats_loaded)
        self.mock.load_dashboard_stats()

    def _on_stats_loaded(self, stats: dict):
        self._loading.hide()

        self._card_total.findChildren(QLabel)[0].setText(str(stats["total_memories"]))
        self._card_prefs.findChildren(QLabel)[0].setText(str(stats["preference_count"]))
        self._card_know.findChildren(QLabel)[0].setText(str(stats["knowledge_count"]))
        self._card_conflicts.findChildren(QLabel)[0].setText(str(stats["conflict_count"]))

        self._latency_label.setText(
            f"平均检索延迟: {stats['avg_latency_ms']}ms  ·  "
            f"活跃偏好: {stats['active_preferences']}  ·  "
            f"已归档: {stats['archived_preferences']}"
        )
        self._cards_container.show()
        self._latency_label.show()