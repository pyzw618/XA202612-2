"""
Dashboard 页面 — 记忆总览看板

展示：
- 4 个统计卡片（总记忆数、偏好数、知识数、冲突数）
- 检索延迟趋势
- 偏好/知识类型分布
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

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

        # ---- 加载提示 ----
        self._loading = QLabel("正在加载数据...")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet("color: #6c6f85; font-size: 14px; padding: 40px;")
        layout.addWidget(self._loading)

        # ---- 统计卡片区域（初始隐藏） ----
        self._cards_container = QWidget()
        self._cards_container.hide()
        cards_layout = QHBoxLayout(self._cards_container)
        cards_layout.setSpacing(16)

        self._card_total = StatCard("🧠", "—", "记忆总数", "#4A90D9")
        self._card_prefs = StatCard("❤️", "—", "偏好记忆", "#E8734A")
        self._card_know = StatCard("📚", "—", "知识记忆", "#34A853")
        self._card_conflicts = StatCard("⚡", "—", "待处理冲突", "#EA4335")

        cards_layout.addWidget(self._card_total)
        cards_layout.addWidget(self._card_prefs)
        cards_layout.addWidget(self._card_know)
        cards_layout.addWidget(self._card_conflicts)
        cards_layout.addStretch()
        layout.addWidget(self._cards_container)

        # ---- 延迟信息 ----
        self._latency_label = QLabel()
        self._latency_label.setStyleSheet("color: #6c6f85; font-size: 11px; padding: 0;")
        self._latency_label.hide()
        layout.addWidget(self._latency_label)

        layout.addStretch()

        # ---- 连接信号 ----
        self.mock.dashboard_stats_ready.connect(self._on_stats_loaded)

        # ---- 触发加载 ----
        self.mock.load_dashboard_stats()

    def _on_stats_loaded(self, stats: dict):
        """收到 Mock 数据后更新卡片"""
        self._loading.hide()

        self._card_total.findChildren(QLabel)[1].setText(str(stats["total_memories"]))
        self._card_prefs.findChildren(QLabel)[1].setText(str(stats["preference_count"]))
        self._card_know.findChildren(QLabel)[1].setText(str(stats["knowledge_count"]))
        self._card_conflicts.findChildren(QLabel)[1].setText(str(stats["conflict_count"]))

        self._latency_label.setText(
            f"平均检索延迟: {stats['avg_latency_ms']}ms | "
            f"活跃偏好: {stats['active_preferences']} | "
            f"已归档: {stats['archived_preferences']}"
        )
        self._cards_container.show()
        self._latency_label.show()