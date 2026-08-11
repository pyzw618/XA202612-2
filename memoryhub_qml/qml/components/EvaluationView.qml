import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 评测报告页 — 各任务评测指标 */
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
                    Label { text: "评测报告"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "偏好抽取 / 检索 / 冲突 评测指标"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.evaluationModel.count + " 份"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "刷新"; onClicked: controller.loadEvalReports() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.evaluationModel
                spacing: 10
                delegate: Rectangle {
                    width: ListView.view.width
                    height: 96
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 8
                        RowLayout { Layout.fillWidth: true; spacing: 8
                            Label { text: taskZh(model.taskName); color: "#172033"; font.bold: true; font.pixelSize: 13 }
                            Label { text: model.taskName; color: "#94A3B8"; font.pixelSize: 10 }
                            Item { Layout.fillWidth: true }
                            Label { text: "样本 " + model.totalSamples; color: "#64748B"; font.pixelSize: 11 }
                        }
                        RowLayout { Layout.fillWidth: true; spacing: 16
                            Metric { text: "准确率"; value: model.accuracy }
                            Metric { text: "F1"; value: model.f1 }
                            Metric { text: "平均耗时"; value: model.avgLatencyMs + "ms" }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.pageLoading ? "正在加载评测报告…" : "暂无评测报告"; color: "#94A3B8" }
            }
        }
    }
    component Metric: ColumnLayout {
        required property string text
        required property var value
        spacing: 2
        Label { text: parent.text; color: "#94A3B8"; font.pixelSize: 10 }
        Label { text: String(parent.value); color: "#047857"; font.pixelSize: 13; font.bold: true }
    }
    function taskZh(t) { const m = { preference_extraction:"偏好抽取", retrieval:"检索", conflict:"冲突处理" }; return m[t] || t }
}