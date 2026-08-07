import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property string toolName
    required property string status
    required property int sequence
    required property int latencyMs
    required property string argumentsJson
    required property string resultJson
    required property string error
    property bool expanded: false
    implicitHeight: content.implicitHeight + 24
    radius: 12
    color: "#F8FAFC"
    border.color: "#E2E8F0"

    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Rectangle { width: 24; height: 24; radius: 7; color: "#E8F0FF"; Text { anchors.centerIn: parent; text: root.sequence; color: "#2563EB"; font.bold: true } }
            Label { text: root.toolName; color: "#172033"; font.bold: true; Layout.fillWidth: true }
            Label { text: root.latencyMs + " ms"; color: "#64748B"; font.pixelSize: 12 }
            Rectangle { width: 62; height: 24; radius: 12; color: root.status === "success" ? "#DCFCE7" : "#FEE2E2"; Label { anchors.centerIn: parent; text: root.status === "success" ? "成功" : "失败"; color: root.status === "success" ? "#15803D" : "#B91C1C"; font.pixelSize: 12 } }
            ToolButton { text: root.expanded ? "收起" : "详情"; onClicked: root.expanded = !root.expanded }
        }
        ColumnLayout {
            visible: root.expanded
            Layout.fillWidth: true
            Label { text: "参数"; font.bold: true; color: "#475569" }
            TextArea { Layout.fillWidth: true; text: root.argumentsJson; readOnly: true; wrapMode: Text.WrapAnywhere; color: "#334155"; background: Rectangle { radius: 8; color: "white"; border.color: "#E2E8F0" } }
            Label { text: root.error ? "错误" : "脱敏结果"; font.bold: true; color: "#475569" }
            TextArea { Layout.fillWidth: true; text: root.error || root.resultJson; readOnly: true; wrapMode: Text.WrapAnywhere; color: root.error ? "#B91C1C" : "#334155"; background: Rectangle { radius: 8; color: "white"; border.color: "#E2E8F0" } }
        }
    }
}
