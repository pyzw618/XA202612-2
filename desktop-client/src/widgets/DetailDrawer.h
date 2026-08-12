#pragma once
// 右侧详情抽屉：标题栏（含关闭） + 内容区。
// 页面通过 open()/close() 控制显隐，内容为任意 QWidget。

#include <QFrame>

class QLabel;
class QPushButton;
class QHBoxLayout;
class QVBoxLayout;
class QStackedWidget;

class DetailDrawer : public QFrame {
    Q_OBJECT
public:
    explicit DetailDrawer(QWidget *parent = nullptr);

    void open(const QString &title, QWidget *content);
    void setContent(QWidget *content);
    void closeDrawer();
    bool isOpen() const { return m_open; }
    void setWidth(int w);

    // 标题栏附加按钮（如"编辑""遗忘"）
    QPushButton *addHeaderButton(const QString &text, const QString &objName = "primaryBtn");

signals:
    void closed();

private:
    QLabel *m_title = nullptr;
    QHBoxLayout *m_headerBtns = nullptr;
    QStackedWidget *m_stack = nullptr;
    bool m_open = false;
};
