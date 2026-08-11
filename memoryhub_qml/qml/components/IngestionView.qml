import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 数据接入记录页 — 事件摄入/抽取任务列表 */
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
                    Label { text: "数据接入记录"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "事件摄入与记忆抽取任务"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.extractionsModel.count + " 条"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "刷新"; onClicked: controller.loadExtractions() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.extractionsModel
                spacing: 8
                delegate: Rectangle {
                    width: ListView.view.width
                    height: Math.max(64, headRow.height + metaRow.height + 20)
                    radius: 10; color: "#FFFFFF"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 12; spacing: 6
                        RowLayout { id: headRow; Layout.fillWidth: true; spacing: 8
                            Rectangle { Layout.preferredWidth: typeTxt.implicitWidth + 12; Layout.preferredHeight: 18; radius: 4; color: "#EFF6FF"
                                Label { id: typeTxt; anchors.centerIn: parent; text: typeZh(model.extractorType); color: "#1D4ED8"; font.pixelSize: 10; font.bold: true } }
                            Label { text: model.taskId; Layout.fillWidth: true; color: "#172033"; font.pixelSize: 12; font.bold: true; elide: Text.ElideMiddle }
                            Rectangle { Layout.preferredWidth: statusTxt.implicitWidth + 12; Layout.preferredHeight: 18; radius: 4; color: statusColor(model.status)
                                Label { id: statusTxt; anchors.centerIn: parent; text: statusZh(model.status); color: "#047857"; font.pixelSize: 10; font.bold: true } }
                        }
                        Label { id: metaRow; Layout.fillWidth: true; text: "事件 " + model.eventId + "   ·   尝试 " + model.attemptCount + " 次   ·   " + model.createdAt + (model.lastErrorCode ? "   ·   错误 " + model.lastErrorCode : ""); color: "#94A3B8"; font.pixelSize: 11; elide: Text.ElideRight }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.pageLoading ? "正在加载接入记录…" : "暂无抽取任务记录"; color: "#94A3B8" }
            }
        }
    }
    function typeZh(t) { const m = { preference_pref:"偏好", preference:"偏好", knowledge:"知识", fact:"事实", conflict:"冲突" }; return m[t] || t }
    function statusZh(s) { const m = { pending:"待处理", running:"执行中", succeeded:"成功", dead_letter:"失败", retry:"重试" }; return m[s] || s }
    function statusColor(s) { return s === "succeeded" ? "#ECFDF5" : (s === "dead_letter" ? "#FEF2F2" : "#EFF6FF") }
}