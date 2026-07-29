"""
Kylin-MemoryHub Console — 入口

启动方式:
    python -m console.main
    或
    cd console && python main.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from console.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Kylin-MemoryHub Console")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()