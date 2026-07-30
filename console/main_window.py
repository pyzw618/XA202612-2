"""
主窗口 — UKUI 风格无边框毛玻璃窗口

设计要点：
- 无边框 + 圆角（通过 QPainterPath 裁剪）
- 半透明背景模拟毛玻璃效果
- 自定义标题栏，支持拖拽移动
- 阴影效果
"""

from PyQt6.QtCore import Qt, QPoint, QRectF
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
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


class MainWindow(QMainWindow):
    """UKUI 风格主窗口"""

    def __init__(self):
        super().__init__()

        # 无边框 + 半透明背景
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(900, 560)

        # 数据层
        self.client = MemoryHubClient()
        self.mock = MockDataController()

        # 中心容器（承载所有内容，留出阴影空间）
        self._setup_central_container()

        # 窗口阴影
        self._setup_shadow()

        # 拖拽相关
        self._drag_pos: QPoint | None = None

    def _setup_central_container(self):
        """构建中心容器：标题栏 + 侧边栏 + 内容区，所有内容在圆角矩形内"""
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

        # 侧边栏
        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self._on_nav_changed)
        body.addWidget(self.sidebar)

        # 内容区
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        body.addWidget(self.stack, 1)

        inner_layout.addLayout(body, 1)

        # 注册页面
        self._register_pages()
        self.sidebar.select(0)

    def _build_title_bar(self) -> QWidget:
        """构建自定义标题栏：Logo + 标题 + 窗口控制按钮"""
        bar = QWidget()
        bar.setFixedHeight(TITLE_BAR_HEIGHT)
        bar.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)

        # Logo 图标（用 Unicode 占位）
        logo = QLabel("🖥")
        logo.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(logo)

        # 标题
        title = QLabel("Kylin-MemoryHub Console")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #1e1e2e;")
        layout.addWidget(title)
        layout.addStretch()

        # 窗口控制按钮
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
            ("📊", "Dashboard", DashboardPage),
            ("❤️", "偏好管理", PreferencesPage),
            ("📚", "知识管理", KnowledgePage),
            ("⚡", "冲突处理", ConflictsPage),
            ("🔍", "检索测试", SearchTestPage),
            ("🗑", "遗忘管理", ForgetPage),
            ("📈", "评测报告", EvaluationPage),
        ]
        for icon, label, page_cls in pages:
            page = page_cls(self.client, self.mock)
            self.stack.addWidget(page)
            self.sidebar.add_item(icon, label)

    def _on_nav_changed(self, index: int):
        """侧边栏导航切换"""
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    def _toggle_maximize(self):
        """切换最大化/还原"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ============================================================
    # 无边框窗口拖拽
    # ============================================================

    def mousePressEvent(self, event):
        """记录拖拽起点"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 只在标题栏区域响应拖拽
            if event.position().y() <= TITLE_BAR_HEIGHT + SHADOW_OFFSET:
                self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """拖拽移动窗口"""
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """结束拖拽"""
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        self.client.close()
        super().closeEvent(event)