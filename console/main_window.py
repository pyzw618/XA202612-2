"""
Kylin-MemoryHub Console — 主窗口

左侧导航栏 + 右侧页面切换（QStackedWidget）。
"""

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from console.api_client import MemoryHubClient
from console.pages.conflicts import ConflictsPage
from console.pages.dashboard import DashboardPage
from console.pages.evaluation import EvaluationPage
from console.pages.forget import ForgetPage
from console.pages.knowledge import KnowledgePage
from console.pages.preferences import PreferencesPage
from console.pages.search_test import SearchTestPage


PAGES = [
    ("📊  Dashboard", DashboardPage),
    ("❤️  偏好管理", PreferencesPage),
    ("📚  知识管理", KnowledgePage),
    ("⚡  冲突处理", ConflictsPage),
    ("🔍  检索测试", SearchTestPage),
    ("🗑️  遗忘管理", ForgetPage),
    ("📈  评测报告", EvaluationPage),
]

SIDEBAR_WIDTH = 200
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800


class MainWindow(QMainWindow):
    """主窗口：侧边栏 + 内容区"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kylin-MemoryHub Console")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(960, 600)

        # API 客户端
        self.client = MemoryHubClient()

        # 中心部件
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- 左侧导航栏 ---
        sidebar = self._build_sidebar()
        root_layout.addWidget(sidebar)

        # --- 右侧内容区 ---
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background-color: #f5f6fa;")
        root_layout.addWidget(self.stack, 1)

        # 注册所有页面
        self._register_pages()

        # 默认选中第一页
        self.sidebar_list.setCurrentRow(0)
        self.stack.setCurrentIndex(0)

    # ============================================================
    # 侧边栏
    # ============================================================

    def _build_sidebar(self) -> QWidget:
        """构建左侧导航栏"""
        container = QWidget()
        container.setFixedWidth(SIDEBAR_WIDTH)
        container.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        title = QLabel("  MemoryHub")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #cdd6f4; padding: 20px 16px;")
        title.setFixedHeight(64)
        layout.addWidget(title)

        # 分隔线
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #313244;")
        layout.addWidget(sep)

        # 导航列表
        self.sidebar_list = QListWidget()
        self.sidebar_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
                padding: 8px 0;
            }
            QListWidget::item {
                color: #a6adc8;
                padding: 12px 16px;
                font-size: 14px;
                border-left: 3px solid transparent;
            }
            QListWidget::item:hover {
                background-color: #313244;
                color: #cdd6f4;
            }
            QListWidget::item:selected {
                background-color: #45475a;
                color: #ffffff;
                border-left: 3px solid #89b4fa;
            }
        """)
        self.sidebar_list.setIconSize(QSize(20, 20))

        for label, _ in PAGES:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, 48))
            self.sidebar_list.addItem(item)

        self.sidebar_list.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.sidebar_list)

        # 底部版本信息
        footer = QLabel("  v0.1.0")
        footer.setStyleSheet("color: #585b70; padding: 12px 16px; font-size: 12px;")
        layout.addWidget(footer)

        return container

    def _on_nav_changed(self, index: int):
        """导航切换"""
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    # ============================================================
    # 页面注册
    # ============================================================

    def _register_pages(self):
        """注册所有页面到 QStackedWidget"""
        for _, page_class in PAGES:
            page = page_class(self.client)
            self.stack.addWidget(page)

    def closeEvent(self, event):
        """关闭窗口时释放资源"""
        self.client.close()
        super().closeEvent(event)