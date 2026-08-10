import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 冲突处理页 — 新旧记忆冲突记录 + 人工裁决 */
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
                    Label { text: "冲突处理"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "新旧记忆冲突及处理结果"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.conflictsModel.count + " 条"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "刷新"; onClicked: controller.loadConflicts() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.conflictsModel
                spacing: 10
                delegate: Rectangle {
                    width: ListView.view.width
                    height: Math.max(110, headRow.height + oldLabel.height + newLabel.height + 26)
                    radius: 12; color: "#FFFBEB"; border.color: "#FDE68A"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 6
                        RowLayout { id: headRow; Layout.fillWidth: true; spacing: 8
                            Label { text: "类型 " + typeZh(model.memoryType); color: "#B45309"; font.pixelSize: 11; font.bold: true }
                            Label { text: "状态 " + decisionZh(model.decision); color: model.decision === "pending" ? "#EF4444" : "#047857"; font.pixelSize: 11; font.bold: true }
                            Item { Layout.fillWidth: true }
                            Label { text: model.createdAt; color: "#94A3B8"; font.pixelSize: 10 }
                        }
                        Label { id: oldLabel; Layout.fillWidth: true; text: "旧：" + model.oldContent; color: "#92400E"; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: 12 }
                        Label { id: newLabel; Layout.fillWidth: true; text: "新：" + model.newContent; color: "#78350F"; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: 12 }
                        RowLayout {
                            Layout.fillWidth: true; Layout.topMargin: 4
                            Button { text: "采纳新记忆"; enabled: model.decision === "pending"; onClicked: controller.resolveConflict(model.conflictId, "override", "采纳新记忆") }
                            Button { text: "合并"; enabled: model.decision === "pending"; onClicked: controller.resolveConflict(model.conflictId, "merge", "合并新旧") }
                            Button { text: "按场景并存"; enabled: model.decision === "pending"; onClicked: controller.resolveConflict(model.conflictId, "coexist", "按场景并存") }
                            Label { text: model.reason; Layout.fillWidth: true; visible: model.decision !== "pending"; color: "#64748B"; elide: Text.ElideRight; font.pixelSize: 11 }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.pageLoading ? "正在加载冲突记录…" : "暂无冲突记录"; color: "#94A3B8" }
            }
        }
    }
    function typeZh(t) { const m = { preference:"偏好", knowledge:"知识", fact:"事实" }; return m[t] || t }
    function decisionZh(d) { const m = { pending:"待处理", override:"采纳新记忆", merge:"合并", coexist:"按场景并存", resolved:"已解决" }; return m[d] || d }
}