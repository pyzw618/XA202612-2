"""
评测报告页面 — 指标卡片 + 报告列表

设计：
- 顶部任务选择 + 运行评测 + 刷新按钮
- 每条报告一张卡片，左侧任务名/样本数/耗时，右侧指标瓷片
- 指标按任务类型动态显示：preference/conflict 显示 准确率/精确率/召回率/F1，
  retrieval 显示 Recall@K / MRR
- 空态 / 加载态提示
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
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

# 任务名 → 中文标签
TASK_NAME_MAP = {
    "preference_extraction": "偏好提取",
    "preference": "偏好提取",
    "retrieval": "检索",
    "conflict": "冲突检测",
    "latency": "延迟",
}

# 任务类型 → 展示的指标瓷片
METRIC_TILES = {
    "preference_extraction": [
        ("accuracy", "准确率"),
        ("precision", "精确率"),
        ("recall", "召回率"),
        ("f1", "F1"),
    ],
    "conflict": [
        ("accuracy", "准确率"),
        ("precision", "精确率"),
        ("recall", "召回率"),
        ("f1", "F1"),
    ],
    "retrieval": [
        ("recall_at_k", "Recall@K"),
        ("mrr", "MRR"),
        ("accuracy", "准确率"),
    ],
}


def _metric_key(task_name: str) -> list[tuple[str, str]]:
    for key, tiles in METRIC_TILES.items():
        if key in task_name:
            return tiles
    return [("accuracy", "准确率")]


class EvaluationPage(BasePage):
    """评测报告 — 指标卡片 + 报告列表"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._loading: QLabel | None = None
        self._report_container: QWidget | None = None
        self._report_layout: QVBoxLayout | None = None
        self._task_combo: QComboBox | None = None
        self._run_btn: QPushButton | None = None
        self._raw_reports: list[dict] = []
        super().__init__(client, mock, title="评测报告")

    def setup_ui(self):
        layout = self.content.layout()

        # ---- 顶部操作栏 ----
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame { background: #ffffff; border-radius: 12px; }
        """)
        b_layout = QHBoxLayout(bar)
        b_layout.setContentsMargins(20, 14, 20, 14)
        b_layout.setSpacing(12)

        lbl = QLabel("评测任务")
        lbl.setFont(QFont("Microsoft YaHei", 10))
        lbl.setStyleSheet("color:#6B7280;background:transparent;")
        b_layout.addWidget(lbl)

        self._task_combo = QComboBox()
        self._task_combo.addItems([
            "偏好提取", "检索", "冲突检测", "延迟",
        ])
        self._task_combo.setFixedWidth(140)
        self._task_combo.setStyleSheet(COMBO_STYLE)
        b_layout.addWidget(self._task_combo)

        self._run_btn = QPushButton("运行评测")
        self._run_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self._run_btn.setFixedSize(96, 34)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setStyleSheet("""
            QPushButton {
                background: #3B82F6;
                border: none;
                border-radius: 8px;
                color: #ffffff;
            }
            QPushButton:hover { background: #2563EB; }
            QPushButton:disabled { background: #93C5FD; }
        """)
        self._run_btn.clicked.connect(self._run_eval)
        b_layout.addWidget(self._run_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setFont(QFont("Microsoft YaHei", 10))
        refresh_btn.setFixedSize(72, 34)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                color: #374151;
            }
            QPushButton:hover { background: #F3F4F6; }
        """)
        refresh_btn.clicked.connect(self._load)
        b_layout.addWidget(refresh_btn)

        b_layout.addStretch()
        layout.addWidget(bar)

        # ---- 加载提示 ----
        self._loading = QLabel("正在加载评测报告…")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet("color:#9CA3AF;font-size:14px;padding:40px;background:transparent;")
        layout.addWidget(self._loading)

        # ---- 报告滚动区 ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}" + SCROLLBAR_STYLE)

        self._report_container = QWidget()
        self._report_container.setStyleSheet("background:transparent;")
        self._report_layout = QVBoxLayout(self._report_container)
        self._report_layout.setContentsMargins(0, 0, 8, 0)
        self._report_layout.setSpacing(16)
        self._report_layout.addStretch()

        self._scroll.setWidget(self._report_container)
        self._scroll.hide()
        layout.addWidget(self._scroll, 1)

        # 信号
        self.mock.eval_reports_ready.connect(self._on_reports)
        self.mock.error_occurred.connect(self._on_error)

    def on_page_shown(self):
        self._load()

    def _load(self):
        if self._loading:
            self._loading.show()
        if self._scroll:
            self._scroll.hide()
        self.mock.load_eval_reports()

    def _run_eval(self):
        task = self._task_combo.currentText()
        task_key = {
            "偏好提取": "preference",
            "检索": "retrieval",
            "冲突检测": "conflict",
            "延迟": "latency",
        }[task]
        self._run_btn.setEnabled(False)
        self._run_btn.setText("运行中…")
        self.mock.run_evaluation(task_key)

    def _on_reports(self, reports: list[dict]):
        self._loading.hide()
        self._scroll.show()
        self._run_btn.setEnabled(True)
        self._run_btn.setText("运行评测")
        self._raw_reports = reports
        self._reports()
        if not reports:
            self._show_empty()

    def _show_empty(self):
        while self._report_layout.count() > 1:
            item = self._report_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        empty = QLabel("暂无评测报告，点击上方「运行评测」生成一份")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color:#9CA3AF;font-size:14px;padding:40px;background:transparent;")
        self._report_layout.insertWidget(self._report_layout.count() - 1, empty)

    def _reports(self):
        while self._report_layout.count() > 1:
            item = self._report_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for report in self._raw_reports:
            card = self._build_report_card(report)
            self._report_layout.insertWidget(self._report_layout.count() - 1, card)

    def _build_report_card(self, report: dict) -> QWidget:
        task_name = report.get("task_name", "")
        task_label = TASK_NAME_MAP.get(task_name, task_name or "未知任务")

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border-radius: 10px;
                border: 1px solid #F3F4F6;
            }
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(14)

        # 顶栏：任务名 + 样本数 + 耗时
        top = QHBoxLayout()
        top.setSpacing(12)

        name = QLabel(task_label)
        name.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        name.setStyleSheet("color:#111827;background:transparent;")
        top.addWidget(name)

        samples = QLabel(f"{report.get('total_samples', 0)} 样本")
        samples.setFont(QFont("Microsoft YaHei", 10))
        samples.setStyleSheet("color:#6B7280;background:transparent;")
        top.addWidget(samples)

        top.addStretch()

        latency = report.get("avg_latency_ms")
        if latency is not None:
            lat_lbl = QLabel(f"平均 {latency:.1f} ms")
            lat_lbl.setFont(QFont("Microsoft YaHei", 10))
            lat_lbl.setStyleSheet("color:#3B82F6;background:transparent;")
            top.addWidget(lat_lbl)
        cl.addLayout(top)

        # 指标瓷片
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        for field, label in _metric_key(task_name):
            tiles.addWidget(self._build_tile(label, report.get(field)))
        tiles.addStretch()
        cl.addLayout(tiles)

        return card

    def _build_tile(self, label: str, value) -> QWidget:
        tile = QFrame()
        tile.setStyleSheet("""
            QFrame {
                background: #F9FAFB;
                border-radius: 8px;
                border: 1px solid #F3F4F6;
                min-width: 96px;
            }
        """)
        tl = QVBoxLayout(tile)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(4)

        v = QLabel(f"{value:.2f}" if isinstance(value, (int, float)) else "—")
        v.setFont(QFont("Microsoft YaHei", 15, QFont.Weight.Bold))
        v.setStyleSheet("color:#1D4ED8;background:transparent;")
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(v)

        l = QLabel(label)
        l.setFont(QFont("Microsoft YaHei", 9))
        l.setStyleSheet("color:#6B7280;background:transparent;")
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(l)

        return tile

    def _on_error(self, msg: str):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("运行评测")
        self._loading.setText(f"加载失败: {msg}")
        self._loading.setStyleSheet("color:#EF4444;font-size:14px;padding:40px;background:transparent;")