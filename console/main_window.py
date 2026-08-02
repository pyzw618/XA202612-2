"""
主窗口 — 麒麟 UKUI 风格无边框窗口

设计要点：
- 白底黑字，浅灰侧边栏，蓝色选中态
- 无边框 + 圆角 + 轻阴影
- 自定义标题栏，支持拖拽移动和边缘缩放
- 最大化时自动去圆角（手动几何管理，避免 Windows 分层窗口 bug）
"""

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.mock_data import MockDataController
from console.pages.conflicts import ConflictsPage
from console.pages.dashboard import DashboardPage
from console.pages.evaluation import EvaluationPage
from console.pages.forget import ForgetPage
from console.pages.knowledge import KnowledgePage
from console.pages.preferences import PreferencesPage
from console.pages.search_test import SearchTestPage
from console.widgets.sidebar import Sidebar

WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 780
CORNER_RADIUS = 12
TITLE_BAR_HEIGHT = 44
SHADOW_OFFSET = 8
RESIZE_MARGIN = 8

_EDGE_NONE = 0
_EDGE_LEFT = 1
_EDGE_RIGHT = 2
_EDGE_TOP = 3
_EDGE_BOTTOM = 4
_EDGE_TOP_LEFT = 5
_EDGE_TOP_RIGHT = 6
_EDGE_BOTTOM_LEFT = 7
_EDGE_BOTTOM_RIGHT = 8

_EDGE_CURSORS = {
    _EDGE_LEFT: Qt.CursorShape.SizeHorCursor,
    _EDGE_RIGHT: Qt.CursorShape.SizeHorCursor,
    _EDGE_TOP: Qt.CursorShape.SizeVerCursor,
    _EDGE_BOTTOM: Qt.CursorShape.SizeVerCursor,
    _EDGE_TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    _EDGE_BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    _EDGE_TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    _EDGE_BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
}


