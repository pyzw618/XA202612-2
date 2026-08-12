#include "MainWindow.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QStackedWidget>
#include <QTimer>
#include <QTreeWidget>
#include <QVBoxLayout>

#include "AppContext.h"
#include "api/ApiClient.h"
#include "pages/BasePage.h"
#include "pages/ConflictPage.h"
#include "pages/DashboardPage.h"
#include "pages/FactPage.h"
#include "pages/ForgetPages.h"
#include "pages/KnowledgePage.h"
#include "pages/PreferencePage.h"
#include "pages/SafetyPages.h"
#include "pages/SearchPage.h"
#include "pages/SettingsPages.h"
#include "pages/TerminalPage.h"

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent) {
    setWindowTitle("MemoryHub 控制台 · Kylin-MemoryHub");
    resize(1440, 900);
    setMinimumSize(1180, 720);
    AppContext::instance()->setNavigateCallback([this](const QString &key) { navigateTo(key); });

    auto *central = new QWidget(this);
    central->setObjectName("centralRoot");
    auto *root = new QHBoxLayout(central);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    setCentralWidget(central);

    // ---------------- 侧边栏 ----------------
    m_nav = new QTreeWidget(central);
    m_nav->setObjectName("navTree");
    m_nav->setHeaderHidden(true);
    m_nav->setIndentation(18);
    m_nav->setFixedWidth(228);
    m_nav->setFocusPolicy(Qt::NoFocus);
    buildSidebar();

    // ---------------- 右列：顶栏 + 内容栈 ----------------
    auto *right = new QWidget(central);
    auto *rightLay = new QVBoxLayout(right);
    rightLay->setContentsMargins(0, 0, 0, 0);
    rightLay->setSpacing(0);

    QWidget *topBar = new QWidget(right);
    topBar->setObjectName("topBar");
    auto *topLay = new QHBoxLayout(topBar);
    topLay->setContentsMargins(20, 10, 20, 10);
    topLay->setSpacing(12);

    m_breadcrumb = new QLabel(topBar);
    m_breadcrumb->setObjectName("breadcrumb");
    m_breadcrumb->setText("总览");

    m_globalSearch = new QLineEdit(topBar);
    m_globalSearch->setPlaceholderText("全局搜索记忆，回车跳转检索测试");
    m_globalSearch->setClearButtonEnabled(true);
    m_globalSearch->setFixedWidth(280);
    connect(m_globalSearch, &QLineEdit::returnPressed, this,
            [this]() { navigateToSearch(m_globalSearch->text().trimmed()); });

    m_statusDot = new QLabel(topBar);
    m_statusDot->setFixedSize(10, 10);
    m_statusDot->setStyleSheet("background:#D1D5DB;border-radius:5px;");
    m_statusText = new QLabel(topBar);
    m_statusText->setStyleSheet("color:#8A8F99;font-size:12px;");
    m_statusText->setText("检测中...");

    m_userCombo = new QComboBox(topBar);
    m_userCombo->setEditable(true);
    m_userCombo->addItem("default");
    m_userCombo->addItem("demo_user");
    m_userCombo->setFixedWidth(140);
    m_userCombo->setToolTip("当前用户 ID（所有请求携带 user_id）");
    connect(m_userCombo, qOverload<int>(&QComboBox::activated), this, [this](int) {
        AppContext::instance()->setUserId(m_userCombo->currentText());
        refreshCurrentPage();
    });

    topLay->addWidget(m_breadcrumb, 1);
    topLay->addWidget(m_globalSearch);
    topLay->addWidget(m_statusDot);
    topLay->addWidget(m_statusText);
    topLay->addWidget(m_userCombo);

    m_stack = new QStackedWidget(right);
    rightLay->addWidget(topBar);
    rightLay->addWidget(m_stack, 1);

    root->addWidget(m_nav);
    root->addWidget(right, 1);

    // ---------------- 注册所有页面 ----------------
    registerPage("dashboard", "总览", "Dashboard", new DashboardPage(m_stack));
    registerPage("terminal", "内置终端", "opencode 终端", new TerminalPage(m_stack));

    registerPage("mem/preference", "记忆管理", "偏好记忆", new PreferencePage(m_stack));
    registerPage("mem/knowledge", "记忆管理", "知识记忆", new KnowledgePage(m_stack));
    registerPage("mem/fact", "记忆管理", "事实记忆", new FactPage(m_stack));

    registerPage("search", "检索与冲突", "检索测试", new SearchPage(m_stack));
    registerPage("conflicts", "检索与冲突", "冲突中心", new ConflictPage(m_stack));

    registerPage("forget/precise", "遗忘与生命周期", "精准遗忘", new ForgetPrecisePage(m_stack));
    registerPage("forget/pending", "遗忘与生命周期", "待审查队列", new ForgetPendingPage(m_stack));
    registerPage("forget/archived", "遗忘与生命周期", "归档仓库", new ForgetArchivedPage(m_stack));
    registerPage("forget/recycle", "遗忘与生命周期", "回收站", new ForgetRecyclePage(m_stack));
    registerPage("forget/health", "遗忘与生命周期", "健康度看板", new ForgetHealthPage(m_stack));
    registerPage("forget/history", "遗忘与生命周期", "遗忘历史", new ForgetHistoryPage(m_stack));
    registerPage("forget/settings", "遗忘与生命周期", "遗忘设置", new ForgetSettingsPage(m_stack));

    registerPage("safety/overview", "安全中心", "安全总览", new SafetyOverviewPage(m_stack));
    registerPage("safety/user-rules", "安全中心", "用户规则", new SafetyUserRulesPage(m_stack));
    registerPage("safety/audit", "安全中心", "审计日志", new SafetyAuditPage(m_stack));
    registerPage("safety/quarantine", "安全中心", "隔离区", new SafetyQuarantinePage(m_stack));

    registerPage("settings/status", "系统设置", "后端状态", new SettingsStatusPage(m_stack));
    registerPage("settings/config", "系统设置", "参数查看", new SettingsConfigPage(m_stack));
    registerPage("settings/demo", "系统设置", "演示数据工具", new SettingsDemoPage(m_stack));

    // ---------------- 健康轮询 ----------------
    m_healthTimer = new QTimer(this);
    m_healthTimer->setInterval(15000);
    connect(m_healthTimer, &QTimer::timeout, this, &MainWindow::pollHealth);
    m_healthTimer->start();
    QTimer::singleShot(200, this, &MainWindow::pollHealth);

    // ---------------- 导航点击 ----------------
    connect(m_nav, &QTreeWidget::itemSelectionChanged, this, [this]() {
        QTreeWidgetItem *item = m_nav->currentItem();
        if (!item || item->childCount() > 0) return;
        const QString key = item->data(0, Qt::UserRole).toString();
        if (!key.isEmpty()) navigateTo(key);
    });

    // 初始选中"总览"
    QTreeWidgetItem *first = m_nav->topLevelItem(0);
    if (first) {
        m_nav->setCurrentItem(first);
        navigateTo("dashboard");
    }
}

