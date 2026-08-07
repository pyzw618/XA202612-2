import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    property var proposal: ({})
    title: "事实候选 · Propose / Commit"
    modal: true
    width: Math.min(620, parent ? parent.width - 40 : 620)
    anchors.centerIn: parent
    standardButtons: Dialog.NoButton

    background: Rectangle { radius: 16; color: "white"; border.color: "#E2E8F0" }
    contentItem: ColumnLayout {
        spacing: 14
        Label { text: "PROPOSE  ·  只读分析"; color: "#2563EB"; font.bold: true }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: triple.implicitHeight + 24; radius: 12; color: "#F8FAFC"; border.color: "#E2E8F0"
            ColumnLayout {
                id: triple
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                spacing: 8
                Label { Layout.fillWidth: true; text: (dialog.proposal.subject || "—") + "  /  " + (dialog.proposal.predicate || "—") + "  /  " + (dialog.proposal.objectValue || "—"); font.bold: true; color: "#172033"; wrapMode: Text.Wrap }
                Label { Layout.fillWidth: true; text: "证据：" + (dialog.proposal.evidence || "—"); color: "#475569"; wrapMode: Text.Wrap }
                Label { text: "置信度 " + Math.round((dialog.proposal.confidence || 0) * 100) + "%  ·  " + (dialog.proposal.admissionReason || ""); color: "#64748B"; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }
        Label { text: "COMMIT  ·  用户裁决"; color: "#2563EB"; font.bold: true }
        RowLayout {
            Layout.fillWidth: true
            ComboBox { id: scope; Layout.fillWidth: true; model: ["project", "global"]; currentIndex: dialog.proposal.suggestedScope === "global" ? 1 : 0 }
            TextField { id: projectId; Layout.fillWidth: true; placeholderText: "项目 ID（项目作用域）"; text: "XA202612-2"; enabled: scope.currentText === "project" }
        }
        ComboBox { id: resolution; Layout.fillWidth: true; model: ["coexist", "replace", "keep", "merge", "escalate"] }
        RowLayout {
            Layout.fillWidth: true
            Button { text: "忽略"; onClicked: { controller.submitFactDecision(dialog.proposal.proposalId || "", false, scope.currentText, projectId.text, resolution.currentText); dialog.close() } }
            Item { Layout.fillWidth: true }
            Button { text: "取消"; onClicked: dialog.close() }
            Button { text: "提交给 Agent"; highlighted: true; onClicked: { controller.submitFactDecision(dialog.proposal.proposalId || "", true, scope.currentText, projectId.text, resolution.currentText); dialog.close() } }
        }
    }
}
