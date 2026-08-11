"""
遗忘管理页面 — 自然语言遗忘 + 遗忘历史

设计：
- 顶部自然语言遗忘输入框 + 遗忘按钮
- 执行后显示结果卡片（删除条数 + 涉及的记忆 + 审计日志）
- 下方遗忘历史表格（指令 / 删除条数 / 时间）
- 空态 / 加载态提示
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.base import BasePage
from console.styles import INPUT_STYLE, TABLE_STYLE


class ForgetPage(BasePage):
    """遗忘管理 — 自然语言遗忘 + 遗忘历史"""

    def __init__(self, client: MemoryHubClient, mock: MockDataController):
        self._result_card: QFrame | None = None
        self._result_title: QLabel | None = None
        self._result_detail: QLabel | None = None
        self._history_table: QTableWidget | None = None
        self._initialized: bool = False
        super().__init__(client, mock, title="遗忘管理")

    def setup_ui(self):
        layout = self.content.layout()

        # ---- 顶部遗忘输入区 ----
        input_panel = QFrame()
        input_panel.setStyleSheet("""
            QFrame { background: #ffffff; border-radius: 12px; }
        """)
        i_layout = QVBoxLayout(input_panel)
        i_layout.setContentsMargins(20, 18, 20, 18)
        i_layout.setSpacing(12)

        hint = QLabel("用自然语言描述要遗忘的记忆，例如「忘掉我关于周报格式的偏好」")
        hint.setFont(QFont("Microsoft YaHei", 10))
        hint.setStyleSheet("color:#6B7280;background:transparent;")
        i_layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(12)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入遗忘指令…")
        self._input.setStyleSheet(INPUT_STYLE)
        self._input.setFont(QFont("Microsoft YaHei", 11))
        self._input.returnPressed.connect(self._do_forget)
        row.addWidget(self._input, 1)

        self._forget_btn = QPushButton("遗忘")
        self._forget_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._forget_btn.setFixedSize(96, 38)
        self._forget_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._forget_btn.setStyleSheet("""
            QPushButton {
                background: #EF4444;
                border: none;
                border-radius: 8px;
                color: #ffffff;
            }
            QPushButton:hover { background: #DC2626; }
            QPushButton:disabled { background: #FCA5A5; }
        """)
        self._forget_btn.clicked.connect(self._do_forget)
        row.addWidget(self._forget_btn)

        i_layout.addLayout(row)

        # 结果卡片（默认隐藏）
        self._result_card = QFrame()
        self._result_card.setStyleSheet("""
            QFrame {
                background: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 10px;
            }
        """)
        r_layout = QVBoxLayout(self._result_card)
        r_layout.setContentsMargins(16, 12, 16, 12)
        r_layout.setSpacing(6)

        self._result_title = QLabel()
        self._result_title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._result_title.setStyleSheet("color:#B91C1C;background:transparent;")
        r_layout.addWidget(self._result_title)

        self._result_detail = QLabel()
        self._result_detail.setFont(QFont("Microsoft YaHei", 10))
        self._result_detail.setStyleSheet("color:#7F1D1D;background:transparent;")
        self._result_detail.setWordWrap(True)
        self._result_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        r_layout.addWidget(self._result_detail)

        self._result_card.hide()
        i_layout.addWidget(self._result_card)

        layout.addWidget(input_panel)

        # ---- 历史区标题 ----
        hist_head = QHBoxLayout()
        hist_head.setSpacing(8)
        hist_title = QLabel("遗忘历史")
        hist_title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        hist_title.setStyleSheet("color:#111827;background:transparent;")
        hist_head.addWidget(hist_title)
        hist_head.addStretch()
        layout.addLayout(hist_head)

        # ---- 遗忘历史表格 ----
        self._history_table = QTableWidget(0, 3)
        self._history_table.setHorizontalHeaderLabels(["指令", "删除条数", "时间"])
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setStyleSheet(TABLE_STYLE)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self._history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._history_table, 1)

        # 信号
        self.mock.forget_result_ready.connect(self._on_result)
        self.mock.forget_history_ready.connect(self._on_history)
        self.mock.error_occurred.connect(self._on_error)

    def on_page_shown(self):
        # 首次进入时加载历史，之后每次切回也刷新
        self.mock.load_forget_history()

    # ---- 遗忘操作 ----

    def _do_forget(self):
        instruction = self._input.text().strip()
        if not instruction:
            return
        self._forget_btn.setEnabled(False)
        self._forget_btn.setText("遗忘中…")
        self.mock.forget(instruction)

    def _on_result(self, data: dict):
        self._forget_btn.setEnabled(True)
        self._forget_btn.setText("遗忘")

        deleted = data.get("deleted_count", 0)
        deleted_ids = data.get("deleted_ids", [])
        audit = data.get("audit_log", "")

        if deleted > 0:
            self._result_title.setText(f"已遗忘 {deleted} 条记忆")
            ids_text = "、".join(deleted_ids) if deleted_ids else "无"
            self._result_detail.setText(
                f"涉及的记忆 ID：{ids_text}\n{audit}"
            )
        else:
            self._result_title.setText("未遗忘任何记忆")
            self._result_detail.setText(
                audit or "没有找到与指令匹配的记忆，可能需要更精确的描述。"
            )
        self._result_card.show()

        # 遗忘后刷新历史
        self.mock.load_forget_history()

    # ---- 历史 ----

    def _on_history(self, items: list[dict]):
        table = self._history_table
        table.setRowCount(len(items))
        for row, item in enumerate(items):
            instruction = QTableWidgetItem(item.get("instruction", ""))
            instruction.setTextAlignment(Qt.AlignmentFlag.AlignVCenter
                                         | Qt.AlignmentFlag.AlignLeft)
            table.setItem(row, 0, instruction)

            deleted = QTableWidgetItem(str(item.get("deleted_count", 0)))
            deleted.setTextAlignment(Qt.AlignmentFlag.AlignVCenter
                                     | Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 1, deleted)

            created = str(item.get("created_at", ""))[:16].replace("T", " ")
            time_item = QTableWidgetItem(created)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter
                                       | Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 2, time_item)

    def _on_error(self, msg: str):
        self._forget_btn.setEnabled(True)
        self._forget_btn.setText("遗忘")
        self._result_title.setText("操作失败")
        self._result_detail.setText(msg)
        self._result_card.setStyleSheet("""
            QFrame {
                background: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 10px;
            }
        """)
        self._result_card.show()