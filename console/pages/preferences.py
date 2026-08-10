"""
偏好管理页面 — 偏好记忆列表 + 版本链 + 证据展示

功能：
- 表格展示所有偏好记忆（类型/内容/置信度/状态/版本/更新时间）
- 类型 + 状态双筛选下拉框
- 点击行展开版本链 + 证据链详情面板
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage

# 偏好类型中文映射（兼容全称和缩写）
PREF_TYPE_MAP = {
    "output_style": "输出风格",
    "tool_preference": "工具选择",
    "workflow_preference": "操作流程",
    "workflow_pref": "操作流程",
    "safety_preference": "安全策略",
    "safety_pref": "安全策略",
    "scene_preference": "场景偏好",
    "scene_pref": "场景偏好",
    "format_preference": "格式偏好",
    "format_pref": "格式偏好",
    "language_preference": "语言偏好",
    "language_pref": "语言偏好",
}

STATUS_MAP = {
    "active": "活跃",
    "archived": "已归档",
    "pending": "待确认",
}


class PreferencesPage(BasePage):
    """偏好管理 — 偏好记忆列表 + 版本链 + 证据展示"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._table: QTableWidget | None = None
        self._filter_bar: QWidget | None = None
        self._type_combo: QComboBox | None = None
        self._status_combo: QComboBox | None = None
        self._detail_panel: QWidget | None = None
        self._version_list: QVBoxLayout | None = None
        self._evidence_list: QVBoxLayout | None = None
        self._rebuilding: bool = False  # 表格重建锁，防止 setRowCount 触发错误的选中回调
        self._loading_label: QLabel | None = None
        self._raw_data: list[dict] = []
        super().__init__(client, mock, title="偏好管理")

    # ============================================================
    # UI 搭建
    # ============================================================

    def setup_ui(self):
        layout = self.content.layout()

        # --- 加载提示 ---
        self._loading_label = QLabel("正在加载数据...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet("color: #9ca3af; font-size: 14px; padding: 40px;")
        layout.addWidget(self._loading_label)

        # --- 筛选栏 ---
        self._filter_bar = QWidget()
        self._filter_bar.setStyleSheet("background: transparent;")
        filter_layout = QHBoxLayout(self._filter_bar)
        filter_layout.setContentsMargins(0, 4, 0, 4)
        filter_layout.setSpacing(12)

        filter_layout.addWidget(self._make_label("类型筛选"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(
            ["全部", "输出风格", "工具选择", "操作流程", "安全策略", "场景偏好", "格式偏好"]
        )
        self._type_combo.setFixedWidth(140)
        self._style_combo(self._type_combo)
        self._type_combo.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._type_combo)

        filter_layout.addWidget(self._make_label("状态"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["全部", "活跃", "已归档"])
        self._status_combo.setFixedWidth(120)
        self._style_combo(self._status_combo)
        self._status_combo.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._status_combo)

        filter_layout.addStretch()
        self._filter_bar.hide()
        layout.addWidget(self._filter_bar)

        # --- 表格 ---
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["偏好类型", "内容", "置信度", "状态", "版本", "更新时间"]
        )
        self._style_table()
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.hide()
        layout.addWidget(self._table, 1)

        # --- 详情面板 ---
        self._detail_panel = QWidget()
        self._detail_panel.setObjectName("detail_panel")
        self._detail_panel.setStyleSheet("""
            QWidget#detail_panel {
                background: #ffffff;
                border: 1px solid #e2e5ea;
                border-radius: 8px;
            }
        """)
        self._detail_panel.setFixedHeight(220)
        detail_layout = QHBoxLayout(self._detail_panel)
        detail_layout.setContentsMargins(20, 12, 20, 12)
        detail_layout.setSpacing(24)

        # 版本链区域
        version_group = QWidget()
        version_group.setStyleSheet("background: transparent;")
        vg_layout = QVBoxLayout(version_group)
        vg_layout.setContentsMargins(0, 0, 0, 0)
        vg_layout.setSpacing(8)
        vg_layout.addWidget(self._make_section_label("版本链"))
        self._version_container = QWidget()
        self._version_list = QVBoxLayout(self._version_container)
        self._version_list.setContentsMargins(0, 0, 0, 0)
        self._version_list.setSpacing(6)
        self._version_list.addStretch()
        vg_layout.addWidget(self._version_container, 1)
        detail_layout.addWidget(version_group, 1)

        # 证据区域
        evidence_group = QWidget()
        evidence_group.setStyleSheet("background: transparent;")
        eg_layout = QVBoxLayout(evidence_group)
        eg_layout.setContentsMargins(0, 0, 0, 0)
        eg_layout.setSpacing(8)
        eg_layout.addWidget(self._make_section_label("证据链"))
        self._evidence_container = QWidget()
        self._evidence_list = QVBoxLayout(self._evidence_container)
        self._evidence_list.setContentsMargins(0, 0, 0, 0)
        self._evidence_list.setSpacing(6)
        self._evidence_list.addStretch()
        eg_layout.addWidget(self._evidence_container, 1)
        detail_layout.addWidget(evidence_group, 1)

        self._detail_panel.hide()
        layout.addWidget(self._detail_panel)

        # --- 数据加载 ---
        if self.mock is not None:
            self.mock.preferences_ready.connect(self._on_data_loaded)
            self.mock.error_occurred.connect(self._on_error)
            self.mock.load_preferences()
        else:
            # 实时后端模式：使用 API 客户端加载
            self._loading_label.setText("连接实时后端中…")
            self._load_from_api()

    def _load_from_api(self):
        """从 MemoryHub API 加载偏好数据"""
        try:
            data = self.client.list_preferences()
            self._on_data_loaded([p.model_dump() if hasattr(p, 'model_dump') else p for p in data])
        except Exception as e:
            self._on_error(str(e))

    # ============================================================
    # 数据加载
    # ============================================================

    def _on_data_loaded(self, data: list[dict]):
        self._loading_label.hide()
        self._raw_data = data
        self._filter_bar.show()
        self._table.show()
        self._populate_table(data)

    def _on_error(self, msg: str):
        self._loading_label.setText(f"加载失败: {msg}")
        self._loading_label.setStyleSheet(
            "color: #EA4335; font-size: 14px; padding: 40px; background: transparent;"
        )

    # ============================================================
    # 表格渲染
    # ============================================================

    def _populate_table(self, data: list[dict]):
        self._rebuilding = True
        self._table.setRowCount(len(data))
        for row, item in enumerate(data):
            # 偏好类型
            type_text = PREF_TYPE_MAP.get(
                item.get("preference_type", ""), item.get("preference_type", "")
            )
            self._set_cell(row, 0, type_text, item["memory_id"])

            # 内容
            self._set_cell(row, 1, item.get("text", ""))

            # 置信度（带颜色）
            conf = item.get("confidence", 0)
            conf_text = f"{conf:.0%}"
            conf_item = self._set_cell(row, 2, conf_text)
            if conf >= 0.9:
                conf_item.setForeground(QBrush(QColor("#34A853")))
            elif conf >= 0.7:
                conf_item.setForeground(QBrush(QColor("#E8734A")))
            else:
                conf_item.setForeground(QBrush(QColor("#EA4335")))

            # 状态
            status_text = STATUS_MAP.get(item.get("status", ""), item.get("status", ""))
            self._set_cell(row, 3, status_text)

            # 版本
            self._set_cell(row, 4, f"v{item.get('version', 1)}")

            # 更新时间
            updated = item.get("updated_at", "")
            if "T" in updated:
                updated = updated.replace("T", " ")[:16]
            self._set_cell(row, 5, updated)
        self._rebuilding = False

    def _set_cell(
        self, row: int, col: int, text: str, data=None
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if data is not None:
            item.setData(Qt.ItemDataRole.UserRole, data)
        self._table.setItem(row, col, item)
        return item

    def _apply_filter(self):
        type_idx = self._type_combo.currentIndex()
        status_idx = self._status_combo.currentIndex()

        rev = {v: k for k, v in PREF_TYPE_MAP.items()}
        type_key = rev.get(self._type_combo.currentText(), "") if type_idx > 0 else ""

        status_key = ""
        if status_idx == 1:
            status_key = "active"
        elif status_idx == 2:
            status_key = "archived"

        filtered = [
            d
            for d in self._raw_data
            if (not type_key or d.get("preference_type") == type_key)
            and (not status_key or d.get("status") == status_key)
        ]
        self._populate_table(filtered)

    # ============================================================
    # 行选中 → 加载版本链 + 证据
    # ============================================================

    def _on_row_selected(self):
        if self._rebuilding:
            return
        rows = self._table.selectedIndexes()
        if not rows:
            self._detail_panel.hide()
            return

        row = rows[0].row()
        item = self._table.item(row, 0)
        if item is None:
            return
        memory_id = item.data(Qt.ItemDataRole.UserRole)
        if not memory_id:
            return

        self._clear_detail()

        # 从缓存数据中取出证据和版本链，秒出
        item_data = next(
            (d for d in self._raw_data if d["memory_id"] == memory_id), None
        )
        if item_data:
            self._show_evidences(item_data.get("evidences", []))
            self._show_versions(item_data.get("versions", []))

        self._detail_panel.show()

    def _show_versions(self, versions: list[dict]):
        """从缓存数据直接渲染版本链（无异步）"""
        for v in versions:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #fafbfc; border: 1px solid #e2e5ea;"
                " border-radius: 6px; }"
            )
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(10)

            badge = QLabel(f"v{v['version']}")
            badge.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
            badge.setStyleSheet("color: #4A90D9; border: none;")
            badge.setFixedWidth(32)
            card_layout.addWidget(badge)

            change = QLabel(v.get("change", ""))
            change.setFont(QFont("Microsoft YaHei", 10))
            change.setStyleSheet("color: #333; border: none;")
            change.setWordWrap(True)
            card_layout.addWidget(change, 1)

            date = QLabel(v.get("created_at", ""))
            date.setFont(QFont("Microsoft YaHei", 9))
            date.setStyleSheet("color: #999; border: none;")
            card_layout.addWidget(date)

            self._version_list.insertWidget(
                self._version_list.count() - 1, card
            )

    def _on_cell_double_clicked(self, row: int, col: int):
        """双击内容列 → 弹窗展示完整内容"""
        if col != 1:  # 只有"内容"列才弹出
            return
        item = self._table.item(row, col)
        if item is None:
            return
        text = item.text()

        dlg = QDialog(self)
        dlg.setWindowTitle("查看内容")
        dlg.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setMinimumWidth(400)
        dlg.setMaximumWidth(620)

        # 外层 — 阴影占位
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(8, 8, 8, 8)

        # 内层 — 白色卡片
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e5ea;"
            " border-radius: 10px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 14, 20, 20)
        card_layout.setSpacing(12)

        # 标题栏
        title_bar = QHBoxLayout()
        title = QLabel("查看内容")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #1a1a2e; border: none;")
        title_bar.addWidget(title)
        title_bar.addStretch()

        close_btn = QPushButton("X")
        close_btn.setFixedSize(28, 28)
        close_btn.setFont(QFont("Microsoft YaHei", 10))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            " border-radius: 6px; color: #9ca3af; }"
            "QPushButton:hover { background: #f0f0f0; color: #1a1a2e; }"
        )
        close_btn.clicked.connect(dlg.close)
        title_bar.addWidget(close_btn)
        card_layout.addLayout(title_bar)

        # 内容
        content = QLabel(text)
        content.setFont(QFont("Microsoft YaHei", 11))
        content.setStyleSheet(
            "color: #1a1a2e; background: #fafbfc; border: 1px solid #e2e5ea;"
            " border-radius: 6px; padding: 12px;"
        )
        content.setWordWrap(True)
        card_layout.addWidget(content, 1)

        outer.addWidget(card)
        dlg.adjustSize()
        dlg.exec()

    # ============================================================
    # 详情面板
    # ============================================================

    def _clear_detail(self):
        for lst in [self._version_list, self._evidence_list]:
            while lst.count() > 1:
                child = lst.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

    def _show_evidences(self, evidences: list[dict]):
        for ev in evidences:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #fafbfc; border: 1px solid #e2e5ea;"
                " border-radius: 6px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(2)

            content = QLabel(ev.get("content", ""))
            content.setFont(QFont("Microsoft YaHei", 10))
            content.setStyleSheet("color: #1a1a2e; border: none;")
            content.setWordWrap(True)
            card_layout.addWidget(content)

            ts = QLabel(ev.get("timestamp", ""))
            ts.setFont(QFont("Microsoft YaHei", 9))
            ts.setStyleSheet("color: #9ca3af; border: none;")
            card_layout.addWidget(ts)

            self._evidence_list.insertWidget(
                self._evidence_list.count() - 1, card
            )

    # ============================================================
    # 样式工具方法
    # ============================================================

    def _make_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 10))
        label.setStyleSheet("color: #6b7280; background: transparent;")
        return label

    def _make_section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.DemiBold))
        label.setStyleSheet("color: #1a1a2e; background: transparent;")
        return label

    def _style_combo(self, combo: QComboBox):
        combo.setFont(QFont("Microsoft YaHei", 10))
        combo.setStyleSheet("""
            QComboBox {
                background: #ffffff;
                border: 1px solid #d0d0d8;
                border-radius: 6px;
                padding: 4px 10px;
                color: #1a1a2e;
            }
            QComboBox:hover { border-color: #4A90D9; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: #ffffff;
                border: 1px solid #d0d0d8;
                color: #1a1a2e;
                selection-background-color: #4A90D9;
                selection-color: #ffffff;
            }
        """)

    def _style_table(self):
        self._table.setFont(QFont("Microsoft YaHei", 10))
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #ffffff;
                border: 1px solid #e2e5ea;
                border-radius: 8px;
                gridline-color: transparent;
                alternate-background-color: #fafbfc;
            }
            QTableWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #f0f2f5;
                color: #1a1a2e;
                text-align: left;
            }
            QTableWidget::item:selected {
                background-color: rgba(74, 144, 217, 0.08);
                color: #1a1a2e;
            }
            QHeaderView::section {
                background: #f0f2f5;
                border: none;
                border-bottom: 1px solid #e2e5ea;
                padding: 8px 12px;
                font-weight: bold;
                color: #6b7280;
                text-align: left;
            }
        """)
        h = self._table.horizontalHeader()
        h.setStretchLastSection(True)
        h.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 120)