class MainWindow(QMainWindow):
    """UKUI 风格主窗口"""

    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(900, 560)

        self.client = MemoryHubClient()
        self.mock = MockDataController(client=self.client)

        # 最大化状态必须在 _setup_ui 之前初始化（_apply_style 会读它）
        self._maximized: bool = False
        self._restore_geom: QRect | None = None

        self._setup_ui()
        self._setup_shadow()

        self._drag_pos: QPoint | None = None
        self._resize_edge: int = _EDGE_NONE
        self._resize_start_geom: QRect | None = None
        self._hover_edge: int = _EDGE_NONE

        QApplication.instance().installEventFilter(self)

    def _setup_ui(self):
        self._outer = QWidget()
        self._outer.setObjectName("outer")
        self.setCentralWidget(self._outer)
        self._outer_layout = QVBoxLayout(self._outer)
        self._outer_layout.setContentsMargins(
            SHADOW_OFFSET, SHADOW_OFFSET, SHADOW_OFFSET, SHADOW_OFFSET
        )

        self._inner = QWidget()
        self._inner.setObjectName("inner")
        self._apply_style()
        self._outer_layout.addWidget(self._inner)

        inner = QVBoxLayout(self._inner)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        inner.addWidget(self._build_title_bar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self._on_nav_changed)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: #f5f6fa;")
        body.addWidget(self.stack, 1)

        inner.addLayout(body, 1)

        self._register_pages()
        self.sidebar.select(0)

    def _apply_style(self):
        if self._maximized:
            self._inner.setStyleSheet(
                "#inner { background-color: #ffffff; border-radius: 0px; border: none; }"
            )
        else:
            self._inner.setStyleSheet(
                f"#inner {{ background-color: #ffffff; border-radius: {CORNER_RADIUS}px;"
                f" border: 1px solid rgba(0,0,0,0.06); }}"
            )

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(TITLE_BAR_HEIGHT)
        bar.setStyleSheet("background: #ffffff; border: none;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)

        title = QLabel("  Kylin-MemoryHub")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #374151; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        for text, slot in [
            ("_", self._on_minimize),
            ("[]", self._on_maximize),
            ("X", self.close),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(36, 28)
            btn.setFont(QFont("Microsoft YaHei", 10))
            btn.setStyleSheet("""
                QPushButton { background: transparent; border: none; border-radius: 6px; color: #9CA3AF; }
                QPushButton:hover { background-color: #F3F4F6; color: #374151; }
            """)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        return bar

    def _setup_shadow(self):
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 40))
        self._outer.setGraphicsEffect(shadow)

    def _register_pages(self):
        pages = [
            ("Dashboard", DashboardPage),
            ("偏好管理", PreferencesPage),
            ("知识管理", KnowledgePage),
            ("冲突处理", ConflictsPage),
            ("检索测试", SearchTestPage),
            ("遗忘管理", ForgetPage),
            ("评测报告", EvaluationPage),
        ]
        for label, page_cls in pages:
            page = page_cls(self.client, self.mock)
            self.stack.addWidget(page)
            self.sidebar.add_item(label)

    def _on_nav_changed(self, index: int):
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    # ============================================================
    # 最小化 / 最大化（手动几何管理，不触发 Windows 分层窗口 bug）
    # ============================================================

    def _on_minimize(self):
        self.showMinimized()

    def _on_maximize(self):
        if self._maximized:
            self._restore()
        else:
            self._maximize()

    def _maximize(self):
        self._restore_geom = self.geometry()
        self._maximized = True
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        self._apply_style()

    def _restore(self):
        self._maximized = False
        self._outer_layout.setContentsMargins(
            SHADOW_OFFSET, SHADOW_OFFSET, SHADOW_OFFSET, SHADOW_OFFSET
        )
        if self._restore_geom is not None:
            self.setGeometry(self._restore_geom)
        self._apply_style()

    def changeEvent(self, event):
        """阻止 Windows 自身的最大化（如 Win+↑），统一走手动逻辑"""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMaximized():
                self.showNormal()
                self._maximize()
        super().changeEvent(event)

    # ============================================================
    # 边缘检测
    # ============================================================

    def _detect_edge(self, pos: QPoint) -> int:
        if self._maximized:
            return _EDGE_NONE
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        left = x <= RESIZE_MARGIN
        right = x >= w - RESIZE_MARGIN
        top = y <= RESIZE_MARGIN
        bottom = y >= h - RESIZE_MARGIN
        if top and left:
            return _EDGE_TOP_LEFT
        if top and right:
            return _EDGE_TOP_RIGHT
        if bottom and left:
            return _EDGE_BOTTOM_LEFT
        if bottom and right:
            return _EDGE_BOTTOM_RIGHT
        if left:
            return _EDGE_LEFT
        if right:
            return _EDGE_RIGHT
        if top:
            return _EDGE_TOP
        if bottom:
            return _EDGE_BOTTOM
        return _EDGE_NONE

    # ============================================================
    # 全局事件过滤器
    # ============================================================

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()
        if not self._belongs_to_me(obj):
            return super().eventFilter(obj, event)

        if etype == QEvent.Type.MouseMove:
            gp = event.globalPosition().toPoint()
            lp = self.mapFromGlobal(gp)

            if self._drag_pos is not None:
                delta = gp - self._drag_pos
                if self._resize_edge != _EDGE_NONE:
                    self._do_resize(delta)
                else:
                    self.move(self.pos() + delta)
                    self._drag_pos = gp
                return True

            edge = self._detect_edge(lp)
            if edge != self._hover_edge:
                self._hover_edge = edge
                if edge != _EDGE_NONE:
                    QApplication.setOverrideCursor(_EDGE_CURSORS[edge])
                else:
                    QApplication.restoreOverrideCursor()

        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                if isinstance(obj, QPushButton):
                    return False
                lp = self.mapFromGlobal(event.globalPosition().toPoint())
                edge = self._detect_edge(lp)
                if edge != _EDGE_NONE:
                    self._resize_edge = edge
                    self._resize_start_geom = self.geometry()
                    self._drag_pos = event.globalPosition().toPoint()
                    return True
                if lp.y() <= TITLE_BAR_HEIGHT + SHADOW_OFFSET:
                    self._drag_pos = event.globalPosition().toPoint()
                    return True

        elif etype == QEvent.Type.MouseButtonRelease:
            self._drag_pos = None
            self._resize_edge = _EDGE_NONE
            self._resize_start_geom = None

        elif etype == QEvent.Type.Leave:
            if obj is self:
                self._hover_edge = _EDGE_NONE
                QApplication.restoreOverrideCursor()

        return super().eventFilter(obj, event)

    def _belongs_to_me(self, obj: QObject) -> bool:
        while obj is not None:
            if obj is self:
                return True
            obj = obj.parent()
        return False

    def _do_resize(self, delta: QPoint):
        if self._resize_start_geom is None:
            return
        g = QRect(self._resize_start_geom)
        dx, dy = delta.x(), delta.y()
        e = self._resize_edge
        mw, mh = self.minimumWidth(), self.minimumHeight()
        if e in (_EDGE_LEFT, _EDGE_TOP_LEFT, _EDGE_BOTTOM_LEFT):
            g.setLeft(min(g.left() + dx, g.right() - mw))
        if e in (_EDGE_RIGHT, _EDGE_TOP_RIGHT, _EDGE_BOTTOM_RIGHT):
            g.setRight(max(g.right() + dx, g.left() + mw))
        if e in (_EDGE_TOP, _EDGE_TOP_LEFT, _EDGE_TOP_RIGHT):
            g.setTop(min(g.top() + dy, g.bottom() - mh))
        if e in (_EDGE_BOTTOM, _EDGE_BOTTOM_LEFT, _EDGE_BOTTOM_RIGHT):
            g.setBottom(max(g.bottom() + dy, g.top() + mh))
        self.setGeometry(g)

    def closeEvent(self, event):
        self.client.close()
        super().closeEvent(event)