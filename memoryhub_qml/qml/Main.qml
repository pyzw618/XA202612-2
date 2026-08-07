import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "components"

ApplicationWindow {
    id: window
    width: 1480
    height: 900
    minimumWidth: 980
    minimumHeight: 680
    visible: true
    title: "MemoryHub · 本地记忆工作台"
    color: "#F4F7FB"
    font.family: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "Noto Sans CJK SC"
    property bool compact: width < 1280

    component MenuButton: Button {
        required property string sectionId
        required property string sectionText
        Layout.fillWidth: true
        implicitHeight: 34
        text: sectionText
        checkable: true
        checked: controller.activeSection === sectionId
        font.pixelSize: 12
        leftPadding: 12
        background: Rectangle { radius: 8; color: parent.checked ? "#2563EB" : "transparent" }
        contentItem: Label { text: parent.text; color: parent.checked ? "white" : "#CBD5E1"; verticalAlignment: Text.AlignVCenter; leftPadding: 4; font.pixelSize: 12 }
        onClicked: controller.selectSection(sectionId)
    }

    FileDialog {
        id: importDialog
        title: "导入 conversation-replay/1.0 JSON"
        nameFilters: ["JSON 文件 (*.json)"]
        onAccepted: controller.importReplay(selectedFile.toString())
    }
    FactDialog { id: factDialog }

    header: Rectangle {
        height: 70; color: "white"; border.color: "#E6EBF2"
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 24; anchors.rightMargin: 24; spacing: 16
            Rectangle { width: 38; height: 38; radius: 11; color: "#2563EB"; Label { anchors.centerIn: parent; text: "M"; color: "white"; font.pixelSize: 22; font.bold: true } }
            ColumnLayout { spacing: 1; Label { text: "MemoryHub"; color: "#14213D"; font.pixelSize: 19; font.bold: true } Label { text: "LOCAL MEMORY WORKBENCH"; color: "#94A3B8"; font.pixelSize: 9; font.letterSpacing: 1.2 } }
            Rectangle { width: 1; Layout.fillHeight: true; Layout.topMargin: 15; Layout.bottomMargin: 15; color: "#E2E8F0" }
            ColumnLayout { Layout.fillWidth: true; spacing: 2; Label { text: controller.title; color: "#172033"; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true } Label { text: controller.sessionId; color: "#94A3B8"; font.pixelSize: 11; elide: Text.ElideMiddle; Layout.fillWidth: true } }
            Rectangle { width: 108; height: 32; radius: 16; color: controller.online ? "#ECFDF5" : "#FEF2F2"; Row { anchors.centerIn: parent; spacing: 7; Rectangle { width: 8; height: 8; radius: 4; color: controller.online ? "#10B981" : "#EF4444" } Label { text: controller.online ? "后端已连接" : "后端离线"; color: controller.online ? "#047857" : "#B91C1C"; font.pixelSize: 12 } } }
            Button { text: "载入演示"; onClicked: controller.loadDemo() }
            Button { text: "导入 JSON"; highlighted: true; onClicked: importDialog.open() }
            ToolButton { visible: window.compact; text: "记忆活动"; onClicked: activityDrawer.open() }
        }
    }

    Drawer {
        id: activityDrawer
        edge: Qt.RightEdge
        width: Math.min(430, window.width * 0.88)
        height: window.height
        ActivityPane { anchors.fill: parent; anchors.margins: 12 }
    }

    component ActivityPane: Rectangle {
        radius: 16; color: "white"; border.color: "#E2E8F0"
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 16; spacing: 12
            RowLayout { Layout.fillWidth: true; Label { text: "本轮记忆活动"; color: "#172033"; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true } Label { text: controller.lastLatencyMs + " ms"; color: "#64748B" } }
            TabBar { id: activityTabs; Layout.fillWidth: true; TabButton { text: "记忆 " + controller.memoryModel.count } TabButton { text: "写入" } TabButton { text: "事实 " + controller.factModel.count } }
            StackLayout {
                currentIndex: activityTabs.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
                ScrollView {
                    clip: true
                    ListView {
                        model: controller.memoryModel; spacing: 10
                        delegate: MemoryCard { width: ListView.view.width; memoryType: model.memoryType; knowledgeType: model.knowledgeType; title: model.title; summary: model.summary; relevance: model.relevance; source: model.source; scope: model.scope; tagsText: model.tagsText; used: model.used }
                        Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.currentExecuted ? "未找到相关记忆" : "执行本轮后显示检索结果"; color: "#94A3B8" }
                    }
                }
                ScrollView { TextArea { text: controller.writeSummary; readOnly: true; wrapMode: Text.Wrap; color: "#334155"; padding: 14; background: Rectangle { radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0" } } }
                ScrollView {
                    clip: true
                    ListView {
                        model: controller.factModel; spacing: 10
                        delegate: Rectangle {
                            width: ListView.view.width; height: factContent.implicitHeight + 24; radius: 12; color: "#FFFBEB"; border.color: "#FDE68A"
                            ColumnLayout {
                                id: factContent
                                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                                spacing: 7
                                Label { text: model.status === "proposed" ? "待确认" : model.status; color: "#B45309"; font.pixelSize: 11; font.bold: true }
                                Label { text: model.subject + " · " + model.predicate; Layout.fillWidth: true; wrapMode: Text.Wrap; font.bold: true; color: "#172033" }
                                Label { text: model.objectValue; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#475569" }
                                Button { text: "查看 Propose / Commit"; enabled: model.status === "proposed" || model.status === "awaiting_decision"; onClicked: { factDialog.proposal = controller.factAt(index); factDialog.open() } }
                            }
                        }
                        Label { anchors.centerIn: parent; visible: parent.count === 0; text: "本轮没有事实候选"; color: "#94A3B8" }
                    }
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 14
        Rectangle {
            Layout.preferredWidth: 220; Layout.fillHeight: true; radius: 16; color: "#111B2E"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                Label { text: "MEMORY CONSOLE"; color: "#64748B"; font.bold: true; font.pixelSize: 10; font.letterSpacing: 1.3 }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ColumnLayout {
                        width: parent.width
                        spacing: 3
                        Label { text: "工作台"; color: "#64748B"; font.pixelSize: 10; topPadding: 5; bottomPadding: 3 }
                        MenuButton { sectionId: "agent"; sectionText: "▣  Agent 对话" }
                        MenuButton { sectionId: "ingestion"; sectionText: "▤  数据接入记录" }
                        MenuButton { sectionId: "retrieval"; sectionText: "⌕  检索记录" }
                        Label { text: "记忆管理"; color: "#64748B"; font.pixelSize: 10; topPadding: 10; bottomPadding: 3 }
                        MenuButton { sectionId: "preferences"; sectionText: "☷  偏好记忆" }
                        MenuButton { sectionId: "facts"; sectionText: "◇  事实记忆" }
                        MenuButton { sectionId: "knowledge"; sectionText: "▧  知识记忆" }
                        MenuButton { sectionId: "conflicts"; sectionText: "⚠  冲突处理" }
                        MenuButton { sectionId: "forget"; sectionText: "⌫  遗忘管理" }
                        Label { text: "系统能力"; color: "#64748B"; font.pixelSize: 10; topPadding: 10; bottomPadding: 3 }
                        MenuButton { sectionId: "safety"; sectionText: "◇  安全规则" }
                        MenuButton { sectionId: "evaluation"; sectionText: "▥  评测报告" }
                        MenuButton { sectionId: "settings"; sectionText: "⚙  系统设置" }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: "#26344D" }
                Label { text: "会话进度"; color: "#CBD5E1"; font.bold: true; font.pixelSize: 13 }
                Rectangle { Layout.fillWidth: true; height: 64; radius: 12; color: "#18253D"; Column { anchors.centerIn: parent; spacing: 4; Label { text: "第 " + (controller.currentIndex + 1) + " / " + controller.totalTurns + " 轮"; color: "white"; font.bold: true } Label { text: controller.currentExecuted ? "本轮已执行" : "等待执行"; color: controller.currentExecuted ? "#6EE7B7" : "#94A3B8"; font.pixelSize: 11 } } }
                ListView {
                    visible: false
                    Layout.fillWidth: true; Layout.fillHeight: true; model: controller.turnModel; spacing: 6; clip: true
                    delegate: Rectangle {
                        width: ListView.view.width; height: 54; radius: 10; color: model.selected ? "#2563EB" : "transparent"
                        RowLayout { anchors.fill: parent; anchors.margins: 10; Rectangle { width: 24; height: 24; radius: 12; color: model.state === "done" ? "#10B981" : (model.selected ? "white" : "#334155"); Label { anchors.centerIn: parent; text: model.state === "done" ? "✓" : model.number; color: model.state === "done" ? "white" : (model.selected ? "#2563EB" : "#CBD5E1"); font.bold: true; font.pixelSize: 11 } } ColumnLayout { Layout.fillWidth: true; spacing: 1; Label { text: "第 " + model.number + " 轮"; color: model.selected ? "white" : "#E2E8F0"; font.bold: true; font.pixelSize: 12 } Label { text: model.preview; color: model.selected ? "#DBEAFE" : "#94A3B8"; elide: Text.ElideRight; Layout.fillWidth: true; font.pixelSize: 10 } } }
                        MouseArea { anchors.fill: parent; onClicked: controller.goToTurn(index) }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 82; radius: 12; color: "#18253D"; ColumnLayout { anchors.fill: parent; anchors.margins: 10; Label { text: controller.statusText; color: controller.online ? "#6EE7B7" : "#FCA5A5"; font.bold: true } RowLayout { Button { text: "重试"; onClicked: controller.retryBackend() } Button { text: "API 文档"; onClicked: controller.openApiDocs() } } } }
            }
        }

        Rectangle {
            Layout.preferredWidth: 245; Layout.fillHeight: true; radius: 16; color: "#FFFFFF"; border.color: "#E2E8F0"
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout { Layout.fillWidth: true; spacing: 2; Label { text: "对话记录"; color: "#172033"; font.pixelSize: 16; font.bold: true } Label { text: "当前测试会话"; color: "#94A3B8"; font.pixelSize: 11 } }
                    ToolButton { text: "⋯"; onClicked: controller.loadDemo() }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
                Rectangle { Layout.fillWidth: true; height: 72; radius: 12; color: "#EFF6FF"; border.color: "#BFDBFE"; ColumnLayout { anchors.fill: parent; anchors.margins: 12; spacing: 4; Label { text: controller.title; color: "#1D4ED8"; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true } Label { text: controller.totalTurns + " 轮对话  ·  " + (controller.online ? "在线" : "离线"); color: "#64748B"; font.pixelSize: 11 } } }
                Label { text: "对话轮次"; color: "#64748B"; font.pixelSize: 11; font.bold: true }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; model: controller.turnModel; spacing: 6; clip: true
                    delegate: Rectangle {
                        width: ListView.view.width; height: 58; radius: 10; color: model.selected ? "#2563EB" : "#F8FAFC"; border.color: model.selected ? "#2563EB" : "#E2E8F0"
                        RowLayout { anchors.fill: parent; anchors.margins: 10; Rectangle { Layout.preferredWidth: 25; Layout.preferredHeight: 25; radius: 13; color: model.state === "done" ? "#10B981" : (model.selected ? "white" : "#E2E8F0"); Label { anchors.centerIn: parent; text: model.state === "done" ? "✓" : model.number; color: model.state === "done" ? "white" : (model.selected ? "#2563EB" : "#64748B"); font.bold: true; font.pixelSize: 11 } } ColumnLayout { Layout.fillWidth: true; spacing: 2; Label { text: "第 " + model.number + " 轮"; color: model.selected ? "white" : "#172033"; font.bold: true; font.pixelSize: 12 } Label { text: model.preview; color: model.selected ? "#DBEAFE" : "#64748B"; elide: Text.ElideRight; Layout.fillWidth: true; font.pixelSize: 10 } } }
                        MouseArea { anchors.fill: parent; onClicked: controller.goToTurn(index) }
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 52; radius: 10; color: "#F8FAFC"; RowLayout { anchors.fill: parent; anchors.margins: 10; Rectangle { width: 8; height: 8; radius: 4; color: controller.online ? "#10B981" : "#EF4444" } Label { text: controller.online ? "服务已连接" : "服务离线"; color: "#64748B"; font.pixelSize: 11; Layout.fillWidth: true } Button { text: "重试"; onClicked: controller.retryBackend() } } }
            }
        }

        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true; radius: 16; color: "white"; border.color: "#E2E8F0"
            ColumnLayout {
                anchors.fill: parent; spacing: 0
                Rectangle { Layout.fillWidth: true; height: 62; color: "transparent"; RowLayout { anchors.fill: parent; anchors.leftMargin: 18; anchors.rightMargin: 18; Label { text: "Agent 对话"; color: "#172033"; font.pixelSize: 17; font.bold: true; Layout.fillWidth: true } Label { text: "逐轮真实执行"; color: "#2563EB"; font.bold: true } } }
                Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
                ScrollView {
                    id: chatScroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    ListView {
                        id: chatList; model: controller.messageModel; spacing: 16; topMargin: 18; bottomMargin: 18; leftMargin: 18; rightMargin: 18
                        delegate: Item {
                            width: ListView.view.width - 36; height: bubble.height
                            Rectangle {
                                id: bubble; width: Math.min(parent.width * 0.78, messageText.implicitWidth + 30); height: messageText.implicitHeight + 28; radius: 14; color: model.speaker === "user" ? "#2563EB" : (model.pending ? "#F8FAFC" : "#F1F5F9"); border.color: model.pending ? "#CBD5E1" : "transparent"; anchors.right: model.speaker === "user" ? parent.right : undefined; anchors.left: model.speaker === "user" ? undefined : parent.left
                                Label { id: messageText; anchors.fill: parent; anchors.margins: 14; text: model.body; color: model.speaker === "user" ? "white" : (model.pending ? "#94A3B8" : "#263247"); wrapMode: Text.Wrap; font.italic: model.pending }
                            }
                        }
                        onCountChanged: positionViewAtEnd()
                    }
                }
                Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
                ColumnLayout {
                    Layout.fillWidth: true; Layout.preferredHeight: Math.min(290, Math.max(145, toolList.contentHeight + 92)); Layout.margins: 14; spacing: 8
                    RowLayout { Layout.fillWidth: true; Label { text: "工具轨迹"; color: "#334155"; font.bold: true; Layout.fillWidth: true } Label { text: controller.toolModel.count + " 次调用"; color: "#94A3B8" } }
                    ListView { id: toolList; Layout.fillWidth: true; Layout.fillHeight: true; model: controller.toolModel; spacing: 8; clip: true; delegate: ToolCard { width: ListView.view.width; toolName: model.toolName; status: model.status; sequence: model.sequence; latencyMs: model.latencyMs; argumentsJson: model.argumentsJson; resultJson: model.resultJson; error: model.error } Label { anchors.centerIn: parent; visible: parent.count === 0; text: "执行本轮后显示工具调用"; color: "#94A3B8" } }
                    RowLayout { Layout.fillWidth: true; Button { text: "上一轮"; enabled: controller.canGoPrevious; onClicked: controller.previousTurn() } Item { Layout.fillWidth: true } BusyIndicator { running: controller.busy; visible: running; implicitWidth: 28; implicitHeight: 28 } Button { text: controller.currentExecuted ? "重新执行（幂等）" : "执行本轮"; highlighted: true; enabled: !controller.busy && controller.online; onClicked: controller.executeCurrent() } Button { text: "下一轮"; enabled: controller.canGoNext; onClicked: controller.nextTurn() } }
                }
            }
        }
        ActivityPane { visible: !window.compact; Layout.preferredWidth: 380; Layout.fillHeight: true }
    }

    Rectangle {
        visible: controller.notice.length > 0
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 24 }
        width: Math.min(noticeText.implicitWidth + 34, window.width - 60); height: noticeText.implicitHeight + 22; radius: 12; color: "#172033"; z: 20
        Label { id: noticeText; anchors.centerIn: parent; width: parent.width - 26; text: controller.notice; color: "white"; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
    }
}
