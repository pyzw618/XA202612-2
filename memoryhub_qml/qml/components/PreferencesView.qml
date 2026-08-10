import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 偏好记忆管理页 — 展示后端真实偏好记忆列表 */
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
                    Label { text: "偏好记忆"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "系统形成的用户偏好及适用范围"; color: "#94A3B8"; font.pixelSize: 11 }
                }
                Label { text: "共 " + controller.preferenceModel.count + " 条"; color: "#64748B"; font.pixelSize: 11 }
                Button { text: "清空"; onClicked: { confirmDialog.open() } }
                Button { text: "刷新"; onClicked: controller.loadPreferences() }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }

        // ---- 偏好卡片列表 ----
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ListView {
                anchors.fill: parent; anchors.margins: 14
                model: controller.preferenceModel
                spacing: 10
                delegate: Rectangle {
                    id: card
                    width: ListView.view.width
                    height: Math.max(128, topRow.height + summaryLabel.height + metaRow.height + evidenceRow.height + 34)
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"

                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 14; spacing: 8

                        // 顶行：类型徽标 + 状态 + 置信度 + 层级
                        RowLayout { id: topRow; Layout.fillWidth: true; spacing: 8
                            Rectangle { Layout.preferredWidth: typeText.implicitWidth + 16; Layout.preferredHeight: 22; radius: 4; color: "#EFF6FF"
                                Label { id: typeText; anchors.centerIn: parent; text: prefTypeZh(model.preferenceType); color: "#1D4ED8"; font.pixelSize: 11; font.bold: true } }
                            Rectangle { Layout.preferredWidth: statusText.implicitWidth + 14; Layout.preferredHeight: 20; radius: 4; color: model.status === "active" ? "#ECFDF5" : "#FEF2F2"
                                Label { id: statusText; anchors.centerIn: parent; text: model.status; color: model.status === "active" ? "#047857" : "#B91C1C"; font.pixelSize: 10 } }
                            Item { Layout.fillWidth: true }
                            Label { text: "置信度 " + confidenceLabel(model.confidence); color: model.confidence >= 0.8 ? "#047857" : (model.confidence >= 0.5 ? "#B45309" : "#94A3B8"); font.pixelSize: 11; font.bold: true }
                            Label { text: "v" + model.version; color: "#94A3B8"; font.pixelSize: 10 }
                        }

                        // 内容摘要（1-3 行）
                        Label { id: summaryLabel; Layout.fillWidth: true; text: model.content; color: "#172033"; wrapMode: Text.Wrap; elide: Text.ElideRight; maximumLineCount: 3; font.pixelSize: 13 }

                        // 元信息：作用域 / 层级 / 更新时间 / 标签
                        Label { id: metaRow; Layout.fillWidth: true; text: (model.scopeText ? "作用域 " + model.scopeText + "   ·   " : "") + (model.level ? "层级 " + levelZh(model.level) + "   ·   " : "") + "更新 " + model.updatedAt + (model.tagsText ? "   ·   " + model.tagsText : ""); color: "#64748B"; font.pixelSize: 11; elide: Text.ElideRight }

                        // 证据 + 操作
                        RowLayout { id: evidenceRow; Layout.fillWidth: true; spacing: 8
                            Label { text: "证据 " + model.evidenceCount + " 条"; color: "#94A3B8"; font.pixelSize: 11 }
                            Item { Layout.fillWidth: true }
                            Button { text: "查看证据"; visible: model.evidenceCount > 0; onClicked: evidenceDialog.show(model.evidenceJson) }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: controller.preferenceLoading ? "正在加载偏好记忆…" : "暂无偏好记忆"; color: "#94A3B8" }
            }
        }
    }

    // ---- 清空确认弹窗 ----
    Dialog {
        id: confirmDialog
        title: "清空偏好记忆"
        modal: true
        standardButtons: Dialog.Cancel | Dialog.Ok
        width: 380
        anchors.centerIn: parent
        onAccepted: controller.clearPreferences()
        Label { text: "将删除当前用户（含演示产生的重复/测试数据）的全部偏好记忆，此操作不可撤销。确定继续？"; wrapMode: Text.Wrap; color: "#334155" }
    }

    // ---- 证据详情弹窗 ----
    Dialog {
        id: evidenceDialog
        title: "证据链"
        modal: true
        standardButtons: Dialog.Close
        width: 520; height: 380
        function show(evidenceJson) {
            evidenceText.text = evidenceJson
            open()
        }
        ScrollView { anchors.fill: parent
            TextArea { id: evidenceText; readOnly: true; wrapMode: Text.NoWrap; font.family: "Consolas"; font.pixelSize: 11; color: "#334155"; background: Rectangle { color: "transparent" } }
        }
    }

    // ---- 工具函数 ----
    function prefTypeZh(t) {
        const map = { output_style:"输出风格", tool_preference:"工具选择", workflow_preference:"操作流程", safety_preference:"安全策略", scene_preference:"场景偏好", format_preference:"格式偏好", language_preference:"语言偏好" }
        return map[t] || t
    }
    function levelZh(l) {
        const map = { short:"短期", mid:"中期", long:"长期" }
        return map[l] || l
    }
    function confidenceLabel(v) {
        if (v >= 0.8) return "高"
        if (v >= 0.5) return "中"
        return "低"
    }
}