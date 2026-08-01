"""
偏好管理页面 — 偏好记忆列表 + 版本链 + 证据展示

功能：
- 搜索（内容）+ 可折叠筛选面板
- 类型 / 状态 / 置信度（数值输入，%外置）/ 创建时间 / 更新时间（复选框+日历）
- 表头点击排序（▲▼，三态：升序→降序→取消）
- 平滑滚动、自适应列宽
- 可滚动详情面板（版本链 + 证据链）
- 双击内容列弹出完整内容
- 文本可选中复制
"""

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage
from console.styles import (
    CHECKBOX_STYLE,
    COMBO_STYLE,
    INPUT_STYLE,
    SCROLLBAR_STYLE,
    SPINBOX_STYLE,
    TABLE_STYLE,
)
from console.widgets.date_picker import DatePicker

# 偏好类型中文映射
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

# 列索引
COL_TYPE = 0
COL_CONTENT = 1
COL_CONF = 2
COL_STATUS = 3
COL_VERSION = 4
COL_CREATED = 5
COL_UPDATED = 6

# 可排序列（内容列不可排序）
SORTABLE_COLS = {COL_TYPE, COL_CONF, COL_STATUS, COL_VERSION, COL_CREATED, COL_UPDATED}


class PreferencesPage(BasePage):
    """偏好管理 — 偏好记忆列表 + 版本链 + 证据展示"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._table: QTableWidget | None = None
        self._filter_panel: QWidget | None = None
        self._filter_visible: bool = False
        self._type_combo: QComboBox | None = None
        self._status_combo: QComboBox | None = None
        self._conf_op: QComboBox | None = None
        self._conf_value: QDoubleSpinBox | None = None
        self._search_input: QLineEdit | None = None
        # 日期筛选：(checkbox, from_date, to_date)
        self._created_ck: QCheckBox | None = None
        self._created_from: DatePicker | None = None
        self._created_to: DatePicker | None = None
        self._updated_ck: QCheckBox | None = None
        self._updated_from: DatePicker | None = None
        self._updated_to: DatePicker | None = None
        self._detail_panel: QWidget | None = None
        self._version_list: QVBoxLayout | None = None
        self._evidence_list: QVBoxLayout | None = None
        self._rebuilding: bool = False
        self._raw_data: list[dict] = []
        self._filtered_data: list[dict] = []
        self._sort_state: dict[int, str | None] = {}
        super().__init__(client, mock, title="偏好管理")

    # ============================================================
    # UI 搭建
    # ============================================================

    def setup_ui(self):
        layout = self.content.layout()

        # --- 加载提示 ---
        self._loading_label = QLabel("正在加载数据...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet(
            "color: #9CA3AF; font-size: 14px; padding: 40px; background: transparent;"
        )
        layout.addWidget(self._loading_label)

        # --- 搜索栏 + 筛选按钮 ---
        self._search_bar = QWidget()
        self._search_bar.setStyleSheet("background: transparent;")
        search_layout = QHBoxLayout(self._search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(12)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索偏好内容...")
        self._search_input.setFixedWidth(280)
        self._search_input.setStyleSheet(INPUT_STYLE)
        self._search_input.textChanged.connect(self._apply_filter)
        search_layout.addWidget(self._search_input)

        self._filter_btn = QPushButton("筛选")
        self._filter_btn.setFixedWidth(72)
        self._filter_btn.setFixedHeight(34)
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff; border: 1px solid #E5E7EB; border-radius: 8px;
                color: #6B7280; font-size: 10pt;
            }
            QPushButton:hover { border-color: #3B82F6; color: #3B82F6; }
            QPushButton:checked { background: #3B82F6; color: #ffffff; border-color: #3B82F6; }
        """)
        self._filter_btn.setCheckable(True)
        self._filter_btn.clicked.connect(self._toggle_filter)
        search_layout.addWidget(self._filter_btn)

        search_layout.addStretch()
        self._search_bar.hide()
        layout.addWidget(self._search_bar)

        # --- 可折叠筛选面板 ---
        self._filter_panel = QWidget()
        self._filter_panel.setStyleSheet("background: transparent;")
        fp = QVBoxLayout(self._filter_panel)
        fp.setContentsMargins(0, 0, 0, 0)
        fp.setSpacing(10)

        # 行1：类型 + 状态 + 置信度
        r1 = QHBoxLayout()
        r1.setSpacing(12)
        r1.addWidget(self._make_label("类型"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["全部", "输出风格", "工具选择", "操作流程", "安全策略", "场景偏好", "格式偏好"])
        self._type_combo.setFixedWidth(120)
        self._type_combo.setStyleSheet(COMBO_STYLE)
        self._type_combo.currentIndexChanged.connect(self._apply_filter)
        r1.addWidget(self._type_combo)

        r1.addWidget(self._make_label("状态"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["全部", "活跃", "已归档"])
        self._status_combo.setFixedWidth(100)
        self._status_combo.setStyleSheet(COMBO_STYLE)
        self._status_combo.currentIndexChanged.connect(self._apply_filter)
        r1.addWidget(self._status_combo)

        r1.addWidget(self._make_label("置信度"))
        self._conf_op = QComboBox()
        self._conf_op.addItems(["不限", ">=", "<=", ">", "<", "="])
        self._conf_op.setFixedWidth(80)
        self._conf_op.setStyleSheet(COMBO_STYLE)
        self._conf_op.currentIndexChanged.connect(self._apply_filter)
        r1.addWidget(self._conf_op)

        self._conf_value = QDoubleSpinBox()
        self._conf_value.setRange(0, 100)
        self._conf_value.setValue(90)
        self._conf_value.setDecimals(0)
        self._conf_value.setSingleStep(5)
        self._conf_value.setFixedWidth(80)
        self._conf_value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._conf_value.setStyleSheet(SPINBOX_STYLE)
        self._conf_value.valueChanged.connect(self._apply_filter)
        r1.addWidget(self._conf_value)
        r1.addWidget(self._make_label("%"))

        r1.addStretch()
        fp.addLayout(r1)

        # 行2：创建时间
        r2 = QHBoxLayout()
        r2.setSpacing(12)
        self._created_ck = QCheckBox("创建时间")
        self._created_ck.setStyleSheet(CHECKBOX_STYLE)
        self._created_ck.setFont(QFont("Microsoft YaHei", 10))
        self._created_ck.stateChanged.connect(self._apply_filter)
        r2.addWidget(self._created_ck)
        self._created_from = self._make_date_edit()
        r2.addWidget(self._created_from)
        r2.addWidget(self._make_label("至"))
        self._created_to = self._make_date_edit()
        r2.addWidget(self._created_to)
        r2.addStretch()
        fp.addLayout(r2)

        # 行3：更新时间
        r3 = QHBoxLayout()
        r3.setSpacing(12)
        self._updated_ck = QCheckBox("更新时间")
        self._updated_ck.setStyleSheet(CHECKBOX_STYLE)
        self._updated_ck.setFont(QFont("Microsoft YaHei", 10))
        self._updated_ck.stateChanged.connect(self._apply_filter)
        r3.addWidget(self._updated_ck)
        self._updated_from = self._make_date_edit()
        r3.addWidget(self._updated_from)
        r3.addWidget(self._make_label("至"))
        self._updated_to = self._make_date_edit()
        r3.addWidget(self._updated_to)
        r3.addStretch()
        fp.addLayout(r3)

        self._filter_panel.hide()
        layout.addWidget(self._filter_panel)

        # --- 表格容器 ---
        self._table_wrapper = QWidget()
        self._table_wrapper.setStyleSheet("background: #ffffff; border-radius: 10px;")
        shadow = QGraphicsDropShadowEffect(self._table_wrapper)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 14))
        self._table_wrapper.setGraphicsEffect(shadow)

        tw = QVBoxLayout(self._table_wrapper)
        tw.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["偏好类型", "内容", "置信度", "状态", "版本", "创建时间", "更新时间"]
        )
        self._style_table()
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.hide()
        tw.addWidget(self._table)
        layout.addWidget(self._table_wrapper, 1)

        # --- 详情面板 ---
        self._detail_panel = QWidget()
        self._detail_panel.setObjectName("detail_panel")
        self._detail_panel.setStyleSheet("QWidget#detail_panel { background: #ffffff; border-radius: 10px; }")
        ds = QGraphicsDropShadowEffect(self._detail_panel)
        ds.setBlurRadius(16); ds.setOffset(0, 2); ds.setColor(QColor(0, 0, 0, 14))
        self._detail_panel.setGraphicsEffect(ds)
        self._detail_panel.setFixedHeight(240)
        dl = QHBoxLayout(self._detail_panel)
        dl.setContentsMargins(24, 16, 24, 16)
        dl.setSpacing(32)

        # 版本链
        vg = QWidget(); vg.setStyleSheet("background: transparent;")
        vgl = QVBoxLayout(vg); vgl.setContentsMargins(0,0,0,0); vgl.setSpacing(10)
        vgl.addWidget(self._make_section_label("版本链"))
        vs = QScrollArea(); vs.setWidgetResizable(True)
        vs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        vs.setStyleSheet("QScrollArea{border:none;background:transparent;}" + SCROLLBAR_STYLE)
        self._version_container = QWidget(); self._version_container.setStyleSheet("background:transparent;")
        self._version_list = QVBoxLayout(self._version_container)
        self._version_list.setContentsMargins(0,0,8,0); self._version_list.setSpacing(6)
        self._version_list.addStretch()
        vs.setWidget(self._version_container); vgl.addWidget(vs, 1)
        dl.addWidget(vg, 1)

        sep = QWidget(); sep.setFixedWidth(1); sep.setStyleSheet("background:#F3F4F6;")
        dl.addWidget(sep)

        # 证据链
        eg = QWidget(); eg.setStyleSheet("background: transparent;")
        egl = QVBoxLayout(eg); egl.setContentsMargins(0,0,0,0); egl.setSpacing(10)
        egl.addWidget(self._make_section_label("证据链"))
        es = QScrollArea(); es.setWidgetResizable(True)
        es.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        es.setStyleSheet("QScrollArea{border:none;background:transparent;}" + SCROLLBAR_STYLE)
        self._evidence_container = QWidget(); self._evidence_container.setStyleSheet("background:transparent;")
        self._evidence_list = QVBoxLayout(self._evidence_container)
        self._evidence_list.setContentsMargins(0,0,8,0); self._evidence_list.setSpacing(6)
        self._evidence_list.addStretch()
        es.setWidget(self._evidence_container); egl.addWidget(es, 1)
        dl.addWidget(eg, 1)

        self._detail_panel.hide()
        layout.addWidget(self._detail_panel)

        # --- 信号 ---
        self.mock.preferences_ready.connect(self._on_data_loaded)
        self.mock.error_occurred.connect(self._on_error)
        self.mock.load_preferences()

    # ============================================================
    # 筛选面板切换 / 页面切换
    # ============================================================

    def _toggle_filter(self):
        self._filter_visible = not self._filter_visible
        self._filter_panel.setVisible(self._filter_visible)
        if not self._filter_visible:
            self._reset_filter_values()

    def on_page_shown(self):
        self._reset_filters()

    def _reset_filter_values(self):
        for cb in [self._type_combo, self._status_combo, self._conf_op]:
            if cb:
                cb.blockSignals(True); cb.setCurrentIndex(0); cb.blockSignals(False)
        if self._conf_value:
            self._conf_value.blockSignals(True); self._conf_value.setValue(90); self._conf_value.blockSignals(False)
        for ck in [self._created_ck, self._updated_ck]:
            if ck:
                ck.blockSignals(True); ck.setChecked(False); ck.blockSignals(False)
        for de in [self._created_from, self._created_to, self._updated_from, self._updated_to]:
            if de:
                de.blockSignals(True); de.set_date(QDate.currentDate()); de.blockSignals(False)
        self._sort_state.clear()
        self._update_header_labels()
        if self._raw_data:
            self._filtered_data = list(self._raw_data)
            self._populate_table(self._filtered_data)

    def _reset_filters(self):
        if self._search_input:
            self._search_input.blockSignals(True); self._search_input.clear(); self._search_input.blockSignals(False)
        self._reset_filter_values()
        if self._filter_panel and self._filter_visible:
            self._filter_visible = False
            self._filter_panel.hide()
            self._filter_btn.setChecked(False)

    # ============================================================
    # 数据加载
    # ============================================================

    def _on_data_loaded(self, data: list[dict]):
        self._loading_label.hide()
        self._raw_data = data
        self._filtered_data = list(data)
        self._search_bar.show()
        self._table.show()
        self._populate_table(data)

    def _on_error(self, msg: str):
        self._loading_label.setText(f"加载失败: {msg}")
        self._loading_label.setStyleSheet("color:#EF4444; font-size:14px; padding:40px; background:transparent;")

    # ============================================================
    # 表格渲染
    # ============================================================

    def _populate_table(self, data: list[dict]):
        self._rebuilding = True
        self._table.setRowCount(len(data))
        for row, item in enumerate(data):
            type_text = PREF_TYPE_MAP.get(item.get("preference_type", ""), item.get("preference_type", ""))
            self._set_cell(row, COL_TYPE, type_text, item["memory_id"])
            self._set_cell(row, COL_CONTENT, item.get("content", ""))

            conf = item.get("confidence", 0)
            ci = self._set_cell(row, COL_CONF, f"{conf:.0%}")
            if conf >= 0.9: ci.setForeground(QBrush(QColor("#10B981")))
            elif conf >= 0.7: ci.setForeground(QBrush(QColor("#F59E0B")))
            else: ci.setForeground(QBrush(QColor("#EF4444")))

            self._set_cell(row, COL_STATUS, STATUS_MAP.get(item.get("status", ""), item.get("status", "")))
            self._set_cell(row, COL_VERSION, f"v{item.get('version', 1)}")

            created = item.get("created_at", "")
            if "T" in created: created = created.replace("T", " ")[:16]
            self._set_cell(row, COL_CREATED, created)

            updated = item.get("updated_at", "")
            if "T" in updated: updated = updated.replace("T", " ")[:16]
            self._set_cell(row, COL_UPDATED, updated)

        self._table.resizeColumnsToContents()
        self._rebuilding = False

    def _set_cell(self, row: int, col: int, text: str, data=None) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if data is not None:
            item.setData(Qt.ItemDataRole.UserRole, data)
        self._table.setItem(row, col, item)
        return item

    # ============================================================
    # 筛选
    # ============================================================

    def _apply_filter(self):
        search = self._search_input.text().strip().lower() if self._search_input else ""

        ti = self._type_combo.currentIndex() if self._type_combo else 0
        rev = {v: k for k, v in PREF_TYPE_MAP.items()}
        type_key = rev.get(self._type_combo.currentText(), "") if ti > 0 else ""

        si = self._status_combo.currentIndex() if self._status_combo else 0
        status_key = "" if si == 0 else ("active" if si == 1 else "archived")

        coi = self._conf_op.currentIndex() if self._conf_op else 0
        cov = (self._conf_value.value() / 100.0) if self._conf_value else 0.0

        # 日期（仅勾选时生效）
        cf = self._de_str(self._created_ck, self._created_from) if self._created_ck and self._created_ck.isChecked() else ""
        ct = self._de_str(self._created_ck, self._created_to) if self._created_ck and self._created_ck.isChecked() else ""
        uf = self._de_str(self._updated_ck, self._updated_from) if self._updated_ck and self._updated_ck.isChecked() else ""
        ut = self._de_str(self._updated_ck, self._updated_to) if self._updated_ck and self._updated_ck.isChecked() else ""

        out = []
        for d in self._raw_data:
            if search and search not in d.get("content", "").lower(): continue
            if type_key and d.get("preference_type") != type_key: continue
            if status_key and d.get("status") != status_key: continue
            if coi > 0 and not self._cmp(d.get("confidence", 0), coi, cov): continue
            cr = d.get("created_at", "")[:10]
            if cf and cr < cf: continue
            if ct and cr > ct: continue
            up = d.get("updated_at", "")[:10]
            if uf and up < uf: continue
            if ut and up > ut: continue
            out.append(d)

        self._filtered_data = out
        self._populate_table(out)

    @staticmethod
    def _cmp(v, op, t):
        if op == 1: return v >= t
        if op == 2: return v <= t
        if op == 3: return v > t
        if op == 4: return v < t
        if op == 5: return abs(v - t) < 0.005
        return True

    @staticmethod
    def _de_str(ck, dp):
        if not ck or not ck.isChecked() or dp is None:
            return ""
        return dp.date().toString("yyyy-MM-dd")

    # ============================================================
    # 表头排序（三态：升序→降序→取消）
    # ============================================================

    _BASE_HEADERS = ["偏好类型", "内容", "置信度", "状态", "版本", "创建时间", "更新时间"]
    _SORT_KEYS = {
        COL_TYPE: lambda d: PREF_TYPE_MAP.get(d.get("preference_type", ""), d.get("preference_type", "")),
        COL_CONF: lambda d: d.get("confidence", 0),
        COL_STATUS: lambda d: d.get("status", ""),
        COL_VERSION: lambda d: d.get("version", 0),
        COL_CREATED: lambda d: d.get("created_at", ""),
        COL_UPDATED: lambda d: d.get("updated_at", ""),
    }

    def _on_header_clicked(self, col: int):
        if col not in SORTABLE_COLS:
            return
        cur = self._sort_state.get(col)
        # 三态循环：None → asc → desc → None
        if cur is None:
            self._sort_state[col] = "asc"
        elif cur == "asc":
            self._sort_state[col] = "desc"
        else:
            del self._sort_state[col]

        # 清其他列
        for c in list(self._sort_state):
            if c != col:
                del self._sort_state[c]

        self._update_header_labels()
        if col in self._sort_state:
            self._filtered_data.sort(key=self._SORT_KEYS[col], reverse=(self._sort_state[col] == "desc"))
            self._populate_table(self._filtered_data)
        else:
            # 取消排序：回到筛选结果原始顺序
            self._apply_filter()

    def _update_header_labels(self):
        labels = list(self._BASE_HEADERS)
        for col, order in self._sort_state.items():
            labels[col] += " ▲" if order == "asc" else " ▼"
        self._table.setHorizontalHeaderLabels(labels)

    # ============================================================
    # 行选中 → 版本链 + 证据
    # ============================================================

    def _on_row_selected(self):
        if self._rebuilding: return
        rows = self._table.selectedIndexes()
        if not rows:
            self._detail_panel.hide(); return
        row = rows[0].row()
        item = self._table.item(row, 0)
        if not item: return
        mid = item.data(Qt.ItemDataRole.UserRole)
        if not mid: return

        self._clear_detail()
        d = next((x for x in self._raw_data if x["memory_id"] == mid), None)
        if d:
            self._show_evidences(d.get("evidences", []))
            self._show_versions(d.get("versions", []))
        self._detail_panel.show()

    def _show_versions(self, versions: list[dict]):
        for v in versions:
            c = QFrame(); c.setStyleSheet("QFrame{background:#F9FAFB;border-radius:8px;}")
            cl = QHBoxLayout(c); cl.setContentsMargins(12,8,12,8); cl.setSpacing(12)
            b = QLabel(f"v{v['version']}"); b.setFont(QFont("Microsoft YaHei",10,QFont.Weight.Bold))
            b.setStyleSheet("color:#3B82F6;"); b.setFixedWidth(28); cl.addWidget(b)
            ch = QLabel(v.get("change","")); ch.setFont(QFont("Microsoft YaHei",10))
            ch.setStyleSheet("color:#374151;"); ch.setWordWrap(True)
            ch.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(ch, 1)
            dt = QLabel(v.get("created_at","")); dt.setFont(QFont("Microsoft YaHei",9))
            dt.setStyleSheet("color:#9CA3AF;")
            dt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(dt)
            self._version_list.insertWidget(self._version_list.count()-1, c)

    def _show_evidences(self, evidences: list[dict]):
        for ev in evidences:
            c = QFrame(); c.setStyleSheet("QFrame{background:#F9FAFB;border-radius:8px;}")
            cl = QVBoxLayout(c); cl.setContentsMargins(12,8,12,8); cl.setSpacing(2)
            ct = QLabel(ev.get("content","")); ct.setFont(QFont("Microsoft YaHei",10))
            ct.setStyleSheet("color:#374151;"); ct.setWordWrap(True)
            ct.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(ct)
            ts = QLabel(ev.get("timestamp","")); ts.setFont(QFont("Microsoft YaHei",9))
            ts.setStyleSheet("color:#9CA3AF;")
            ts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(ts)
            self._evidence_list.insertWidget(self._evidence_list.count()-1, c)

    def _on_cell_double_clicked(self, row: int, col: int):
        if col != COL_CONTENT: return
        item = self._table.item(row, col)
        if not item: return
        self._show_content_popup(item.text())

    def _show_content_popup(self, text: str):
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setMinimumWidth(400); dlg.setMaximumWidth(620)
        outer = QVBoxLayout(dlg); outer.setContentsMargins(8,8,8,8)
        card = QFrame(); card.setStyleSheet("QFrame{background:#ffffff;border-radius:12px;}")
        cs = QGraphicsDropShadowEffect(card); cs.setBlurRadius(24); cs.setOffset(0,4); cs.setColor(QColor(0,0,0,30))
        card.setGraphicsEffect(cs)
        cl = QVBoxLayout(card); cl.setContentsMargins(24,18,24,24); cl.setSpacing(14)
        tb = QHBoxLayout()
        t = QLabel("查看内容"); t.setFont(QFont("Microsoft YaHei",13,QFont.Weight.Bold)); t.setStyleSheet("color:#111827;")
        tb.addWidget(t); tb.addStretch()
        cb = QPushButton("✕"); cb.setFixedSize(32,32); cb.setFont(QFont("Microsoft YaHei",12))
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:8px;color:#9CA3AF;}QPushButton:hover{background:#F3F4F6;color:#374151;}")
        cb.clicked.connect(dlg.close); tb.addWidget(cb); cl.addLayout(tb)
        ct = QLabel(text); ct.setFont(QFont("Microsoft YaHei",12))
        ct.setStyleSheet("color:#374151;background:#F9FAFB;border-radius:8px;padding:16px;")
        ct.setWordWrap(True)
        ct.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(ct, 1); outer.addWidget(card); dlg.adjustSize(); dlg.exec()

    def _clear_detail(self):
        for lst in [self._version_list, self._evidence_list]:
            while lst.count() > 1:
                ch = lst.takeAt(0)
                if ch.widget(): ch.widget().deleteLater()

    # ============================================================
    # 样式工具
    # ============================================================

    def _make_label(self, text: str) -> QLabel:
        l = QLabel(text); l.setFont(QFont("Microsoft YaHei",10))
        l.setStyleSheet("color:#6B7280;background:transparent;"); return l

    def _make_section_label(self, text: str) -> QLabel:
        l = QLabel(text); l.setFont(QFont("Microsoft YaHei",12,QFont.Weight.Bold))
        l.setStyleSheet("color:#111827;background:transparent;"); return l

    def _make_date_edit(self) -> DatePicker:
        dp = DatePicker(self)
        dp.date_changed.connect(self._apply_filter)
        return dp

    def _style_table(self):
        self._table.setFont(QFont("Microsoft YaHei", 10))
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._table.setStyleSheet(TABLE_STYLE)
        h = self._table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i in range(self._table.columnCount()):
            h.setSectionResizeMode(i,
                QHeaderView.ResizeMode.Stretch if i == COL_CONTENT
                else QHeaderView.ResizeMode.ResizeToContents)
