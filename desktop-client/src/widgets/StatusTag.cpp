#include "StatusTag.h"

#include <QDebug>
#include <QStyle>

StatusTag::StatusTag(QWidget *parent) : QLabel(parent) {
    setProperty("tagBase", true);
    setAlignment(Qt::AlignCenter);
    setTextInteractionFlags(Qt::NoTextInteraction);
    // 让 QSS 的 QLabel[tagBase=true] 生效需要重新解析样式
    style()->unpolish(this);
    style()->polish(this);
}

QString StatusTag::statusText(const QString &status) {
    if (status == "active") return "有效";
    if (status == "archived") return "已归档";
    if (status == "deleted") return "已删除";
    if (status == "pending") return "待审查";
    if (status == "superseded") return "已替代";
    if (status == "disputed") return "存疑";
    if (status == "resolved") return "已解决";
    if (status == "dead_letter") return "死信";
    if (status == "succeeded") return "成功";
    if (status == "retry") return "重试中";
    if (status == "running") return "执行中";
    if (status == "committed") return "已入库";
    if (status == "rejected") return "已驳回";
    if (status == "proposed") return "待裁决";
    if (status == "awaiting_decision") return "待决策";
    return status;
}

void StatusTag::setStatus(const QString &status) {
    const QString s = status.toLower();
    setTag(statusText(s), "statusTag", s);
}

QString StatusTag::memoryTypeText(const QString &type) {
    if (type == "preference") return "偏好";
    if (type == "knowledge") return "知识";
    if (type == "fact") return "事实";
    return type;
}

void StatusTag::setMemoryType(const QString &type) {
    const QString t = type.toLower();
    setTag(memoryTypeText(t), "memTag", t);
}

QString StatusTag::decisionText(const QString &decision) {
    if (decision == "override") return "覆盖";
    if (decision == "merge") return "合并";
    if (decision == "coexist") return "并存";
    if (decision == "pending") return "待确认";
    if (decision == "resolve") return "已解决";
    return decision;
}

void StatusTag::setDecision(const QString &decision) {
    const QString d = decision.toLower();
    // 决策语义：override 红 / merge 紫 / coexist 蓝 / pending 琥珀
    QString propVal;
    if (d == "override") propVal = "deleted";       // 红
    else if (d == "merge") propVal = "knowledge";   // 紫
    else if (d == "coexist") propVal = "fact";      // 青
    else propVal = "pending";                       // 琥珀
    // 决策用 statusTag 配色，override 映射 deleted(红)，merge 用 memTag 紫，coexist 用 memTag 青
    setTag(decisionText(d), "statusTag", propVal);
}

void StatusTag::setTag(const QString &text, const QString &propName, const QString &propValue) {
    setText(text);
    setProperty(propName.toUtf8().constData(), QVariant(propValue));
    // 保留 base 样式属性
    setProperty("tagBase", true);
    style()->unpolish(this);
    style()->polish(this);
    update();
}
