import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 知识管理页 — 知识记忆列表 + 步骤链 + 工具链展示 */
Rectangle {
    id: root
    color: "transparent"

    property string _filterType: ""

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
                TextField {
                    id: searchInput
                    placeholderText: "搜索名称或内容…"
                    implicitWidth: 240
                    onTextChanged: controller.filterKnowledge(typeCombo.currentIndex, text)
                }
                ComboBox {
                    id: typeCombo
                    implicitWidth: 140
                    model: ["全部分类", "工作流", "历史案例", "模板"]
                    onActivated: controller.filterKnowledge(currentIndex, searchInput.text)
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
                highlightFollowsCurrentItem: false
                delegate: Rectangle {
                    id: card
                    width: ListView.view.width
                    height: Math.max(120, headRow.height + summaryLabel.height + metaRow.height + 30)
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { listView.currentIndex = index; detailContent.steps = model.steps; detailContent.tools = model.tools }
                        hoverEnabled: true
                        onEntered: card.border.color = "#93C5FD"
                        onExited: card.border.color = "#E2E8F0"
                    }
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 8
                        RowLayout { id: headRow; Layout.fillWidth: true; spacing: 8
                            Rectangle { Layout.preferredWidth: typeTxt.implicitWidth + 16; Layout.preferredHeight: 22; radius: 4; color: typeBg(model.knowledgeType)
                                Label { id: typeTxt; anchors.centerIn: parent; text: typeZh(model.knowledgeType); color: "#1D4ED8"; font.pixelSize: 11; font.bold: true } }
                            Label { text: model.name; Layout.fillWidth: true; elide: Text.ElideRight; color: "#172033"; font.bold: true; font.pixelSize: 13 }
                            Label { text: "置信度 " + confLabel(model.confidence); color: model.confidence >= 0.8 ? "#047857" : (model.confidence >= 0.5 ? "#B45309" : "#94A3B8"); font.pixelSize: 11; font.bold: true }
                        }
                        Label { id: summaryLabel; Layout.fillWidth: true; text: model.content; color: "#475569"; wrapMode: Text.Wrap; elide: Text.ElideRight; maximumLineCount: 2; font.pixelSize: 12 }
                        Label { id: metaRow; Layout.fillWidth: true; text: "成功率 " + model.successRate + "   ·   " + (model.level ? "层级 " + levelZh(model.level) + "   ·   " : "") + "更新 " + model.createdAt + (model.toolsText ? "   ·   工具 " + model.toolsText : ""); color: "#64748B"; font.pixelSize: 11; elide: Text.ElideRight }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.knowledgeLoading ? "正在加载知识记忆…" : "暂无知识记忆"; color: "#94A3B8" }
            }
        }

        // ---- 详情面板：执行步骤 + 调用工具 ----
        Rectangle {
            id: detailPanel
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            color: "#FFFFFF"; border.color: "#E2E8F0"; radius: 12
            visible: detailContent.steps.length > 0 || detailContent.tools.length > 0
            Item { id: detailContent; property var steps: []; property var tools: [] }
            RowLayout {
                anchors.fill: parent; anchors.margins: 16; spacing: 24
                ColumnLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
                    Label { text: "执行步骤"; color: "#111827"; font.bold: true; font.pixelSize: 13 }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        ListView {
                            model: detailContent.steps
                            spacing: 6
                            delegate: RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                Rectangle { width: 20; height: 20; radius: 10; color: "#EFF6FF"; Label { anchors.centerIn: parent; text: index + 1; color: "#2563EB"; font.pixelSize: 10; font.bold: true } }
                                Label { text: modelData; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#374151"; font.pixelSize: 12 }
                            }
                        }
                    }
                }
                Rectangle { Layout.fillHeight: true; width: 1; color: "#F3F4F6" }
                ColumnLayout { Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
                    Label { text: "调用工具"; color: "#111827"; font.bold: true; font.pixelSize: 13 }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        ListView {
                            model: detailContent.tools
                            spacing: 6
                            delegate: RowLayout {
                                Layout.fillWidth: true; spacing: 8
                                Rectangle { width: 6; height: 6; radius: 3; color: "#2563EB" }
                                Label { text: modelData; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#374151"; font.pixelSize: 12 }
                            }
                        }
                    }
                }
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