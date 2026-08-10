import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 检索记录页 — 混合检索偏好/知识/事实 */
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
                    Label { text: "检索记录"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "混合检索偏好 / 知识 / 事实记忆"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                TextField {
                    id: queryInput
                    placeholderText: "输入查询…"
                    implicitWidth: 280
                    onAccepted: search()
                }
                Button { text: "检索"; highlighted: true; onClicked: search() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.retrievalModel
                spacing: 10
                delegate: Rectangle {
                    width: ListView.view.width
                    height: Math.max(84, typeRow.height + contentLabel.height + 18)
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 6
                        RowLayout { id: typeRow; Layout.fillWidth: true; spacing: 8
                            Rectangle { Layout.preferredWidth: typeTxt.implicitWidth + 12; Layout.preferredHeight: 18; radius: 4; color: typeRowColor(model.memoryType)
                                Label { id: typeTxt; anchors.centerIn: parent; text: typeZh(model.memoryType); color: "#1D4ED8"; font.pixelSize: 10; font.bold: true } }
                            Label { text: model.memoryId; color: "#94A3B8"; font.pixelSize: 10; elide: Text.ElideMiddle; Layout.maximumWidth: 220 }
                            Item { Layout.fillWidth: true }
                            Label { text: "得分 " + model.score.toFixed(3); color: "#047857"; font.pixelSize: 11; font.bold: true }
                        }
                        Label { id: contentLabel; Layout.fillWidth: true; text: model.content; color: "#172033"; wrapMode: Text.Wrap; elide: Text.ElideRight; maximumLineCount: 3; font.pixelSize: 12 }
                        Label { text: "来源 " + model.source; color: "#94A3B8"; font.pixelSize: 10 }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: "输入查询点击「检索」查看结果"; color: "#94A3B8" }
            }
        }
    }
    function search() { controller.searchMemory(queryInput.text) }
    function typeZh(t) { const m = { preference:"偏好", knowledge:"知识", fact:"事实" }; return m[t] || t }
    function typeRowColor(t) { return t === "preference" ? "#EFF6FF" : (t === "fact" ? "#FEF2F2" : "#ECFDF5") }
}