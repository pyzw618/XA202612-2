#include "MainWindow.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QImage>
#include <QLabel>
#include <QList>
#include <QListView>
#include <QLineEdit>
#include <QPainter>
#include <QPalette>
#include <QPushButton>
#include <QPair>
#include <QRegion>
#include <QResizeEvent>
#include <QScreen>
#include <QStackedWidget>
#include <QStyle>
#include <QTimer>
#include <QShortcut>
#include <QTreeWidget>
#include <QVBoxLayout>
#include <QVariant>

#include <functional>

#include "AppContext.h"
#include "api/ApiClient.h"
#include "pages/BasePage.h"
#include "pages/ConflictPage.h"
#include "pages/DashboardPage.h"
#include "pages/VNextDashboardPages.h"
#include "pages/FactPage.h"
#include "pages/ForgetPages.h"
#include "pages/KnowledgePage.h"
#include "pages/MemoryTierPage.h"
#include "pages/PreferencePage.h"
#include "pages/SafetyPages.h"
#include "pages/SearchPage.h"
#include "pages/ProjectionPage.h"
#include "pages/SettingsPages.h"

namespace {
QRect visibleBounds(const QImage &image) {
    int left = image.width();
    int top = image.height();
    int right = -1;
    int bottom = -1;
    for (int y = 0; y < image.height(); ++y) {
        for (int x = 0; x < image.width(); ++x) {
            if (qAlpha(image.pixel(x, y)) > 8) {
                left = qMin(left, x);
                top = qMin(top, y);
                right = qMax(right, x);
                bottom = qMax(bottom, y);
            }
        }
    }
    return right >= left ? QRect(QPoint(left, top), QPoint(right, bottom)) : QRect();
}

QPixmap tintedNavPixmap(const QString &iconPath, const QColor &color, qreal dpr) {
    constexpr int kCanvasSize = 18;
    constexpr int kVisibleSize = 16;
    const int canvasPixels = qRound(kCanvasSize * dpr);
    const int sourcePixels = qRound(48 * dpr);
    QPixmap source = QIcon(iconPath).pixmap(sourcePixels, sourcePixels);
    QPixmap tinted(source.size());
    tinted.fill(Qt::transparent);

    QPainter painter(&tinted);
    painter.drawPixmap(0, 0, source);
    painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
    painter.fillRect(tinted.rect(), color);
    painter.end();

    const QImage image = tinted.toImage();
    const QRect bounds = visibleBounds(image);
    QPixmap canvas(canvasPixels, canvasPixels);
    canvas.fill(Qt::transparent);
    if (!bounds.isEmpty()) {
        const int targetPixels = qRound(kVisibleSize * dpr);
        const QPixmap visible = QPixmap::fromImage(image.copy(bounds)).scaled(
            targetPixels, targetPixels, Qt::KeepAspectRatio, Qt::SmoothTransformation);
        QPainter canvasPainter(&canvas);
        canvasPainter.drawPixmap((canvasPixels - visible.width()) / 2,
                                 (canvasPixels - visible.height()) / 2, visible);
    }
    canvas.setDevicePixelRatio(dpr);
    return canvas;
}

QIcon navIcon(const QString &iconPath) {
    QIcon icon;
    for (qreal dpr : {1.0, 2.0}) {
        icon.addPixmap(tintedNavPixmap(iconPath, QColor("#607089"), dpr), QIcon::Normal);
        icon.addPixmap(tintedNavPixmap(iconPath, QColor("#3D78DF"), dpr), QIcon::Selected);
        icon.addPixmap(tintedNavPixmap(iconPath, QColor("#3D78DF"), dpr), QIcon::Active);
    }
    return icon;
}

class UserSwitcherPopup : public QWidget {
public:
    explicit UserSwitcherPopup(const QList<QPair<QString, QString>> &users,
                               std::function<void(const QString &)> onSelect,
                               QWidget *parent = nullptr)
        : QWidget(parent, Qt::Popup | Qt::FramelessWindowHint), m_onSelect(std::move(onSelect)) {
        setAttribute(Qt::WA_TranslucentBackground, true);
        setAttribute(Qt::WA_ShowWithoutActivating, true);

        auto *layout = new QVBoxLayout(this);
        layout->setContentsMargins(7, 7, 7, 7);
        layout->setSpacing(3);
        for (const auto &user : users) {
            const QString userId = user.first;
            auto *button = new QPushButton(user.second, this);
            button->setObjectName("userPopupOption");
            button->setProperty("userId", userId);
            button->setCheckable(true);
            button->setFixedHeight(36);
            connect(button, &QPushButton::clicked, this, [this, userId]() {
                hide();
                m_onSelect(userId);
            });
            m_options.append(button);
            layout->addWidget(button);
        }
    }