void MainWindow::buildSidebar() {
    auto addGroup = [&](const QString &label) -> QTreeWidgetItem * {
        auto *item = new QTreeWidgetItem(m_nav, QStringList{label});
        item->setFlags(Qt::ItemIsEnabled);
        item->setData(0, Qt::UserRole, QString("__group__"));
        QFont f = item->font(0);
        f.setBold(true);
        f.setPointSizeF(9.5);
        item->setFont(0, f);
        item->setForeground(0, QColor("#8A8F99"));
        item->setExpanded(true);
        return item;
    };

    auto addLeaf = [&](QTreeWidgetItem *group, const QString &label, const QString &key,
                       bool highlight = false) {
        QString text = highlight ? "●  " + label : label;
        auto *item = new QTreeWidgetItem(group, QStringList{text});
        item->setData(0, Qt::UserRole, key);
        if (highlight) item->setForeground(0, QColor("#DC2626"));
    };

    QTreeWidgetItem *g1 = addGroup("总览");
    addLeaf(g1, "Dashboard", "dashboard");

    QTreeWidgetItem *gTerm = addGroup("内置终端");
    addLeaf(gTerm, "opencode 终端", "terminal");

    QTreeWidgetItem *g2 = addGroup("记忆管理");
    addLeaf(g2, "偏好记忆", "mem/preference");
    addLeaf(g2, "知识记忆", "mem/knowledge");
    addLeaf(g2, "事实记忆", "mem/fact");

    QTreeWidgetItem *g3 = addGroup("检索与冲突");
    addLeaf(g3, "检索测试", "search");
    addLeaf(g3, "冲突中心", "conflicts");

    QTreeWidgetItem *g4 = addGroup("遗忘与生命周期");
    addLeaf(g4, "精准遗忘", "forget/precise");
    addLeaf(g4, "待审查队列", "forget/pending", true);
    addLeaf(g4, "归档仓库", "forget/archived");
    addLeaf(g4, "回收站", "forget/recycle");
    addLeaf(g4, "健康度看板", "forget/health");
    addLeaf(g4, "遗忘历史", "forget/history");
    addLeaf(g4, "遗忘设置", "forget/settings");

    QTreeWidgetItem *g5 = addGroup("安全中心");
    addLeaf(g5, "安全总览", "safety/overview");
    addLeaf(g5, "用户规则", "safety/user-rules");
    addLeaf(g5, "审计日志", "safety/audit");
    addLeaf(g5, "隔离区", "safety/quarantine", true);

    QTreeWidgetItem *g6 = addGroup("系统设置");
    addLeaf(g6, "后端状态", "settings/status");
    addLeaf(g6, "参数查看", "settings/config");
    addLeaf(g6, "演示数据工具", "settings/demo");
}

