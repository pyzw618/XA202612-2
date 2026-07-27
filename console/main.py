"""
Kylin-MemoryHub Console — 前端管理界面入口

PyQt6 原生桌面应用，用于管理 OS Agent 的记忆中枢。
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Kylin-MemoryHub Console")

    # TODO: 初始化主窗口和各页面

    sys.exit(app.exec())


if __name__ == "__main__":
    main()