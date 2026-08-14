#pragma once
// 空态占位：插画式图标 + 标题 + 引导文案 + 可选按钮。

#include <QWidget>
#include <QIcon>

class QLabel;
class QPushButton;

class EmptyState : public QWidget {
    Q_OBJECT
public:
    explicit EmptyState(QWidget *parent = nullptr);

    void setIconText(const QString &emojiOrGlyph);
    void setIcon(const QIcon &icon);
    void setTitle(const QString &title);
    void setHint(const QString &hint);
    QPushButton *addButton(const QString &text);

private:
    QLabel *m_icon = nullptr;
    QLabel *m_title = nullptr;
    QLabel *m_hint = nullptr;
};
