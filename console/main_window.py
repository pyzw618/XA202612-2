"""
主窗口 — UKUI 风格无边框毛玻璃窗口

设计要点：
- 无边框 + 圆角（通过 QPainterPath 裁剪）
- 半透明背景模拟毛玻璃效果
- 自定义标题栏，支持拖拽移动
- 窗口边缘拖拽缩放（8 个方向）
- 阴影效果
"""

from PyQt6.QtCore import Qt, QPoint, QRect, QSize
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
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

# ---- 窗口常量 ----
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 780
CORNER_RADIUS = 12
TITLE_BAR_HEIGHT = 44
SHADOW_OFFSET = 8
RESIZE_MARGIN = 8  # 边缘缩放检测区域

# 边缘方向常量
_EDGE_NONE = 0
_EDGE_LEFT = 1
_EDGE_RIGHT = 2
_EDGE_TOP = 3
_EDGE_BOTTOM = 4
_EDGE_TOP_LEFT = 5
_EDGE_TOP_RIGHT = 6
_EDGE_BOTTOM_LEFT = 7
_EDGE_BOTTOM_RIGHT = 8


class MainWindow(QMainWindow):
    """UKUI 风格主窗口 — 无边框，支持拖拽移动和边缘缩放"""

    def __init__(self):
        super().__init__()

        # 无边框 + 半透明背景
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(900, 560)

        # 数据层：通过环境变量 MEMORYHUB_LIVE_BACKEND=1 切换实时后端
        import os
        self._use_live = os.environ.get("MEMORYHUB_LIVE_BACKEND", "").lower() in ("1", "true", "yes")
        self.client = MemoryHubClient()
        self.mock = MockDataController() if not self._use_live else None

        # 中心容器（承载所有内容，留出阴影空间）
        self._setup_central_container()

        # 窗口阴影
        self._setup_shadow()

        # 拖拽 / 缩放状态
        self._drag_pos: QPoint | None = None
        self._resize_edge: int = _EDGE_NONE
        self._resize_start_geom: QRect | None = None

    def _setup_central_container(self):
        """构建中心容器：标题栏 + 侧边栏 + 内容区"""
        # 外层容器留出阴影 margin
        outer = QWidget()
        outer.setObjectName("outer_container")
        self.setCentralWidget(outer)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(
            SHADOW_OFFSET, SHADOW_OFFSET, SHADOW_OFFSET, SHADOW_OFFSET
        )

        # 内层容器 — 实际内容区域，圆角背景
        self._inner = QWidget()
        self._inner.setObjectName("inner_container")
        self._inner.setStyleSheet(f"""
            #inner_container {{
                background-color: rgba(245, 247, 250, 0.97);
                border-radius: {CORNER_RADIUS}px;
            }}
        """)
        outer_layout.addWidget(self._inner)

        inner_layout = QVBoxLayout(self._inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

        # ---- 自定义标题栏 ----
        inner_layout.addWidget(self._build_title_bar())

        # ---- 下方：侧边栏 + 内容区 ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self._on_nav_changed)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        body.addWidget(self.stack, 1)

        inner_layout.addLayout(body, 1)

        self._register_pages()
        self.sidebar.select(0)

    def _build_title_bar(self) -> QWidget:
        """构建自定义标题栏：Logo + 标题 + 窗口控制按钮"""
        bar = QWidget()
        bar.setFixedHeight(TITLE_BAR_HEIGHT)
        bar.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)

        logo = QLabel("\U0001f5a5")
        logo.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(logo)

        title = QLabel("Kylin-MemoryHub Console")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #1e1e2e;")
        layout.addWidget(title)
        layout.addStretch()

        for symbol, slot in [("─", self.showMinimized), ("□", self._toggle_maximize), ("✕", self.close)]:
            btn = QPushButton(symbol)
            btn.setFixedSize(36, 28)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 6px;
                    font-size: 14px;
                    color: #585b70;
                }
                QPushButton:hover {
                    background-color: rgba(0, 0, 0, 0.08);
                    color: #1e1e2e;
                }
            """)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        return bar

    def _setup_shadow(self):
        """给窗口添加阴影"""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.centralWidget().setGraphicsEffect(shadow)

    def _register_pages(self):
        """注册所有页面到 QStackedWidget"""
        pages = [
            ("\U0001f4ca", "Dashboard", DashboardPage),
            ("❤️", "偏好管理", PreferencesPage),
            ("\U0001f4da", "知识管理", KnowledgePage),
            ("⚡", "冲突处理", ConflictsPage),
            ("\U0001f50d", "检索测试", SearchTestPage),
            ("\U0001f5d1", "遗忘管理", ForgetPage),
            ("\U0001f4c8", "评测报告", EvaluationPage),
        ]
        for icon, label, page_cls in pages:
            page = page_cls(self.client, self.mock)
            self.stack.addWidget(page)
            self.sidebar.add_item(icon, label)

    def _on_nav_changed(self, index: int):
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ============================================================
    # 边缘检测
    # ============================================================

    def _detect_edge(self, pos: QPoint) -> int:
        """判断鼠标位置在窗口的哪个边缘，返回边缘常量"""
        # 使用窗口外层的坐标来判断（包含阴影 margin）
        w = self.width()
        h = self.height()
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

    def _edge_cursor(self, edge: int) -> Qt.CursorShape:
        """根据边缘方向返回对应的鼠标指针形状"""
        _cursors = {
            _EDGE_LEFT: Qt.CursorShape.SizeHorCursor,
            _EDGE_RIGHT: Qt.CursorShape.SizeHorCursor,
            _EDGE_TOP: Qt.CursorShape.SizeVerCursor,
            _EDGE_BOTTOM: Qt.CursorShape.SizeVerCursor,
            _EDGE_TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
            _EDGE_BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
            _EDGE_TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
            _EDGE_BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
        }
        return _cursors.get(edge, Qt.CursorShape.ArrowCursor)

    # ============================================================
    # 鼠标事件 — 拖拽移动 + 边缘缩放
    # ============================================================

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position().toPoint()
        edge = self._detect_edge(pos)

        if edge != _EDGE_NONE:
            # 边缘缩放
            self._resize_edge = edge
            self._resize_start_geom = self.geometry()
            self._drag_pos = event.globalPosition().toPoint()
        elif pos.y() <= TITLE_BAR_HEIGHT + SHADOW_OFFSET:
            # 标题栏拖拽
            self._drag_pos = event.globalPosition().toPoint()
            self._resize_edge = _EDGE_NONE
        else:
            self._resize_edge = _EDGE_NONE
            self._drag_pos = None

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()

        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos

            if self._resize_edge != _EDGE_NONE:
                # 缩放窗口
                self._apply_resize(delta)
            else:
                # 移动窗口
                self.move(self.pos() + delta)
                self._drag_pos = event.globalPosition().toPoint()
        else:
            # 未按下鼠标时，根据位置切换指针形状
            edge = self._detect_edge(pos)
            self.setCursor(self._edge_cursor(edge))

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._resize_edge = _EDGE_NONE
        self._resize_start_geom = None
        super().mouseReleaseEvent(event)

    def _apply_resize(self, delta: QPoint):
        """根据当前缩放边缘和鼠标位移计算新窗口几何"""
        if self._resize_start_geom is None:
            return
        g = QRect(self._resize_start_geom)
        dx, dy = delta.x(), delta.y()

        edge = self._resize_edge
        if edge in (_EDGE_LEFT, _EDGE_TOP_LEFT, _EDGE_BOTTOM_LEFT):
            g.setLeft(min(g.left() + dx, g.right() - self.minimumWidth()))
        if edge in (_EDGE_RIGHT, _EDGE_TOP_RIGHT, _EDGE_BOTTOM_RIGHT):
            g.setRight(max(g.right() + dx, g.left() + self.minimumWidth()))
        if edge in (_EDGE_TOP, _EDGE_TOP_LEFT, _EDGE_TOP_RIGHT):
            g.setTop(min(g.top() + dy, g.bottom() - self.minimumHeight()))
        if edge in (_EDGE_BOTTOM, _EDGE_BOTTOM_LEFT, _EDGE_BOTTOM_RIGHT):
            g.setBottom(max(g.bottom() + dy, g.top() + self.minimumHeight()))

        self.setGeometry(g)

    def closeEvent(self, event):
        self.client.close()
        super().closeEvent(event)