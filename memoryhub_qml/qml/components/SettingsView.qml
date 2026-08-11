import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 系统设置页 — 后端连接信息 + 演示数据管理 */
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
                    Label { text: "系统设置"; font.pixelSize: 17; font.bold: true; color: "#172033" }
                    Label { text: "后端连接与演示数据管理"; color: "#94A3B8"; font.pixelSize: 11 }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#E2E8F0" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ColumnLayout {
                width: parent.width
                Layout.leftMargin: 20; Layout.rightMargin: 20; Layout.topMargin: 16; Layout.bottomMargin: 20
                spacing: 16

                // ---- 后端连接 ----
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 200
                    radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 20; spacing: 16
                        Label { text: "后端连接"; font.bold: true; color: "#172033"; font.pixelSize: 14 }
                        GridLayout {
                            columns: 2; Layout.fillWidth: true
                            columnSpacing: 16; rowSpacing: 12
                            property int labelCol: 80
                            Label { Layout.preferredWidth: parent.labelCol; text: "服务地址"; color: "#64748B" }
                            Label { Layout.fillWidth: true; text: controller.backendUrl; color: "#172033"; font.bold: true; elide: Text.ElideRight }
                            Label { Layout.preferredWidth: parent.labelCol; text: "连接状态"; color: "#64748B" }
                            RowLayout { Layout.fillWidth: true; spacing: 8
                                Rectangle { width: 8; height: 8; radius: 4; color: controller.online ? "#10B981" : "#EF4444" }
                                Label { text: controller.online ? "已连接" : "离线"; color: controller.online ? "#047857" : "#B91C1C"; font.bold: true }
                            }
                            Label { Layout.preferredWidth: parent.labelCol; text: "当前用户"; color: "#64748B" }
                            Label { Layout.fillWidth: true; text: controller.currentUserId; color: "#172033" }
                        }
                        RowLayout { Layout.fillWidth: true; spacing: 12
                            Button { text: "重新检测"; onClicked: controller.retryBackend() }
                            Button { text: "打开 API 文档"; onClicked: controller.openApiDocs() }
                        }
                    }
                }

                // ---- 演示数据 ----
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 180
                    radius: 12; color: "#FEF2F2"; border.color: "#FECACA"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 20; spacing: 14
                        Label { text: "演示数据"; font.bold: true; color: "#991B1B"; font.pixelSize: 14 }
                        Label { text: "清空当前用户（demo_user）的全部偏好记忆，便于重新执行演示。知识 / 事实 / 冲突不清。"; color: "#7F1D1D"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Item { Layout.fillHeight: true }
                        Button { text: "清空偏好记忆"; highlighted: true; Layout.preferredWidth: 140; onClicked: confirmDialog.open() }
                    }
                }
            }
        }
    }

    Dialog {
        id: confirmDialog
        title: "清空偏好记忆"
        modal: true
        standardButtons: Dialog.Cancel | Dialog.Ok
        width: 380
        anchors.centerIn: parent
        onAccepted: controller.clearPreferences()
        Label { text: "将删除当前用户的全部偏好记忆，此操作不可撤销。确定继续？"; wrapMode: Text.Wrap; color: "#334155" }
    }
}