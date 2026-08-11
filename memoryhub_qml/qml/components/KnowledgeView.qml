import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 知识管理页 — 知识记忆卡片列表（步骤/工具直接集成在卡片内） */
Rectangle {
    id: root
    color: "transparent"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- 顶部工具条 ----
        Rectangle {
            Layout.fillWidth: true; height: 62; color: "transparent"
            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 18; anchors.rightMargin: 18; spacing: 12
                ColumnLayout { Layout.fillWidth: true; spacing: 2
                    Label { text: "知识记忆"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "可复用的工作流、案例与模板"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.knowledgeModel.count + " 条"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "刷新"; onClicked: controller.loadKnowledge() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }

        // ---- 知识卡片列表 ----
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                id: listView
                anchors.fill: parent; anchors.margins: 14
                model: controller.knowledgeModel
                spacing: 10
                delegate: Rectangle {
                    id: card
                    width: ListView.view.width
                    height: contentCol.implicitHeight + 28
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        id: contentCol
                        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 14; rightMargin: 14; topMargin: 14 }
                        spacing: 8

                        // 顶行：类型徽标 + 名称 + 置信度
                        RowLayout { Layout.fillWidth: true; spacing: 8
                            Rectangle { Layout.preferredWidth: typeTxt.implicitWidth + 16; Layout.preferredHeight: 22; radius: 4; color: typeBg(model.knowledgeType)
                                Label { id: typeTxt; anchors.centerIn: parent; text: typeZh(model.knowledgeType); color: "#1D4ED8"; font.pixelSize: 11; font.bold: true } }
                            Label { text: model.name; Layout.fillWidth: true; elide: Text.ElideRight; color: "#172033"; font.bold: true; font.pixelSize: 13 }
                            Label { text: "置信度 " + confLabel(model.confidence); color: model.confidence >= 0.8 ? "#047857" : (model.confidence >= 0.5 ? "#B45309" : "#94A3B8"); font.pixelSize: 11; font.bold: true }
                        }

                        // 内容摘要
                        Label { Layout.fillWidth: true; text: model.content; color: "#475569"; wrapMode: Text.Wrap; font.pixelSize: 12 }

                        // 元信息
                        Label { Layout.fillWidth: true; text: "成功率 " + model.successRate + (model.level ? "   ·   层级 " + levelZh(model.level) : "") + "   ·   更新 " + model.createdAt + (model.scopeText ? "   ·   作用域 " + model.scopeText : ""); color: "#64748B"; font.pixelSize: 11; elide: Text.ElideRight }

                        // 执行步骤
                        ColumnLayout { Layout.fillWidth: true; spacing: 4
                            Label { text: "执行步骤"; color: "#111827"; font.bold: true; font.pixelSize: 11 }
                            Label { visible: model.stepsText.length > 0; Layout.fillWidth: true; text: model.stepsText; color: "#374151"; wrapMode: Text.Wrap; font.pixelSize: 11; lineHeight: 1.4 }
                            Label { visible: model.stepsText.length === 0; text: "执行步骤：无"; color: "#94A3B8"; font.pixelSize: 11 }
                        }

                        // 调用工具
                        ColumnLayout { Layout.fillWidth: true; spacing: 4
                            Label { text: "调用工具"; color: "#111827"; font.bold: true; font.pixelSize: 11 }
                            Label { visible: model.toolsText.length > 0; Layout.fillWidth: true; text: model.toolsText; color: "#2563EB"; wrapMode: Text.Wrap; font.pixelSize: 11 }
                            Label { visible: model.toolsText.length === 0; text: "调用工具：无"; color: "#94A3B8"; font.pixelSize: 11 }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.knowledgeLoading ? "正在加载知识记忆…" : "暂无知识记忆"; color: "#94A3B8" }
            }
        }
    }

    function typeZh(t) {
        const map = { workflow:"工作流", case:"历史案例", template:"模板" }
        return map[t] || t
    }
    function typeBg(t) {
        return t === "template" ? "#FFF7ED" : (t === "case" ? "#F0FDF4" : "#EFF6FF")
    }
    function levelZh(l) {
        const map = { short:"短期", mid:"中期", long:"长期" }
        return map[l] || l
    }
    function confLabel(v) {
        if (v >= 0.8) return "高"
        if (v >= 0.5) return "中"
        return "低"
    }
}