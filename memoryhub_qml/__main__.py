from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .api import MemoryHubApi
from .controller import MemoryHubController


def main() -> int:
    parser = argparse.ArgumentParser(description="MemoryHub PySide6 + QML desktop client")
    parser.add_argument("--backend-url", default=os.environ.get("MEMORYHUB_BACKEND_URL"))
    parser.add_argument("--demo", help="Path to a conversation-replay/1.0 JSON file")
    args = parser.parse_args()

    QCoreApplication.setOrganizationName("MemoryHub")
    QCoreApplication.setApplicationName("MemoryHub QML")
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(sys.argv[:1])

    api = MemoryHubApi(args.backend_url)
    controller = MemoryHubController(api, args.demo)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    qml_path = Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 1
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
