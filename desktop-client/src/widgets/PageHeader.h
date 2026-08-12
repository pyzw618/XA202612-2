#pragma once
// 页面头部：标题 + 副标题 + 右侧操作区（按钮）

#include <QWidget>

class QLabel;
class QHBoxLayout;

class PageHeader : public QWidget {
    Q_OBJECT
public:
    explicit PageHeader(QWidget *parent = nullptr);

    void setTitle(const QString &title);
    void setSubtitle(const QString &subtitle);
    void setTitlePrefix(const QString &prefix); // 面包屑样式前缀（如 "记忆管理 /"）
    QHBoxLayout *actionLayout() const { return m_actionLayout; }

private:
    QLabel *m_title = nullptr;
    QLabel *m_subtitle = nullptr;
    QLabel *m_prefix = nullptr;
    QHBoxLayout *m_actionLayout = nullptr;
};
