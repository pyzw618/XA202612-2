"""
知识管理页面 — 知识记忆列表 + 步骤链 + 工具链展示

功能：
- 搜索（名称 + 内容）+ 可折叠筛选面板
- 类型 / 状态 / 置信度 / 成功率（数值输入，%外置）/ 创建时间（复选框+日历）
- 表头点击排序（▲▼，三态：升序→降序→取消）
- 平滑滚动、自适应列宽
- 可滚动详情面板（执行步骤 + 调用工具）
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

KNOWLEDGE_TYPE_MAP = {"workflow": "工作流", "case": "历史案例", "template": "模板"}
STATUS_MAP = {"active": "活跃", "archived": "已归档"}

COL_TYPE = 0; COL_NAME = 1; COL_CONTENT = 2; COL_CONF = 3; COL_RATE = 4; COL_STATUS = 5; COL_CREATED = 6
SORTABLE_COLS = {COL_TYPE, COL_CONF, COL_RATE, COL_STATUS, COL_CREATED}


class KnowledgePage(BasePage):

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._table: QTableWidget | None = None
        self._filter_panel: QWidget | None = None
        self._filter_visible: bool = False
        self._type_combo: QComboBox | None = None
        self._status_combo: QComboBox | None = None
        self._conf_op: QComboBox | None = None
        self._conf_value: QDoubleSpinBox | None = None
        self._rate_op: QComboBox | None = None
        self._rate_value: QDoubleSpinBox | None = None
        self._search_input: QLineEdit | None = None
        self._created_ck: QCheckBox | None = None
        self._created_from: DatePicker | None = None
        self._created_to: DatePicker | None = None
        self._detail_panel: QWidget | None = None
        self._steps_list: QVBoxLayout | None = None
        self._tools_list: QVBoxLayout | None = None
        self._rebuilding: bool = False
        self._raw_data: list[dict] = []
        self._filtered_data: list[dict] = []
        self._sort_state: dict[int, str | None] = {}
        super().__init__(client, mock, title="知识管理")

    def setup_ui(self):
        layout = self.content.layout()

        self._loading_label = QLabel("正在加载数据...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setStyleSheet("color:#9CA3AF;font-size:14px;padding:40px;background:transparent;")
        layout.addWidget(self._loading_label)

        # 搜索栏
        self._search_bar = QWidget(); self._search_bar.setStyleSheet("background:transparent;")
        sl = QHBoxLayout(self._search_bar); sl.setContentsMargins(0,0,0,0); sl.setSpacing(12)
        self._search_input = QLineEdit(); self._search_input.setPlaceholderText("搜索名称或内容...")
        self._search_input.setFixedWidth(280); self._search_input.setStyleSheet(INPUT_STYLE)
        self._search_input.textChanged.connect(self._apply_filter); sl.addWidget(self._search_input)
        self._filter_btn = QPushButton("筛选"); self._filter_btn.setFixedWidth(72); self._filter_btn.setFixedHeight(34)
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setStyleSheet("QPushButton{background:#ffffff;border:1px solid #E5E7EB;border-radius:8px;color:#6B7280;font-size:10pt;}QPushButton:hover{border-color:#3B82F6;color:#3B82F6;}QPushButton:checked{background:#3B82F6;color:#ffffff;border-color:#3B82F6;}")
        self._filter_btn.setCheckable(True); self._filter_btn.clicked.connect(self._toggle_filter)
        sl.addWidget(self._filter_btn); sl.addStretch()
        self._search_bar.hide(); layout.addWidget(self._search_bar)

        # 筛选面板
        self._filter_panel = QWidget(); self._filter_panel.setStyleSheet("background:transparent;")
        fp = QVBoxLayout(self._filter_panel); fp.setContentsMargins(0,0,0,0); fp.setSpacing(10)

        # 行1：类型 + 状态
        r1 = QHBoxLayout(); r1.setSpacing(12)
        r1.addWidget(self._ml("类型"))
        self._type_combo = QComboBox(); self._type_combo.addItems(["全部","工作流","历史案例","模板"])
        self._type_combo.setFixedWidth(120); self._type_combo.setStyleSheet(COMBO_STYLE)
        self._type_combo.currentIndexChanged.connect(self._apply_filter); r1.addWidget(self._type_combo)
        r1.addWidget(self._ml("状态"))
        self._status_combo = QComboBox(); self._status_combo.addItems(["全部","活跃","已归档"])
        self._status_combo.setFixedWidth(100); self._status_combo.setStyleSheet(COMBO_STYLE)
        self._status_combo.currentIndexChanged.connect(self._apply_filter); r1.addWidget(self._status_combo)
        r1.addStretch(); fp.addLayout(r1)

        # 行2：置信度 + 成功率
        r2 = QHBoxLayout(); r2.setSpacing(12)
        r2.addWidget(self._ml("置信度"))
        self._conf_op = QComboBox(); self._conf_op.addItems(["不限",">=","<=",">","<","="])
        self._conf_op.setFixedWidth(80); self._conf_op.setStyleSheet(COMBO_STYLE)
        self._conf_op.currentIndexChanged.connect(self._apply_filter); r2.addWidget(self._conf_op)
        self._conf_value = QDoubleSpinBox(); self._conf_value.setRange(0,100); self._conf_value.setValue(90)
        self._conf_value.setDecimals(0); self._conf_value.setSingleStep(5); self._conf_value.setFixedWidth(80)
        self._conf_value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._conf_value.setStyleSheet(SPINBOX_STYLE)
        self._conf_value.valueChanged.connect(self._apply_filter); r2.addWidget(self._conf_value)
        r2.addWidget(self._ml("%"))

        r2.addWidget(self._ml("成功率"))
        self._rate_op = QComboBox(); self._rate_op.addItems(["不限",">=","<=",">","<","="])
        self._rate_op.setFixedWidth(80); self._rate_op.setStyleSheet(COMBO_STYLE)
        self._rate_op.currentIndexChanged.connect(self._apply_filter); r2.addWidget(self._rate_op)
        self._rate_value = QDoubleSpinBox(); self._rate_value.setRange(0,100); self._rate_value.setValue(90)
        self._rate_value.setDecimals(0); self._rate_value.setSingleStep(5); self._rate_value.setFixedWidth(80)
        self._rate_value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._rate_value.setStyleSheet(SPINBOX_STYLE)
        self._rate_value.valueChanged.connect(self._apply_filter); r2.addWidget(self._rate_value)
        r2.addWidget(self._ml("%"))
        r2.addStretch(); fp.addLayout(r2)

        # 行3：创建时间
        r3 = QHBoxLayout(); r3.setSpacing(12)
        self._created_ck = QCheckBox("创建时间")
        self._created_ck.setStyleSheet(CHECKBOX_STYLE)
        self._created_ck.setFont(QFont("Microsoft YaHei",10))
        self._created_ck.stateChanged.connect(self._apply_filter); r3.addWidget(self._created_ck)
        self._created_from = self._mkde(); r3.addWidget(self._created_from)
        r3.addWidget(self._ml("至"))
        self._created_to = self._mkde(); r3.addWidget(self._created_to)
        r3.addStretch(); fp.addLayout(r3)

        self._filter_panel.hide(); layout.addWidget(self._filter_panel)

        # 表格
        self._table_wrapper = QWidget(); self._table_wrapper.setStyleSheet("background:#ffffff;border-radius:10px;")
        sh = QGraphicsDropShadowEffect(self._table_wrapper); sh.setBlurRadius(16); sh.setOffset(0,2); sh.setColor(QColor(0,0,0,14))
        self._table_wrapper.setGraphicsEffect(sh)
        tw = QVBoxLayout(self._table_wrapper); tw.setContentsMargins(0,0,0,0)
        self._table = QTableWidget(); self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(["知识类型","名称","内容摘要","置信度","成功率","状态","创建时间"])
        self._style_table()
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.hide(); tw.addWidget(self._table)
        layout.addWidget(self._table_wrapper, 1)

        # 详情面板
        self._detail_panel = QWidget(); self._detail_panel.setObjectName("dp")
        self._detail_panel.setStyleSheet("QWidget#dp{background:#ffffff;border-radius:10px;}")
        ds = QGraphicsDropShadowEffect(self._detail_panel); ds.setBlurRadius(16); ds.setOffset(0,2); ds.setColor(QColor(0,0,0,14))
        self._detail_panel.setGraphicsEffect(ds); self._detail_panel.setFixedHeight(240)
        dl = QHBoxLayout(self._detail_panel); dl.setContentsMargins(24,16,24,16); dl.setSpacing(32)

        sg = QWidget(); sg.setStyleSheet("background:transparent;")
        sgl = QVBoxLayout(sg); sgl.setContentsMargins(0,0,0,0); sgl.setSpacing(10)
        sgl.addWidget(self._msl("执行步骤"))
        ss = QScrollArea(); ss.setWidgetResizable(True)
        ss.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ss.setStyleSheet("QScrollArea{border:none;background:transparent;}"+SCROLLBAR_STYLE)
        self._sc = QWidget(); self._sc.setStyleSheet("background:transparent;")
        self._steps_list = QVBoxLayout(self._sc); self._steps_list.setContentsMargins(0,0,8,0); self._steps_list.setSpacing(6)
        self._steps_list.addStretch(); ss.setWidget(self._sc); sgl.addWidget(ss,1); dl.addWidget(sg,1)

        sep = QWidget(); sep.setFixedWidth(1); sep.setStyleSheet("background:#F3F4F6;"); dl.addWidget(sep)

        tg = QWidget(); tg.setStyleSheet("background:transparent;")
        tgl = QVBoxLayout(tg); tgl.setContentsMargins(0,0,0,0); tgl.setSpacing(10)
        tgl.addWidget(self._msl("调用工具"))
        ts = QScrollArea(); ts.setWidgetResizable(True)
        ts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ts.setStyleSheet("QScrollArea{border:none;background:transparent;}"+SCROLLBAR_STYLE)
        self._tc = QWidget(); self._tc.setStyleSheet("background:transparent;")
        self._tools_list = QVBoxLayout(self._tc); self._tools_list.setContentsMargins(0,0,8,0); self._tools_list.setSpacing(6)
        self._tools_list.addStretch(); ts.setWidget(self._tc); tgl.addWidget(ts,1); dl.addWidget(tg,1)

        self._detail_panel.hide(); layout.addWidget(self._detail_panel)

        self.mock.knowledge_ready.connect(self._on_data_loaded)
        self.mock.error_occurred.connect(self._on_error)
        self.mock.load_knowledge()

    def _toggle_filter(self):
        self._filter_visible = not self._filter_visible
        self._filter_panel.setVisible(self._filter_visible)
        if not self._filter_visible: self._reset_filter_values()

    def on_page_shown(self): self._reset_filters()

    def _reset_filter_values(self):
        for cb in [self._type_combo, self._status_combo, self._conf_op, self._rate_op]:
            if cb: cb.blockSignals(True); cb.setCurrentIndex(0); cb.blockSignals(False)
        for sv in [self._conf_value, self._rate_value]:
            if sv: sv.blockSignals(True); sv.setValue(90); sv.blockSignals(False)
        if self._created_ck: self._created_ck.blockSignals(True); self._created_ck.setChecked(False); self._created_ck.blockSignals(False)
        for de in [self._created_from, self._created_to]:
            if de: de.blockSignals(True); de.set_date(QDate.currentDate()); de.blockSignals(False)
        self._sort_state.clear(); self._update_header_labels()
        if self._raw_data: self._filtered_data = list(self._raw_data); self._populate_table(self._filtered_data)

    def _reset_filters(self):
        if self._search_input: self._search_input.blockSignals(True); self._search_input.clear(); self._search_input.blockSignals(False)
        self._reset_filter_values()
        if self._filter_panel and self._filter_visible:
            self._filter_visible = False; self._filter_panel.hide(); self._filter_btn.setChecked(False)

    def _on_data_loaded(self, data: list[dict]):
        self._loading_label.hide(); self._raw_data = data; self._filtered_data = list(data)
        self._search_bar.show(); self._table.show(); self._populate_table(data)

    def _on_error(self, msg: str):
        self._loading_label.setText(f"加载失败: {msg}")
        self._loading_label.setStyleSheet("color:#EF4444;font-size:14px;padding:40px;background:transparent;")

    def _populate_table(self, data: list[dict]):
        self._rebuilding = True; self._table.setRowCount(len(data))
        for row, item in enumerate(data):
            tt = KNOWLEDGE_TYPE_MAP.get(item.get("knowledge_type",""), item.get("knowledge_type",""))
            self._sc2(row, COL_TYPE, tt, item["memory_id"])
            self._sc2(row, COL_NAME, item.get("name",""))
            self._sc2(row, COL_CONTENT, item.get("content",""))
            conf = item.get("confidence",0)
            ci = self._sc2(row, COL_CONF, f"{conf:.0%}")
            if conf>=0.9: ci.setForeground(QBrush(QColor("#10B981")))
            elif conf>=0.7: ci.setForeground(QBrush(QColor("#F59E0B")))
            else: ci.setForeground(QBrush(QColor("#EF4444")))
            s,t = item.get("success_count",0), item.get("total_count",0)
            self._sc2(row, COL_RATE, f"{s}/{t}" if t>0 else "—")
            self._sc2(row, COL_STATUS, STATUS_MAP.get(item.get("status",""), item.get("status","")))
            cr = item.get("created_at","")
            if "T" in cr: cr = cr.replace("T"," ")[:16]
            self._sc2(row, COL_CREATED, cr)
        self._table.resizeColumnsToContents(); self._rebuilding = False

    def _sc2(self, row, col, text, data=None):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if data is not None: item.setData(Qt.ItemDataRole.UserRole, data)
        self._table.setItem(row, col, item); return item

    def _apply_filter(self):
        search = self._search_input.text().strip().lower() if self._search_input else ""
        ti = self._type_combo.currentIndex() if self._type_combo else 0
        tk = "" if ti==0 else ("workflow" if ti==1 else ("case" if ti==2 else "template"))
        si = self._status_combo.currentIndex() if self._status_combo else 0
        sk = "" if si==0 else ("active" if si==1 else "archived")
        coi = self._conf_op.currentIndex() if self._conf_op else 0
        cov = (self._conf_value.value()/100.0) if self._conf_value else 0.0
        roi = self._rate_op.currentIndex() if self._rate_op else 0
        rov = (self._rate_value.value()/100.0) if self._rate_value else 0.0
        cf = self._des(self._created_ck, self._created_from) if self._created_ck and self._created_ck.isChecked() else ""
        ct = self._des(self._created_ck, self._created_to) if self._created_ck and self._created_ck.isChecked() else ""

        out = []
        for d in self._raw_data:
            if search:
                if search not in d.get("name","").lower() and search not in d.get("content","").lower(): continue
            if tk and d.get("knowledge_type") != tk: continue
            if sk and d.get("status") != sk: continue
            if coi>0 and not self._cmp(d.get("confidence",0), coi, cov): continue
            if roi>0:
                s,t = d.get("success_count",0), d.get("total_count",0)
                if t>0 and not self._cmp(s/t, roi, rov): continue
            cr = d.get("created_at","")[:10]
            if cf and cr<cf: continue
            if ct and cr>ct: continue
            out.append(d)
        self._filtered_data = out; self._populate_table(out)

    @staticmethod
    def _cmp(v, op, t):
        if op==1: return v>=t
        if op==2: return v<=t
        if op==3: return v>t
        if op==4: return v<t
        if op==5: return abs(v-t)<0.005
        return True

    @staticmethod
    def _des(ck, de):
        if not ck or not ck.isChecked() or de is None: return ""
        return de.date().toString("yyyy-MM-dd")

    # 排序（三态）
    _BASE_HEADERS = ["知识类型","名称","内容摘要","置信度","成功率","状态","创建时间"]
    _SORT_KEYS = {
        COL_TYPE: lambda d: KNOWLEDGE_TYPE_MAP.get(d.get("knowledge_type",""),""),
        COL_CONF: lambda d: d.get("confidence",0),
        COL_RATE: lambda d: (d.get("success_count",0)/d.get("total_count",1)) if d.get("total_count",0)>0 else 0,
        COL_STATUS: lambda d: d.get("status",""),
        COL_CREATED: lambda d: d.get("created_at",""),
    }

    def _on_header_clicked(self, col):
        if col not in SORTABLE_COLS: return
        cur = self._sort_state.get(col)
        if cur is None: self._sort_state[col] = "asc"
        elif cur == "asc": self._sort_state[col] = "desc"
        else: del self._sort_state[col]
        for c in list(self._sort_state):
            if c != col: del self._sort_state[c]
        self._update_header_labels()
        if col in self._sort_state:
            self._filtered_data.sort(key=self._SORT_KEYS[col], reverse=(self._sort_state[col]=="desc"))
            self._populate_table(self._filtered_data)
        else:
            self._apply_filter()

    def _update_header_labels(self):
        labels = list(self._BASE_HEADERS)
        for col, order in self._sort_state.items():
            labels[col] += " ▲" if order=="asc" else " ▼"
        self._table.setHorizontalHeaderLabels(labels)

    def _on_row_selected(self):
        if self._rebuilding: return
        rows = self._table.selectedIndexes()
        if not rows: self._detail_panel.hide(); return
        row = rows[0].row(); item = self._table.item(row, 0)
        if not item: return
        mid = item.data(Qt.ItemDataRole.UserRole)
        if not mid: return
        self._clear_detail()
        d = next((x for x in self._raw_data if x["memory_id"]==mid), None)
        if d: self._show_steps(d.get("steps",[])); self._show_tools(d.get("tools",[]))
        self._detail_panel.show()

    def _show_steps(self, steps):
        for i, step in enumerate(steps):
            c = QFrame(); c.setStyleSheet("QFrame{background:#F9FAFB;border-radius:8px;}")
            cl = QHBoxLayout(c); cl.setContentsMargins(12,8,12,8); cl.setSpacing(12)
            b = QLabel(f"{i+1}"); b.setFont(QFont("Microsoft YaHei",10,QFont.Weight.Bold))
            b.setStyleSheet("color:#3B82F6;"); b.setFixedWidth(20); cl.addWidget(b)
            t = QLabel(step); t.setFont(QFont("Microsoft YaHei",10)); t.setStyleSheet("color:#374151;")
            t.setWordWrap(True); t.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(t, 1); self._steps_list.insertWidget(self._steps_list.count()-1, c)

    def _show_tools(self, tools):
        if not tools:
            e = QLabel("暂无调用工具"); e.setFont(QFont("Microsoft YaHei",10)); e.setStyleSheet("color:#9CA3AF;")
            self._tools_list.insertWidget(self._tools_list.count()-1, e); return
        for tool in tools:
            c = QFrame(); c.setStyleSheet("QFrame{background:#F9FAFB;border-radius:8px;}")
            cl = QHBoxLayout(c); cl.setContentsMargins(12,8,12,8)
            dot = QLabel(); dot.setFixedSize(6,6); dot.setStyleSheet("background:#3B82F6;border-radius:3px;"); cl.addWidget(dot)
            n = QLabel(tool); n.setFont(QFont("Microsoft YaHei",10)); n.setStyleSheet("color:#374151;")
            n.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cl.addWidget(n, 1); self._tools_list.insertWidget(self._tools_list.count()-1, c)

    def _on_cell_double_clicked(self, row, col):
        if col != COL_CONTENT: return
        item = self._table.item(row, col)
        if not item: return
        self._popup(item.text())

    def _popup(self, text):
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
        ct.setWordWrap(True); ct.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(ct, 1); outer.addWidget(card); dlg.adjustSize(); dlg.exec()

    def _clear_detail(self):
        for lst in [self._steps_list, self._tools_list]:
            while lst.count() > 1:
                ch = lst.takeAt(0)
                if ch.widget(): ch.widget().deleteLater()

    def _ml(self, t): l = QLabel(t); l.setFont(QFont("Microsoft YaHei",10)); l.setStyleSheet("color:#6B7280;background:transparent;"); return l
    def _msl(self, t): l = QLabel(t); l.setFont(QFont("Microsoft YaHei",12,QFont.Weight.Bold)); l.setStyleSheet("color:#111827;background:transparent;"); return l

    def _mkde(self) -> DatePicker:
        dp = DatePicker(self)
        dp.date_changed.connect(self._apply_filter)
        return dp

    def _style_table(self):
        self._table.setFont(QFont("Microsoft YaHei",10))
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True); self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._table.setStyleSheet(TABLE_STYLE)
        h = self._table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i in range(self._table.columnCount()):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i==COL_CONTENT else QHeaderView.ResizeMode.ResizeToContents)
