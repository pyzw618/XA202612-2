#pragma once
// 只读 JSON 查看器：等宽字体 + 语法缩进展示，支持复制。

#include <QWidget>

class QPlainTextEdit;
class QJsonObject;
class QJsonArray;

class JsonViewer : public QWidget {
    Q_OBJECT
public:
    explicit JsonViewer(QWidget *parent = nullptr);

    void setObject(const QJsonObject &o);
    void setArray(const QJsonArray &a);
    void setText(const QString &text);
    void clear();

    QPlainTextEdit *editor() const { return m_edit; }

private:
    QPlainTextEdit *m_edit = nullptr;
};
