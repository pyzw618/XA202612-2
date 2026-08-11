import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 事实记忆页 — 事实三元组列表 */
Rectangle {
    id: root
    color: "transparent"
    property var factDialog: null

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true; height: 62; color: "transparent"
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 18; anchors.rightMargin: 18; spacing: 12
                ColumnLayout { Layout.fillWidth: true; spacing: 2
                    Label { text: "事实记忆"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "从对话中沉淀的稳定事实关系"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.factsModel.count + " 条"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "刷新"; onClicked: controller.loadFacts() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.factsModel
                spacing: 10
                delegate: Rectangle {
                    width: ListView.view.width
                    height: Math.max(96, tripleRow.height + srcLabel.height + 26)
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 8
                        RowLayout { id: tripleRow; Layout.fillWidth: true; spacing: 8
                            Label { text: model.subject; color: "#1D4ED8"; font.bold: true; font.pixelSize: 13 }
                            Label { text: model.predicate; color: "#64748B"; font.pixelSize: 12 }
                            Label { text: model.objectValue; Layout.fillWidth: true; color: "#172033"; font.bold: true; font.pixelSize: 13; elide: Text.ElideRight }
                            Rectangle { Layout.preferredWidth: statusTxt.implicitWidth + 14; Layout.preferredHeight: 20; radius: 4; color: model.status === "pending" ? "#FFFBEB" : "#EFF6FF"
                                Label { id: statusTxt; anchors.centerIn: parent; text: model.status === "pending" ? "待确认" : "已提交"; color: model.status === "pending" ? "#B45309" : "#1D4ED8"; font.pixelSize: 10; font.bold: true } }
                            Rectangle { Layout.preferredWidth: confTxt.implicitWidth + 14; Layout.preferredHeight: 20; radius: 4; color: "#EFF6FF"
                                Label { id: confTxt; anchors.centerIn: parent; text: "置信度 " + confLabel(model.confidence); color: "#1D4ED8"; font.pixelSize: 10; font.bold: true } }
                        }
                        Label { id: srcLabel; Layout.fillWidth: true; text: "来源：" + (model.sourceText || "—") + "   ·   作用域 " + model.scope + "   ·   " + model.createdAt; color: "#64748B"; font.pixelSize: 11; elide: Text.ElideRight }
                        RowLayout { Layout.fillWidth: true
                            Item { Layout.fillWidth: true }
                            Button { text: "提交 / 忽略"; visible: model.status === "pending"; onClicked: { if (root.factDialog) { root.factDialog.proposal = controller.factPageAt(index); root.factDialog.open() } } }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.pageLoading ? "正在加载事实记忆…" : "暂无事实记忆"; color: "#94A3B8" }
            }
        }
    }
    function confLabel(v) {
        if (v >= 0.8) return "高"
        if (v >= 0.5) return "中"
        return "低"
    }
}