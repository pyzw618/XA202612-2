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
class BasePage;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);

    // 全局搜索跳转（供顶栏调用）
    void navigateToSearch(const QString &query);

protected:
    void closeEvent(QCloseEvent *e) override;

private:
    void buildSidebar();
    void buildTopBar();
    void registerPage(const QString &key, const QString &group, const QString &title,
                      BasePage *page);
    void navigateTo(const QString &key);
    void updateBreadcrumb(const QString &group, const QString &title);
    void pollHealth();
    void refreshCurrentPage();

    QTreeWidget *m_nav = nullptr;
    QStackedWidget *m_stack = nullptr;
    QLabel *m_breadcrumb = nullptr;
    QLabel *m_statusDot = nullptr;
    QLabel *m_statusText = nullptr;
    QLineEdit *m_globalSearch = nullptr;
    QComboBox *m_userCombo = nullptr;
    QTimer *m_healthTimer = nullptr;
    bool m_backendOnline = false;
    bool m_healthChecked = false;

    struct PageEntry {
        BasePage *page = nullptr;
        QString group;
        QString title;
    };
    QMap<QString, PageEntry> m_pages;
    QString m_currentKey;
};
