"""
冲突处理页面 — 冲突卡片对比 + 手动解决

设计：
- 每条冲突一张卡片，顶部色条标识状态
- 左右对比（原有记忆 vs 新记忆）
- 待处理：底部三个操作按钮（覆盖 / 并存 / 合并）
- 已解决：显示决策标签
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage
from console.styles import COMBO_STYLE, SCROLLBAR_STYLE

DECISION_MAP = {
    "pending": ("待处理", "#F59E0B"),
    "override": ("覆盖", "#EF4444"),
    "coexist": ("并存", "#10B981"),
    "merge": ("合并", "#3B82F6"),
}

FIELD_MAP = {
    "content": "内容",
    "scope": "作用域",
    "confidence": "置信度",
}


class ConflictsPage(BasePage):
    """冲突处理 — 冲突卡片对比 + 手动解决"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._card_container: QWidget | None = None
        self._card_layout: QVBoxLayout | None = None
        self._filter_combo: QComboBox | None = None
        self._raw_data: list[dict] = []
        self._rebuilding: bool = False
        super().__init__(client, mock, title="冲突处理")

    def setup_ui(self):
        layout = self.content.layout()

        # 加载提示
        self._loading = QLabel("正在加载数据...")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet("color:#9CA3AF;font-size:14px;padding:40px;background:transparent;")
        layout.addWidget(self._loading)

        # 筛选栏
        self._filter_bar = QWidget()
        self._filter_bar.setStyleSheet("background:transparent;")
        fl = QHBoxLayout(self._filter_bar)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(12)

        lbl = QLabel("状态")
        lbl.setFont(QFont("Microsoft YaHei", 10))
        lbl.setStyleSheet("color:#6B7280;background:transparent;")
        fl.addWidget(lbl)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "待处理", "已解决"])
        self._filter_combo.setFixedWidth(120)
        self._filter_combo.setStyleSheet(COMBO_STYLE)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        fl.addWidget(self._filter_combo)

        self._count_label = QLabel()
        self._count_label.setFont(QFont("Microsoft YaHei", 10))
        self._count_label.setStyleSheet("color:#9CA3AF;background:transparent;")
        fl.addWidget(self._count_label)

        fl.addStretch()
        self._filter_bar.hide()
        layout.addWidget(self._filter_bar)

        # 卡片滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}" + SCROLLBAR_STYLE)

        self._card_container = QWidget()
        self._card_container.setStyleSheet("background:transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 8, 0)
        self._card_layout.setSpacing(16)
        self._card_layout.addStretch()

        self._scroll.setWidget(self._card_container)
        self._scroll.hide()
        layout.addWidget(self._scroll, 1)

        # 信号
        self.mock.conflicts_ready.connect(self._on_data_loaded)
        self.mock.error_occurred.connect(self._on_error)
        self.mock.load_conflicts()

    def on_page_shown(self):
        if self._filter_combo:
            self._filter_combo.blockSignals(True)
            self._filter_combo.setCurrentIndex(0)
            self._filter_combo.blockSignals(False)
        if self._raw_data:
            self._populate_cards(self._raw_data)

    def _on_data_loaded(self, data: list[dict]):
        self._loading.hide()
        self._raw_data = data
        self._filter_bar.show()
        self._scroll.show()
        self._populate_cards(data)

    def _on_error(self, msg: str):
        self._loading.setText(f"加载失败: {msg}")
        self._loading.setStyleSheet("color:#EF4444;font-size:14px;padding:40px;background:transparent;")

    def _apply_filter(self):
        idx = self._filter_combo.currentIndex()
        if idx == 0:
            filtered = self._raw_data
        elif idx == 1:
            filtered = [d for d in self._raw_data if d.get("decision") == "pending"]
        else:
            filtered = [d for d in self._raw_data if d.get("decision") != "pending"]
        self._populate_cards(filtered)

    def _populate_cards(self, data: list[dict]):
        self._rebuilding = True
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        pending = sum(1 for d in data if d.get("decision") == "pending")
        self._count_label.setText(f"共 {len(data)} 条冲突，{pending} 条待处理")

        for d in data:
            card = self._build_card(d)
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)
        self._rebuilding = False

    def _build_card(self, data: dict) -> QWidget:
        decision = data.get("decision", "pending")
        decision_text, decision_color = DECISION_MAP.get(decision, ("未知", "#6B7280"))

        # 外层包裹（提供阴影间距）
        wrapper = QWidget()
        wrapper.setStyleSheet("background:transparent;")
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)

        # 顶部色条
        accent = QWidget()
        accent.setFixedHeight(3)
        accent.setStyleSheet(f"background:{decision_color};border-radius:2px 2px 0 0;")
        wl.addWidget(accent)

        # 卡片主体
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border-radius: 0 0 10px 10px;
            }
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 14))
        card.setGraphicsEffect(shadow)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 16)
        cl.setSpacing(12)

        # 顶栏：冲突字段 + 决策标签 + 时间
        top = QHBoxLayout()
        top.setSpacing(12)

        field_text = FIELD_MAP.get(data.get("conflict_field", ""), data.get("conflict_field", ""))

        # 小圆点 + 字段名
        dot = QWidget()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{decision_color};border-radius:4px;")
        top.addWidget(dot)

        field_lbl = QLabel(f"冲突字段: {field_text}")
        field_lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        field_lbl.setStyleSheet("color:#374151;")
        top.addWidget(field_lbl)

        badge = QLabel(decision_text)
        badge.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        badge.setStyleSheet(
            f"background:{decision_color};color:#ffffff;border-radius:4px;padding:2px 8px;"
        )
        badge.setFixedHeight(22)
        top.addWidget(badge)

        top.addStretch()

        created = data.get("created_at", "")
        if "T" in created:
            created = created.replace("T", " ")[:16]
        time_lbl = QLabel(created)
        time_lbl.setFont(QFont("Microsoft YaHei", 9))
        time_lbl.setStyleSheet("color:#9CA3AF;")
        time_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(time_lbl)
        cl.addLayout(top)

        # 对比区域
        compare = QHBoxLayout()
        compare.setSpacing(12)

        left = self._build_side("原有记忆", data.get("old_content", ""), "#EF4444")
        compare.addWidget(left, 1)

        # 中间箭头
        arrow_wrap = QWidget()
        arrow_wrap.setStyleSheet("background:transparent;")
        al = QVBoxLayout(arrow_wrap)
        al.setContentsMargins(0, 0, 0, 0)
        al.addStretch()
        arrow = QLabel("→")
        arrow.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        arrow.setStyleSheet("color:#D1D5DB;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        al.addWidget(arrow)
        al.addStretch()
        compare.addWidget(arrow_wrap)

        right = self._build_side("新记忆", data.get("new_content", ""), "#3B82F6")
        compare.addWidget(right, 1)

        cl.addLayout(compare)

        # 原因
        reason = data.get("reason", "")
        if reason:
            reason_lbl = QLabel(f"原因: {reason}")
            reason_lbl.setFont(QFont("Microsoft YaHei", 10))
            reason_lbl.setStyleSheet("color:#6B7280;")
            reason_lbl.setWordWrap(True)
            reason_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(reason_lbl)

        # 操作按钮（仅 pending）
        if decision == "pending":
            btn_row = QHBoxLayout()
            btn_row.setSpacing(10)
            btn_row.addStretch()

            for text, dec, color in [
                ("覆盖", "override", "#EF4444"),
                ("并存", "coexist", "#10B981"),
                ("合并", "merge", "#3B82F6"),
            ]:
                btn = QPushButton(text)
                btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
                btn.setFixedSize(80, 34)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {color};
                        border: none;
                        border-radius: 8px;
                        color: #ffffff;
                    }}
                    QPushButton:hover {{ opacity: 0.85; }}
                """)
                cid = data.get("conflict_id", "")
                btn.clicked.connect(lambda checked, c=cid, d=dec: self._resolve(c, d))
                btn_row.addWidget(btn)

            cl.addLayout(btn_row)

        wl.addWidget(card)
        return wrapper

    def _build_side(self, title: str, content: str, color: str) -> QWidget:
        w = QFrame()
        w.setStyleSheet(f"""
            QFrame {{
                background: #F9FAFB;
                border-radius: 8px;
                border: 1px solid #F3F4F6;
            }}
        """)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(14, 10, 14, 10)
        vl.setSpacing(6)

        t = QLabel(title)
        t.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        t.setStyleSheet(f"color:{color};background:transparent;")
        vl.addWidget(t)

        c = QLabel(content)
        c.setFont(QFont("Microsoft YaHei", 10))
        c.setStyleSheet("color:#374151;background:transparent;")
        c.setWordWrap(True)
        c.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        vl.addWidget(c)

        vl.addStretch()
        return w

    def _resolve(self, conflict_id: str, decision: str):
        for d in self._raw_data:
            if d.get("conflict_id") == conflict_id:
                d["decision"] = decision
                break
        self._apply_filter()
