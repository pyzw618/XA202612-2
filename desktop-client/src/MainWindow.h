#pragma once
// 主窗口：左侧导航 + 顶栏（面包屑/全局搜索/连接状态/用户切换）+ 内容区

#include <QMainWindow>
#include <QMap>
#include <QString>

class QTreeWidget;
class QTreeWidgetItem;
class QStackedWidget;
class QLabel;
class QLineEdit;
class QComboBox;
class QTimer;
class QPushButton;
class QWidget;
class QResizeEvent;
class BasePage;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);

    // 全局搜索跳转（供顶栏调用）
    void navigateToSearch(const QString &query);

protected:
    void closeEvent(QCloseEvent *e) override;
    void resizeEvent(QResizeEvent *e) override;

private:
    // 侧边栏磨砂玻璃：窗口启用透明背景，由 ukui 样式读取 blurRegion 属性做区域模糊
    void updateBlurRegion();
    void buildSidebar();
    void buildTopBar();
    void registerPage(const QString &key, const QString &group, const QString &title,
                      BasePage *page);
    void navigateTo(const QString &key);
    void updateBreadcrumb(const QString &group, const QString &title);
    void pollHealth();
    void refreshCurrentPage();
    void polishPopupControls(QWidget *root);

    QTreeWidget *m_nav = nullptr;
    QWidget *m_sidebar = nullptr;
    QStackedWidget *m_stack = nullptr;
    QLabel *m_breadcrumb = nullptr;
    QLabel *m_statusDot = nullptr;
    QLabel *m_statusText = nullptr;
    QLineEdit *m_globalSearch = nullptr;
    QLineEdit *m_userEdit = nullptr;
    QPushButton *m_refreshButton = nullptr;
    QTimer *m_healthTimer = nullptr;

    struct PageEntry {
        BasePage *page = nullptr;
        QString group;
        QString title;
    };
    QMap<QString, PageEntry> m_pages;
    QString m_currentKey;
};