    void setCurrentUser(const QString &userId) {
        for (QPushButton *button : m_options)
            button->setChecked(button->property("userId").toString() == userId);
    }

protected:
    void paintEvent(QPaintEvent *event) override {
        Q_UNUSED(event)
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setBrush(QColor("#FFFFFF"));
        painter.setPen(QPen(QColor("#D9E1EB"), 1.0));
        painter.drawRoundedRect(QRectF(rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10);
    }

private:
    std::function<void(const QString &)> m_onSelect;
    QList<QPushButton *> m_options;
};
} // namespace

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent) {
    setWindowTitle("MemoryHub 控制台 · Kylin-MemoryHub");
    resize(1440, 900);
    setMinimumSize(1180, 720);
    // UKUI 原生毛玻璃：开启窗口透明，由 ukui 样式 + 合成器对侧边栏区域做背景模糊。
    // 通过 blurRegion 属性限定模糊范围（见 updateBlurRegion()）。
    setAttribute(Qt::WA_TranslucentBackground, true);
    setProperty("useSystemStyleBlur", true);
    setProperty("doNotBlur", false);
    AppContext::instance()->setNavigateCallback([this](const QString &key) { navigateTo(key); });

    auto *central = new QWidget(this);
    central->setObjectName("centralRoot");
    auto *root = new QHBoxLayout(central);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    setCentralWidget(central);

    // ---------------- 侧边栏 ----------------
    auto *sidebar = new QWidget(central);
    sidebar->setObjectName("sidebar");
    sidebar->setFixedWidth(224);
    m_sidebar = sidebar;
    auto *sidebarLay = new QVBoxLayout(sidebar);
    sidebarLay->setContentsMargins(14, 18, 14, 14);
    sidebarLay->setSpacing(12);

    auto *brand = new QWidget(sidebar);
    brand->setObjectName("brandBlock");
    auto *brandLay = new QHBoxLayout(brand);
    brandLay->setContentsMargins(6, 0, 4, 8);
    brandLay->setSpacing(10);
    auto *brandIcon = new QLabel(brand);
    brandIcon->setObjectName("brandIcon");
    brandIcon->setPixmap(QIcon(":/icons/logo.svg").pixmap(30, 30));
    auto *brandText = new QVBoxLayout();
    brandText->setSpacing(0);
    auto *brandTitle = new QLabel("MemoryHub", brand);
    brandTitle->setObjectName("brandTitle");
    auto *brandSub = new QLabel("智能记忆工作台", brand);
    brandSub->setObjectName("brandSubtitle");
    brandText->addWidget(brandTitle);
    brandText->addWidget(brandSub);
    brandLay->addWidget(brandIcon);
    brandLay->addLayout(brandText, 1);
    sidebarLay->addWidget(brand);

    m_nav = new QTreeWidget(sidebar);
    m_nav->setObjectName("navTree");
    m_nav->setHeaderHidden(true);
    m_nav->setIndentation(0);
    m_nav->setIconSize(QSize(18, 18));
    m_nav->setFocusPolicy(Qt::StrongFocus);
    m_nav->setAccessibleName("主导航");
    m_nav->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    buildSidebar();
    sidebarLay->addWidget(m_nav, 1);

    auto *account = new QFrame(sidebar);
    account->setObjectName("accountPanel");
    auto *accountLay = new QVBoxLayout(account);
    accountLay->setContentsMargins(10, 10, 10, 10);
    accountLay->setSpacing(6);
    auto *accountRow = new QHBoxLayout();
    auto *avatar = new QLabel(account);
    avatar->setObjectName("avatar");
    avatar->setPixmap(QIcon(":/icons/user.svg").pixmap(20, 20));
    avatar->setAlignment(Qt::AlignCenter);
    avatar->setFixedSize(34, 34);
    auto *accountLabels = new QVBoxLayout();
    accountLabels->setSpacing(0);
    auto *accountCaption = new QLabel("记忆用户", account);
    accountCaption->setObjectName("accountCaption");
    auto *userSwitcher = new QWidget(account);
    userSwitcher->setObjectName("userSwitcherFrame");
    userSwitcher->setFixedHeight(36);
    auto *userSwitcherLayout = new QHBoxLayout(userSwitcher);
    userSwitcherLayout->setContentsMargins(10, 0, 4, 0);
    userSwitcherLayout->setSpacing(2);
    m_userEdit = new QLineEdit(AppContext::instance()->userId(), userSwitcher);
    m_userEdit->setObjectName("userSwitcher");
    m_userEdit->setReadOnly(true);
    m_userEdit->setToolTip("当前记忆归属；默认使用登录 Linux 的系统用户");
    const QString systemUser = AppContext::instance()->systemUserId();
    const QList<QPair<QString, QString>> userChoices{
        {systemUser, QString("%1（当前用户）").arg(systemUser)},
        {AppContext::globalUserId(), QStringLiteral("global（全局用户）")},
    };
    auto *userPopup = new UserSwitcherPopup(userChoices, [this](const QString &userId) {
        m_userEdit->setText(userId);
        AppContext::instance()->setUserId(userId);
    }, userSwitcher);
    auto *userDropButton = new QPushButton(QIcon(":/icons/chevron-down.svg"), QString(), userSwitcher);
    userDropButton->setObjectName("userDropButton");
    userDropButton->setFixedSize(28, 28);
    userDropButton->setToolTip("切换用户");
    userSwitcherLayout->addWidget(m_userEdit, 1);
    userSwitcherLayout->addWidget(userDropButton);
    connect(userDropButton, &QPushButton::clicked, this, [this, userPopup, userSwitcher]() {
        userPopup->setCurrentUser(m_userEdit->text().trimmed());
        const QSize menuSize(userSwitcher->width(), userPopup->sizeHint().height());
        userPopup->resize(menuSize);
        const QPoint below = userSwitcher->mapToGlobal(QPoint(0, userSwitcher->height() + 6));
        const QPoint above = userSwitcher->mapToGlobal(QPoint(0, -menuSize.height() - 6));
        QScreen *screen = m_userEdit->screen();
        const QRect available = screen ? screen->availableGeometry() : QRect();
        const bool canOpenBelow = !available.isValid() || below.y() + menuSize.height() <= available.bottom();
        userPopup->move(canOpenBelow ? below : above);
        userPopup->show();
    });
    accountLabels->addWidget(accountCaption);
    accountLabels->addWidget(userSwitcher);
    accountRow->addWidget(avatar);
    accountRow->addLayout(accountLabels, 1);
    accountLay->addLayout(accountRow);
    auto *connectionRow = new QHBoxLayout();
    connectionRow->setSpacing(7);
    m_statusDot = new QLabel(account);
    m_statusDot->setObjectName("statusDot");
    m_statusDot->setProperty("online", false);
    m_statusDot->setFixedSize(8, 8);
    m_statusText = new QLabel("正在检测后端", account);
    m_statusText->setObjectName("connectionText");
    connectionRow->addWidget(m_statusDot);
    connectionRow->addWidget(m_statusText, 1);
    accountLay->addLayout(connectionRow);
    sidebarLay->addWidget(account);

    // ---------------- 右列：顶栏 + 内容栈 ----------------
    auto *right = new QWidget(central);
    right->setObjectName("rightPane");
    auto *rightLay = new QVBoxLayout(right);
    rightLay->setContentsMargins(0, 0, 0, 0);
    rightLay->setSpacing(0);

    QWidget *topBar = new QWidget(right);
    topBar->setObjectName("topBar");
    auto *topLay = new QHBoxLayout(topBar);
    topLay->setContentsMargins(24, 10, 24, 10);
    topLay->setSpacing(12);

    m_breadcrumb = new QLabel(topBar);
    m_breadcrumb->setObjectName("breadcrumb");
    m_breadcrumb->setText("总览");

    m_globalSearch = new QLineEdit(topBar);
    m_globalSearch->setObjectName("globalSearch");
    m_globalSearch->setPlaceholderText("搜索记忆、事实或知识…");
    m_globalSearch->addAction(QIcon(":/icons/search.svg"), QLineEdit::LeadingPosition);
    m_globalSearch->setClearButtonEnabled(true);
    m_globalSearch->setFixedWidth(320);
    m_globalSearch->setAccessibleName("全局搜索");
    m_globalSearch->setAccessibleDescription("输入查询并按回车打开检索测试");
    connect(m_globalSearch, &QLineEdit::returnPressed, this,
            [this]() { navigateToSearch(m_globalSearch->text().trimmed()); });

    m_refreshButton = new QPushButton(QIcon(":/icons/refresh.svg"), "刷新", topBar);
    m_refreshButton->setObjectName("toolbarButton");
    m_refreshButton->setAccessibleName("刷新当前页面");
    connect(m_refreshButton, &QPushButton::clicked, this, [this]() {
        pollHealth();
        refreshCurrentPage();
    });
    auto *focusSearch = new QShortcut(QKeySequence("Ctrl+K"), this);
    connect(focusSearch, &QShortcut::activated, this, [this]() {
        m_globalSearch->setFocus(Qt::ShortcutFocusReason);
        m_globalSearch->selectAll();
    });
    auto *refreshShortcut = new QShortcut(QKeySequence("Ctrl+R"), this);
    connect(refreshShortcut, &QShortcut::activated, this, &MainWindow::refreshCurrentPage);
    auto *f5Shortcut = new QShortcut(QKeySequence(Qt::Key_F5), this);
    connect(f5Shortcut, &QShortcut::activated, this, &MainWindow::refreshCurrentPage);

    topLay->addWidget(m_breadcrumb, 1);
    topLay->addWidget(m_globalSearch);
    topLay->addWidget(m_refreshButton);

    m_stack = new QStackedWidget(right);
    rightLay->addWidget(topBar);
    rightLay->addWidget(m_stack, 1);

    root->addWidget(sidebar);
    root->addWidget(right, 1);

    // ---------------- 注册所有页面 ----------------
    registerPage("dashboard", "总览", "Dashboard", new DashboardPage(m_stack));
    registerPage("dashboard/explorer", "vNext Dashboard", "Memory Explorer",
                 new VNextDashboardPage(VNextDashboardPage::View::Explorer, m_stack));
    registerPage("dashboard/evolution", "vNext Dashboard", "Evolution",
                 new VNextDashboardPage(VNextDashboardPage::View::Evolution, m_stack));
    registerPage("dashboard/retrieval", "vNext Dashboard", "Retrieval Debugger",
                 new VNextDashboardPage(VNextDashboardPage::View::RetrievalDebugger, m_stack));
    registerPage("dashboard/benchmark", "vNext Dashboard", "Benchmark",
                 new VNextDashboardPage(VNextDashboardPage::View::Benchmark, m_stack));
    registerPage("mem/preference", "记忆管理", "偏好记忆", new PreferencePage(m_stack));
    registerPage("mem/knowledge", "记忆管理", "知识记忆", new KnowledgePage(m_stack));
    registerPage("mem/tiers", "记忆管理", "记忆分层", new MemoryTierPage(m_stack));
    registerPage("mem/fact", "记忆管理", "事实记忆", new FactPage(m_stack));

    registerPage("search", "检索与冲突", "检索测试", new SearchPage(m_stack));
    registerPage("conflicts", "检索与冲突", "冲突中心", new ConflictPage(m_stack));
    registerPage("projections", "检索与冲突", "投影恢复", new ProjectionPage(m_stack));

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
    registerPage("settings/llm", "系统设置", "LLM 服务", new SettingsLLMPage(m_stack));
    registerPage("settings/config", "系统设置", "参数查看", new SettingsConfigPage(m_stack));
    registerPage("settings/demo", "系统设置", "演示数据工具", new SettingsDemoPage(m_stack));

    // Qt 在 Windows 上默认给下拉弹层套用原生黑边和厚阴影。
    // 全项目改用轻量、无原生阴影的统一列表视图。
    polishPopupControls(central);

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

    // 初始选中"总览"。构造阶段只切换页面，不触发网络请求；
    // 等窗口进入事件循环并完成首次绘制后再刷新。
    QTreeWidgetItem *firstGroup = m_nav->topLevelItem(0);
    QTreeWidgetItem *first = firstGroup && firstGroup->childCount() > 0
                                 ? firstGroup->child(0)
                                 : firstGroup;
    if (first) {
        m_nav->blockSignals(true);
        m_nav->setCurrentItem(first);
        m_nav->blockSignals(false);
        const PageEntry &entry = m_pages.value("dashboard");
        m_currentKey = "dashboard";
        m_stack->setCurrentWidget(entry.page);
        updateBreadcrumb(entry.group, entry.title);
    }

    QTimer::singleShot(120, this, [this]() {
        pollHealth();
        refreshCurrentPage();
    });

    updateBlurRegion();
}

