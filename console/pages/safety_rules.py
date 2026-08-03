"""
安全规则管理页面 — 用户自定义敏感信息规则 CRUD

设计：
- 顶部「新增规则」+ 刷新按钮
- 规则表格：名称 / 类型 / 效果 / 区分大小写 / 状态 / 修订号 / 更新时间 / 操作
- 操作列：编辑、启用/禁用、删除
- 新增/编辑复用弹窗（matcher 只写不回显）
- 空态 / 加载态提示
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage
from console.styles import COMBO_STYLE, INPUT_STYLE, TABLE_STYLE

KIND_MAP = {"literal": "字面量", "advanced_regex": "正则"}
EFFECT_MAP = {"mask_match": "掩码", "drop_event": "丢弃事件"}


def _fmt_time(t) -> str:
    s = str(t or "")
    return s.replace("T", " ")[:16]


class RuleDialog(QDialog):
    """新增 / 编辑安全规则弹窗"""

    def __init__(self, parent=None, rule: dict | None = None):
        super().__init__(parent)
        self._rule = rule
        self.setWindowTitle("编辑规则" if rule else "新增规则")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet("background:#ffffff;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)

        # 名称
        layout.addWidget(self._field_label("规则名称"))
        self._label = QLineEdit()
        self._label.setPlaceholderText("例如：API Key")
        self._label.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self._label)

        # 类型
        layout.addWidget(self._field_label("匹配类型"))
        self._kind = QComboBox()
        self._kind.addItems(["advanced_regex", "literal"])
        self._kind.setStyleSheet(COMBO_STYLE)
        layout.addWidget(self._kind)

        # 效果
        layout.addWidget(self._field_label("效果"))
        self._effect = QComboBox()
        self._effect.addItems(["mask_match", "drop_event"])
        self._effect.setStyleSheet(COMBO_STYLE)
        layout.addWidget(self._effect)

        # 匹配模式（仅新增时必填；编辑时留空表示不修改）
        layout.addWidget(self._field_label("匹配模式（敏感内容，保存后不回显）"))
        self._matcher = QLineEdit()
        self._matcher.setPlaceholderText("输入敏感信息模式…")
        self._matcher.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self._matcher)

        # 复选框
        self._case_sensitive = QCheckBox("区分大小写")
        self._case_sensitive.setStyleSheet("color:#374151;")
        layout.addWidget(self._case_sensitive)

        self._enabled = QCheckBox("启用")
        self._enabled.setStyleSheet("color:#374151;")
        layout.addWidget(self._enabled)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 预填
        if rule:
            self._label.setText(rule.get("label", ""))
            self._kind.setCurrentText(rule.get("kind", "advanced_regex"))
            self._effect.setCurrentText(rule.get("effect", "mask_match"))
            self._case_sensitive.setChecked(bool(rule.get("case_sensitive")))
            self._enabled.setChecked(bool(rule.get("enabled")))

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#374151;background:transparent;")
        return lbl

    def _on_save(self):
        label = self._label.text().strip()
        if not label:
            QMessageBox.warning(self, "提示", "请填写规则名称")
            return
        if self._rule is None and not self._matcher.text().strip():
            QMessageBox.warning(self, "提示", "请填写匹配模式")
            return
        self.accept()

    def values(self) -> dict:
        """返回表单值（不含未填写的 matcher）"""
        data = {
            "label": self._label.text().strip(),
            "kind": self._kind.currentText(),
            "effect": self._effect.currentText(),
            "case_sensitive": self._case_sensitive.isChecked(),
            "enabled": self._enabled.isChecked(),
        }
        matcher = self._matcher.text().strip()
        if matcher:
            data["matcher"] = matcher
        return data


class SafetyRulesPage(BasePage):
    """安全规则管理 — 用户自定义敏感规则 CRUD"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._loading: QLabel | None = None
        self._table: QTableWidget | None = None
        self._raw: list[dict] = []
        super().__init__(client, mock, title="安全规则")

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

        hint = QLabel("管理用于敏感信息过滤的自定义规则，匹配到后掩码或丢弃事件")
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet("color:#6B7280;background:transparent;")
        b_layout.addWidget(hint)
        b_layout.addStretch()

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

        add_btn = QPushButton("新增规则")
        add_btn.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        add_btn.setFixedSize(96, 34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #3B82F6;
                border: none;
                border-radius: 8px;
                color: #ffffff;
            }
            QPushButton:hover { background: #2563EB; }
        """)
        add_btn.clicked.connect(self._add_rule)
        b_layout.addWidget(add_btn)

        layout.addWidget(bar)

        # ---- 加载提示 ----
        self._loading = QLabel("正在加载安全规则…")
        self._loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading.setStyleSheet("color:#9CA3AF;font-size:14px;padding:40px;background:transparent;")
        layout.addWidget(self._loading)

        # ---- 规则表格 ----
        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            "规则名称", "类型", "效果", "区分大小写", "状态", "修订号", "更新时间", "操作",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(TABLE_STYLE)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self._table.hide()
        layout.addWidget(self._table, 1)

        # 信号
        self.mock.user_rules_ready.connect(self._on_rules)
        self.mock.error_occurred.connect(self._on_error)

    def on_page_shown(self):
        self._load()

    def _load(self):
        if self._loading:
            self._loading.show()
        if self._table:
            self._table.hide()
        self.mock.load_user_rules()

    def _on_rules(self, rules: list[dict]):
        self._loading.hide()
        self._table.show()
        self._raw = rules
        self._populate(rules)

    def _populate(self, rules: list[dict]):
        table = self._table
        table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            table.setItem(row, 0, self._text(rule.get("label", "")))
            table.setItem(row, 1, self._text(
                KIND_MAP.get(rule.get("kind", ""), rule.get("kind", ""))
            ))
            table.setItem(row, 2, self._text(
                EFFECT_MAP.get(rule.get("effect", ""), rule.get("effect", ""))
            ))
            table.setItem(row, 3, self._text("是" if rule.get("case_sensitive") else "否"))
            enabled = bool(rule.get("enabled"))
            item = QTableWidgetItem("启用" if enabled else "禁用")
            item.setForeground(Qt.GlobalColor.white)
            item.setBackground(Qt.GlobalColor.transparent)
            table.setItem(row, 4, item)
            table.setItem(row, 5, self._text(str(rule.get("revision", 1))))
            table.setItem(row, 6, self._text(_fmt_time(rule.get("updated_at"))))
            table.setCellWidget(row, 7, self._build_actions(rule))

    def _text(self, s: str) -> QTableWidgetItem:
        item = QTableWidgetItem(s)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item

    def _build_actions(self, rule: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(6)

        for text, color, slot in [
            ("编辑", "#3B82F6", self._edit_rule),
            ("启用" if not rule.get("enabled") else "禁用", "#10B981" if not rule.get("enabled") else "#F59E0B", self._toggle_rule),
            ("删除", "#EF4444", self._delete_rule),
        ]:
            btn = QPushButton(text)
            btn.setFont(QFont("Microsoft YaHei", 9))
            btn.setFixedSize(52, 26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: none;
                    border-radius: 6px;
                    color: #ffffff;
                }}
                QPushButton:hover {{ opacity: 0.85; }}
            """)
            rid = rule.get("rule_id", "")
            btn.clicked.connect(lambda checked, r=rid, s=slot: s(r))
            h.addWidget(btn)
        return w

    # ---- 操作 ----

    def _find_rule(self, rule_id: str) -> dict | None:
        for r in self._raw:
            if r.get("rule_id") == rule_id:
                return r
        return None

    def _add_rule(self):
        dlg = RuleDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            self.mock.create_user_rule(
                label=v["label"], kind=v["kind"], effect=v["effect"],
                matcher=v["matcher"], case_sensitive=v["case_sensitive"],
                enabled=v["enabled"],
            )

    def _edit_rule(self, rule_id: str):
        rule = self._find_rule(rule_id)
        if not rule:
            return
        dlg = RuleDialog(self, rule=rule)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            updates = {k: val for k, val in v.items() if k != "matcher"}
            if "matcher" in v:
                updates["matcher"] = v["matcher"]
            self.mock.update_user_rule(
                rule_id, rule.get("revision", 1), **updates
            )

    def _toggle_rule(self, rule_id: str):
        rule = self._find_rule(rule_id)
        if not rule:
            return
        self.mock.update_user_rule(
            rule_id, rule.get("revision", 1), enabled=not bool(rule.get("enabled"))
        )

    def _delete_rule(self, rule_id: str):
        rule = self._find_rule(rule_id)
        if not rule:
            return
        ret = QMessageBox.question(
            self, "确认删除",
            f"确定删除规则「{rule.get('label', '')}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.mock.delete_user_rule(rule_id, rule.get("revision", 1))

    def _on_error(self, msg: str):
        self._loading.setText(f"加载失败: {msg}")
        self._loading.setStyleSheet("color:#EF4444;font-size:14px;padding:40px;background:transparent;")