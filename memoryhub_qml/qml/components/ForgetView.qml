import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 遗忘管理页 — 遗忘指令 + 遗忘历史 */
Rectangle {
    id: root
    color: "transparent"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true; height: 62; color: "transparent"
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 18; anchors.rightMargin: 18; spacing: 12
                ColumnLayout { Layout.fillWidth: true; spacing: 2
                    Label { text: "遗忘管理"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "精准遗忘指令与审计历史"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Button { text: "刷新"; onClicked: controller.loadForgetHistory() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        // 遗忘指令输入
        Rectangle {
            Layout.fillWidth: true; Layout.margins: 14; height: 56; radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
            RowLayout {
                anchors.fill: parent; anchors.margins: 10; spacing: 10
                TextField { id: forgetInput; Layout.fillWidth: true; placeholderText: "输入遗忘指令，如：忘了上周的测试偏好"; onAccepted: doForget() }
                Button { text: "遗忘"; highlighted: true; onClicked: doForget() }
            }
        }
        // 遗忘历史
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.forgetModel
                spacing: 10
                delegate: Rectangle {
                    width: ListView.view.width
                    height: Math.max(70, headRow.height + 20)
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 6
                        RowLayout { id: headRow; Layout.fillWidth: true; spacing: 8
                            Label { text: model.instruction; Layout.fillWidth: true; color: "#172033"; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: 12 }
                            Label { text: "删除 " + model.deletedCount + " 条"; color: model.deletedCount > 0 ? "#047857" : "#94A3B8"; font.pixelSize: 11; font.bold: true }
                            Label { text: model.createdAt; color: "#94A3B8"; font.pixelSize: 10 }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: "暂无遗忘历史"; color: "#94A3B8" }
            }
        }
    }
    function doForget() { if (forgetInput.text.trim()) controller.applyForget(forgetInput.text.trim()) }
}