void MainWindow::updateBlurRegion() {
    if (!m_sidebar)
        return;
    const QPoint topLeft = m_sidebar->mapTo(this, QPoint(0, 0));
    const QRegion region(QRect(topLeft, m_sidebar->size()));
    setProperty("blurRegion", QVariant::fromValue(region));
    if (isVisible())
        update();
}

void MainWindow::resizeEvent(QResizeEvent *e) {
    QMainWindow::resizeEvent(e);
    updateBlurRegion();
}

void MainWindow::buildSidebar() {
    auto addGroup = [&](const QString &label) -> QTreeWidgetItem * {
        auto *item = new QTreeWidgetItem(m_nav, QStringList{label});
        item->setFlags(Qt::ItemIsEnabled);
        item->setData(0, Qt::UserRole, QString("__group__"));
        QFont f = item->font(0);
        f.setBold(false);
        f.setPointSizeF(8.5);
        item->setFont(0, f);
        item->setForeground(0, QColor("#8A8F99"));
        item->setExpanded(true);
        return item;
    };

    auto addLeaf = [&](QTreeWidgetItem *group, const QString &label, const QString &key,
                       const QString &icon) {
        auto *item = new QTreeWidgetItem(group, QStringList{label});
        item->setData(0, Qt::UserRole, key);
        item->setIcon(0, navIcon(icon));
    };

    QTreeWidgetItem *g1 = addGroup("工作台");
    addLeaf(g1, "总览", "dashboard", ":/icons/dashboard.svg");
    addLeaf(g1, "Memory Explorer", "dashboard/explorer", ":/icons/database.svg");
    addLeaf(g1, "Evolution", "dashboard/evolution", ":/icons/history.svg");
    addLeaf(g1, "Retrieval Debugger", "dashboard/retrieval", ":/icons/search.svg");
    addLeaf(g1, "Benchmark", "dashboard/benchmark", ":/icons/activity.svg");
    QTreeWidgetItem *g2 = addGroup("记忆");
    addLeaf(g2, "偏好记忆", "mem/preference", ":/icons/preference.svg");
    addLeaf(g2, "知识记忆", "mem/knowledge", ":/icons/knowledge.svg");
    addLeaf(g2, "记忆分层", "mem/tiers", ":/icons/activity.svg");
    addLeaf(g2, "事实记忆", "mem/fact", ":/icons/fact.svg");

    QTreeWidgetItem *g3 = addGroup("处理中心");
    addLeaf(g3, "检索测试", "search", ":/icons/search.svg");
    addLeaf(g3, "冲突中心", "conflicts", ":/icons/conflict.svg");
    addLeaf(g3, "投影恢复", "projections", ":/icons/refresh.svg");
    addLeaf(g3, "精准遗忘", "forget/precise", ":/icons/target.svg");
    addLeaf(g3, "待审查队列", "forget/pending", ":/icons/history.svg");
    addLeaf(g3, "归档仓库", "forget/archived", ":/icons/archive.svg");
    addLeaf(g3, "回收站", "forget/recycle", ":/icons/archive.svg");
    addLeaf(g3, "健康度看板", "forget/health", ":/icons/activity.svg");
    addLeaf(g3, "遗忘历史", "forget/history", ":/icons/history.svg");
    addLeaf(g3, "遗忘设置", "forget/settings", ":/icons/settings.svg");

    QTreeWidgetItem *g5 = addGroup("系统");
    addLeaf(g5, "安全总览", "safety/overview", ":/icons/shield.svg");
    addLeaf(g5, "用户规则", "safety/user-rules", ":/icons/shield.svg");
    addLeaf(g5, "审计日志", "safety/audit", ":/icons/history.svg");
    addLeaf(g5, "隔离区", "safety/quarantine", ":/icons/shield.svg");
    addLeaf(g5, "后端状态", "settings/status", ":/icons/database.svg");
    addLeaf(g5, "LLM 服务", "settings/llm", ":/icons/settings.svg");
    addLeaf(g5, "参数查看", "settings/config", ":/icons/settings.svg");
    addLeaf(g5, "演示数据工具", "settings/demo", ":/icons/settings.svg");
}

