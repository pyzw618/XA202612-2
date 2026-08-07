import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property string memoryType
    required property string knowledgeType
    required property string title
    required property string summary
    required property real relevance
    required property string source
    required property string scope
    required property string tagsText
    required property bool used
    implicitHeight: card.implicitHeight + 24
    radius: 12
    color: root.used ? "#EFF6FF" : "#FFFFFF"
    border.color: root.used ? "#93C5FD" : "#E2E8F0"

    ColumnLayout {
        id: card
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 7
        RowLayout {
            Layout.fillWidth: true
            Rectangle { width: 62; height: 23; radius: 11; color: root.used ? "#DBEAFE" : "#F1F5F9"; Label { anchors.centerIn: parent; text: root.used ? "实际引用" : "候选"; color: root.used ? "#1D4ED8" : "#64748B"; font.pixelSize: 11; font.bold: true } }
            Label { text: root.memoryType === "preference" ? "偏好" : (root.knowledgeType || "知识"); color: "#64748B"; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            Label { text: Math.round(root.relevance * 100) + "%"; color: "#2563EB"; font.bold: true }
        }
        Label { Layout.fillWidth: true; text: root.title; color: "#172033"; font.bold: true; wrapMode: Text.Wrap }
        Label { Layout.fillWidth: true; text: root.summary; color: "#475569"; wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight }
        Label { Layout.fillWidth: true; text: root.source + "  ·  " + root.scope + (root.tagsText ? "  ·  " + root.tagsText : ""); color: "#94A3B8"; font.pixelSize: 11; elide: Text.ElideRight }
    }
}
