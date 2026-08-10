import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 安全规则页 — 用户自定义安全匹配规则 */
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
                    Label { text: "安全规则"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "用户自定义敏感匹配规则"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.safetyModel.count + " 条"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "刷新"; onClicked: controller.loadSafetyRules() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.safetyModel
                spacing: 10
                delegate: Rectangle {
                    width: ListView.view.width
                    height: 84
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 8
                        RowLayout { Layout.fillWidth: true; spacing: 8
                            Label { text: model.label; Layout.fillWidth: true; color: "#172033"; font.bold: true; font.pixelSize: 13; elide: Text.ElideRight }
                            Rectangle { Layout.preferredWidth: effTxt.implicitWidth + 12; Layout.preferredHeight: 20; radius: 4; color: model.effect === "mask_match" ? "#FEF3C7" : "#FEE2E2"
                                Label { id: effTxt; anchors.centerIn: parent; text: effectZh(model.effect); color: model.effect === "mask_match" ? "#B45309" : "#B91C1C"; font.pixelSize: 10; font.bold: true } }
                            Rectangle { Layout.preferredWidth: 44; Layout.preferredHeight: 20; radius: 4; color: model.enabled ? "#ECFDF5" : "#F1F5F9"
                                Label { anchors.centerIn: parent; text: model.enabled ? "启用" : "停用"; color: model.enabled ? "#047857" : "#64748B"; font.pixelSize: 10; font.bold: true } }
                        }
                        Label { text: "类型 " + kindZh(model.kind) + "   ·   修订 v" + model.revision + "   ·   " + model.ruleId; color: "#94A3B8"; font.pixelSize: 11; elide: Text.ElideRight }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.pageLoading ? "正在加载安全规则…" : "暂无安全规则"; color: "#94A3B8" }
            }
        }
    }
    function kindZh(k) { const m = { literal:"关键词", advanced_regex:"正则" }; return m[k] || k }
    function effectZh(e) { const m = { mask_match:"打码", drop_event:"丢弃" }; return m[e] || e }
}