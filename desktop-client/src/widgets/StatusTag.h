#pragma once
// 状态/类型标签：圆角小标签，通过对象名属性绑定 QSS 配色。
// 状态: statusTag="active|archived|deleted|pending|superseded|disputed|resolved|..."
// 类型: memTag="preference|knowledge|fact"
// 决策: decisionTag="override|merge|coexist|pending"

#include <QLabel>
#include <QString>

class StatusTag : public QLabel {
    Q_OBJECT
public:
    explicit StatusTag(QWidget *parent = nullptr);

    // 按状态设置（自动映射中文文案 + 配色）
    static QString statusText(const QString &status);
    void setStatus(const QString &status);

    // 按记忆类型设置（preference / knowledge / fact）
    void setMemoryType(const QString &type);
    static QString memoryTypeText(const QString &type);

    // 按冲突决策设置（override / merge / coexist / pending）
    void setDecision(const QString &decision);
    static QString decisionText(const QString &decision);

    // 通用：纯文本标签 + 属性（供自定义配色）
    void setTag(const QString &text, const QString &propName, const QString &propValue);
};