void MainWindow::registerPage(const QString &key, const QString &group, const QString &title,
                              BasePage *page) {
    PageEntry e;
    e.page = page;
    e.group = group;
    e.title = title;
    m_pages.insert(key, e);
    m_stack->addWidget(page);
}

void MainWindow::navigateTo(const QString &key) {
    if (!m_pages.contains(key)) return;
    if (key == m_currentKey) return;
    const PageEntry &e = m_pages.value(key);
    m_currentKey = key;
    m_stack->setCurrentWidget(e.page);
    m_breadcrumb->setText(e.group.isEmpty() ? e.title : e.group + " / " + e.title);
    e.page->refresh();
}

void MainWindow::navigateToSearch(const QString &query) {
    if (!m_pages.contains("search")) return;
    navigateTo("search");
    if (!query.isEmpty()) {
        auto *page = qobject_cast<SearchPage *>(m_pages.value("search").page);
        if (page) page->applySearchQuery(query);
    }
}

void MainWindow::pollHealth() {
    api::ApiClient *client = AppContext::instance()->api();
    client->getAsync("/api/health", [this](const api::Result &r) {
        bool online = r.ok && r.jsonObject().value("status").toString() == "ok";
        m_backendOnline = online;
        m_healthChecked = true;
        if (online) {
            m_statusDot->setStyleSheet("background:#22C55E;border-radius:5px;");
            m_statusText->setText("后端已连接");
        } else {
            m_statusDot->setStyleSheet("background:#EF4444;border-radius:5px;");
            m_statusText->setText("后端离线");
        }
    });
}

void MainWindow::refreshCurrentPage() {
    if (m_pages.contains(m_currentKey)) {
        m_pages.value(m_currentKey).page->refresh();
    }
}

void MainWindow::closeEvent(QCloseEvent *e) {
    QMainWindow::closeEvent(e);
}
