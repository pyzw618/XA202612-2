from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine

from memoryhub_qml.api import MemoryHubApi
from memoryhub_qml.controller import MemoryHubController


def test_main_qml_loads_offscreen(qapp):
    api = MemoryHubApi("http://127.0.0.1:65534")
    controller = MemoryHubController(api)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    path = Path(__file__).parents[1] / "memoryhub_qml" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects()
    engine.deleteLater()