void MainWindow::registerPage(const QString &key, const QString &group, const QString &title,
                              BasePage *page) {
    PageEntry e;
    e.page = page;
    e.group = group;
    e.title = title;
    m_pages.insert(key, e);
    m_stack->addWidget(page);

    // 旧页面原本普遍使用 0 边距，内容会紧贴窗口边缘。Dashboard 自带滚动容器，
    // 其余页面在应用外壳层统一获得安全边距与区块间距。
    if (key != "dashboard" && page->layout()) {
        page->layout()->setContentsMargins(24, 20, 24, 24);
        if (page->layout()->spacing() < 12) page->layout()->setSpacing(12);
    }
}

void MainWindow::navigateTo(const QString &key) {
    if (!m_pages.contains(key)) return;
    if (key == m_currentKey) return;
    const PageEntry &e = m_pages.value(key);
    m_currentKey = key;
    m_stack->setCurrentWidget(e.page);
    updateBreadcrumb(e.group, e.title);
    const auto items = m_nav->findItems(QString(), Qt::MatchContains | Qt::MatchRecursive);
    for (auto *item : items) {
        if (item->data(0, Qt::UserRole).toString() == key) {
            m_nav->blockSignals(true);
            m_nav->setCurrentItem(item);
            m_nav->scrollToItem(item, QAbstractItemView::EnsureVisible);
            m_nav->blockSignals(false);
            break;
        }
    }
    e.page->refresh();
}

