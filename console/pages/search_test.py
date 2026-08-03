"""
检索测试页面 — 输入查询 + 展示召回结果

设计：
- 顶部搜索框 + 检索按钮，回车即可触发
- 检索后显示耗时与命中总数
- 结果按「偏好记忆 / 知识记忆」分组展示卡片
- 每张卡片带类型徽标、相似度分数、记忆内容
- 空态 / 加载态 / 无结果态 三种提示
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage
from console.styles import INPUT_STYLE, SCROLLBAR_STYLE

# 类型徽标配色
TYPE_MAP = {
    "preference": ("偏好", "#3B82F6"),
    "knowledge": ("知识", "#10B981"),
}


class SearchTestPage(BasePage):
    """检索测试 — 输入查询 + 展示召回结果"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._result_container: QWidget | None = None
        self._result_layout: QVBoxLayout | None = None
        self._status_label: QLabel | None = None
        self._searching: bool = False
        super().__init__(client, mock, title="检索测试")

    def setup_ui(self):
        layout = self.content.layout()

        # ---- 顶部搜索栏 ----
        search_panel = QFrame()
        search_panel.setStyleSheet("""
            QFrame { background: #ffffff; border-radius: 12px; }
        """)
        s_layout = QVBoxLayout(search_panel)
        s_layout.setContentsMargins(20, 18, 20, 18)
        s_layout.setSpacing(12)

        hint = QLabel("输入一段描述，模拟 Agent 检索记忆，例如「帮我生成项目周报」")
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet("color:#6B7280;background:transparent;")
        s_layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(12)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入查询内容…")
        self._input.setStyleSheet(INPUT_STYLE)
        self._input.setFont(QFont("Microsoft YaHei", 11))
        self._input.returnPressed.connect(self._do_search)
        row.addWidget(self._input, 1)

        self._search_btn = QPushButton("检索")
        self._search_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._search_btn.setFixedSize(96, 38)
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.setStyleSheet("""
            QPushButton {
                background: #3B82F6;
                border: none;
                border-radius: 8px;
                color: #ffffff;
            }
            QPushButton:hover { background: #2563EB; }
            QPushButton:disabled { background: #93C5FD; }
        """)
        self._search_btn.clicked.connect(self._do_search)
        row.addWidget(self._search_btn)

        s_layout.addLayout(row)

        # 状态提示：耗时 + 命中数
        self._status_label = QLabel("输入查询词开始检索")
        self._status_label.setFont(QFont("Microsoft YaHei", 10))
        self._status_label.setStyleSheet("color:#9CA3AF;background:transparent;")
        s_layout.addWidget(self._status_label)

        layout.addWidget(search_panel)

        # ---- 结果滚动区 ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}" + SCROLLBAR_STYLE)

        self._result_container = QWidget()
        self._result_container.setStyleSheet("background:transparent;")
        self._result_layout = QVBoxLayout(self._result_container)
        self._result_layout.setContentsMargins(0, 0, 8, 0)
        self._result_layout.setSpacing(16)
        self._result_layout.addStretch()

        self._scroll.setWidget(self._result_container)
        layout.addWidget(self._scroll, 1)

        # 信号
        self.mock.search_results_ready.connect(self._on_results)
        self.mock.error_occurred.connect(self._on_error)

    def on_page_shown(self):
        if self._input:
            self._input.setFocus()

    def _do_search(self):
        query = self._input.text().strip()
        if not query or self._searching:
            return
        self._searching = True
        self._search_btn.setEnabled(False)
        self._search_btn.setText("检索中…")
        self._status_label.setText("正在检索…")
        self.mock.search(query)

    def _on_results(self, data: dict):
        self._searching = False
        self._search_btn.setEnabled(True)
        self._search_btn.setText("检索")

        prefs = data.get("preferences", [])
        knows = data.get("knowledge", [])
        total = data.get("total_count", len(prefs) + len(knows))
        latency = data.get("latency_ms", 0)

        self._status_label.setText(
            f"共命中 {total} 条记忆 · 耗时 {latency:.1f} ms"
            if latency else f"共命中 {total} 条记忆"
        )

        self._rebuild_results(prefs, knows)

    def _on_error(self, msg: str):
        self._searching = False
        self._search_btn.setEnabled(True)
        self._search_btn.setText("检索")
        self._status_label.setText(f"检索失败: {msg}")
        self._status_label.setStyleSheet("color:#EF4444;background:transparent;")

    def _rebuild_results(self, prefs: list[dict], knows: list[dict]):
        # 清空（保留末尾 stretch）
        while self._result_layout.count() > 1:
            item = self._result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not prefs and not knows:
            empty = QLabel("未检索到相关记忆，换个关键词试试")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color:#9CA3AF;font-size:14px;padding:40px;background:transparent;")
            self._result_layout.insertWidget(self._result_layout.count() - 1, empty)
            return

        if prefs:
            self._result_layout.insertWidget(
                self._result_layout.count() - 1,
                self._build_group("偏好记忆", prefs, "preference"),
            )
        if knows:
            self._result_layout.insertWidget(
                self._result_layout.count() - 1,
                self._build_group("知识记忆", knows, "knowledge"),
            )

    def _build_group(self, title: str, items: list[dict], kind: str) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;")
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(10)

        head = QLabel(title)
        head.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        head.setStyleSheet("color:#111827;background:transparent;")
        vl.addWidget(head)

        for item in items:
            card = self._build_result_card(item, kind)
            vl.addWidget(card)

        return wrap

    def _build_result_card(self, item: dict, kind: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #F3F4F6;
            }
        """)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(12)

        # 类型徽标 + 分数
        badge_text, badge_color = TYPE_MAP.get(kind, (kind, "#6B7280"))
        badge = QLabel(badge_text)
        badge.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        badge.setStyleSheet(
            f"background:{badge_color};color:#ffffff;border-radius:4px;padding:2px 8px;"
        )
        badge.setFixedHeight(22)
        cl.addWidget(badge)

        # 内容（偏好用 content，知识用 name + content）
        text = item.get("content") or item.get("name") or item.get("text") or ""
        if kind == "knowledge" and item.get("name") and item.get("content"):
            text = f"{item.get('name')} — {item.get('content')}"
        content_lbl = QLabel(text)
        content_lbl.setFont(QFont("Microsoft YaHei", 10))
        content_lbl.setStyleSheet("color:#374151;background:transparent;")
        content_lbl.setWordWrap(True)
        content_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(content_lbl, 1)

        score = item.get("score")
        if score is not None:
            score_lbl = QLabel(f"{score:.2f}")
            score_lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
            score_lbl.setStyleSheet("color:#3B82F6;background:transparent;")
            cl.addWidget(score_lbl)

        return card