void MainWindow::updateBreadcrumb(const QString &group, const QString &title) {
    m_breadcrumb->setText(group.isEmpty() ? title : group + " / " + title);
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
            m_statusDot->setProperty("online", true);
            m_statusText->setText("后端已连接");
        } else {
            m_statusDot->setProperty("online", false);
            m_statusText->setText("后端离线");
        }
        m_statusDot->style()->unpolish(m_statusDot);
        m_statusDot->style()->polish(m_statusDot);
    });
}

void MainWindow::refreshCurrentPage() {
    if (m_pages.contains(m_currentKey)) {
        m_pages.value(m_currentKey).page->refresh();
    }
}

void MainWindow::polishPopupControls(QWidget *root) {
    const auto combos = root->findChildren<QComboBox *>();
    for (auto *combo : combos) {
        auto *view = new QListView(combo);
        view->setObjectName("comboPopup");
        view->setFrameShape(QFrame::NoFrame);
        view->setSpacing(2);
        view->setUniformItemSizes(true);
        view->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        combo->setView(view);

        QWidget *popup = view->window();
        popup->setWindowFlag(Qt::NoDropShadowWindowHint, true);
        // Windows 上透明的 QComboBoxPrivateContainer 不会按 QSS 圆角真正裁剪，
        // 四角会被 DWM 合成为黑色。使用不透明白色窗口底，再由内部列表绘制圆角。
        popup->setAttribute(Qt::WA_TranslucentBackground, false);
        popup->setAutoFillBackground(true);
        QPalette palette = popup->palette();
        palette.setColor(QPalette::Window, QColor("#FFFFFF"));
        palette.setColor(QPalette::Base, QColor("#FFFFFF"));
        popup->setPalette(palette);
    }
}

void MainWindow::closeEvent(QCloseEvent *e) {
    QMainWindow::closeEvent(e);
}
