#include "DashboardPage.h"

#include <QDateTime>
#include <QEvent>
#include <QFileInfo>
#include <QFrame>
#include <QGridLayout>
#include <QHeaderView>
#include <QIcon>
#include <QLabel>
#include <QLinearGradient>
#include <QPainter>
#include <QProcess>
#include <QTimer>
#include <QPushButton>
#include <QScrollArea>
#include <QStyle>
#include <QTableWidget>
#include <QVBoxLayout>
#include <QGridLayout>
#include <QKeyEvent>
#include <QResizeEvent>
#include <QStandardPaths>
#include <QtMath>

#include <QtCharts/QBarCategoryAxis>
#include <QtCharts/QBarSet>
#include <QtCharts/QChart>
#include <QtCharts/QChartView>
#include <QtCharts/QPieSeries>
#include <QtCharts/QPieSlice>
#include <QtCharts/QStackedBarSeries>
#include <QtCharts/QValueAxis>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"
#include "../widgets/StatCard.h"

namespace {

struct KnowledgeSlice {
    const char *name;     // 图表分类名
    const QString keyword; // 用于知识卡片细信息的标记名
    int *counter;         // 指向成员计数
    const char *color;     // 十六进制颜色
};

const QColor kPrefColor("#4B7FE0");
const QColor kWorkflowColor("#7F6BDC");
const QColor kCaseColor("#3FB6B2");
const QColor kTemplateColor("#E8A23C");
const QColor kFactColor("#D15B7E");

QString installedHelper(const QString &name) {
    const QString found = QStandardPaths::findExecutable(name);
    if (!found.isEmpty()) return found;
    const QString systemPath = QStringLiteral("/usr/bin/") + name;
    return QFileInfo::exists(systemPath) ? systemPath : QString();
}

QString eventTypeLabel(const QString &raw) {
    if (raw == "agent_response") return "工具轨迹";
    if (raw == "agent_summary") return "会话总结";
    if (raw == "memory_write") return "记忆写入";
    if (raw == "user_behavior") return "用户行为";
    if (raw.startsWith("knowledge")) return "知识";
    if (raw.startsWith("preference")) return "偏好";
    return raw.isEmpty() ? "记忆事件" : raw;
}

QString eventTypeTone(const QString &raw) {
    if (raw == "agent_response" || raw.startsWith("knowledge")) return "violet";
    if (raw == "agent_summary") return "teal";
    if (raw == "memory_write" || raw.startsWith("preference")) return "blue";
    if (raw == "user_behavior") return "gray";
    return "rose";
}

QFrame *makeCard(QWidget *parent, const QString &title, const QString &subtitle,
                 QVBoxLayout **content) {
    auto *card = new QFrame(parent);
    card->setObjectName("dashboardCard");
    auto *layout = new QVBoxLayout(card);
    layout->setContentsMargins(18, 16, 18, 16);
    layout->setSpacing(10);
    auto *heading = new QLabel(title, card);
    heading->setObjectName("sectionTitle");
    layout->addWidget(heading);
    if (!subtitle.isEmpty()) {
        auto *hint = new QLabel(subtitle, card);
        hint->setObjectName("sectionHint");
        layout->addWidget(hint);
    }
    *content = layout;
    return card;
}

QFrame *makeTask(QWidget *parent, const QIcon &icon, const QString &title,
                 const QString &hint, QLabel **count) {
    auto *row = new QFrame(parent);
    row->setObjectName("taskItem");
    auto *layout = new QHBoxLayout(row);
    layout->setContentsMargins(12, 10, 12, 10);
    layout->setSpacing(10);
    auto *iconLabel = new QLabel(row);
    iconLabel->setObjectName("taskIcon");
    iconLabel->setPixmap(icon.pixmap(18, 18));
    iconLabel->setAlignment(Qt::AlignCenter);
    iconLabel->setFixedSize(34, 34);
    auto *texts = new QVBoxLayout();
    texts->setSpacing(1);
    auto *titleLabel = new QLabel(title, row);
    titleLabel->setObjectName("taskTitle");
    auto *hintLabel = new QLabel(hint, row);
    hintLabel->setObjectName("taskHint");
    texts->addWidget(titleLabel);
    texts->addWidget(hintLabel);
    *count = new QLabel("—", row);
    (*count)->setObjectName("taskCount");
    layout->addWidget(iconLabel);
    layout->addLayout(texts, 1);
    layout->addWidget(*count);
    return row;
}
}

DashboardPage::DashboardPage(QWidget *parent) : BasePage(parent) {
    setObjectName("dashboardPage");
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);

    auto *scroll = new QScrollArea(this);
    scroll->setObjectName("dashboardScroll");
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto *body = new QWidget(scroll);
    body->setObjectName("dashboardBody");
    auto *layout = new QVBoxLayout(body);
    layout->setContentsMargins(24, 22, 24, 24);
    layout->setSpacing(16);
    scroll->setWidget(body);
    outer->addWidget(scroll);

    auto *header = new PageHeader(body);
    header->setTitle("记忆系统状态");
    header->setSubtitle("偏好记忆与知识记忆（工作流 · 案例 · 模板 · 事实）的实时概况");
    m_updateTime = new QLabel("尚未更新", header);
    m_updateTime->setObjectName("updateTime");
    auto *search = new QPushButton(QIcon(":/icons/search.svg"), "检索测试", header);
    search->setObjectName("secondaryButton");
    auto *refresh = new QPushButton(QIcon(":/icons/refresh.svg"), "刷新数据", header);
    refresh->setObjectName("primaryButton");
    m_configureButton = new QPushButton("一键配置", header);
    m_configureButton->setObjectName("secondaryButton");
    m_openAgentButton = new QPushButton("打开 Agent", header);
    m_openAgentButton->setObjectName("agentButton");
#ifdef Q_OS_WIN
    m_configureButton->setEnabled(false);
    m_configureButton->setToolTip("当前平台不支持：一键配置仅适用于 Linux");
    m_openAgentButton->setEnabled(false);
    m_openAgentButton->setToolTip("当前平台不支持 Agent 启动");
#else
    m_configureButton->setToolTip("为当前 Linux 用户安装或修复 OpenCode 插件配置");
    m_openAgentButton->setToolTip("在主目录打开系统终端并启动 OpenCode");
#endif
    header->actionLayout()->addWidget(m_updateTime);
    header->actionLayout()->addWidget(search);
    header->actionLayout()->addWidget(refresh);
    header->actionLayout()->addWidget(m_configureButton);
    header->actionLayout()->addWidget(m_openAgentButton);
    connect(search, &QPushButton::clicked, this,
            []() { AppContext::instance()->navigate("search"); });
    connect(refresh, &QPushButton::clicked, this, &DashboardPage::refresh);
    connect(m_configureButton, &QPushButton::clicked, this, &DashboardPage::configureOpenCode);
    connect(m_openAgentButton, &QPushButton::clicked, this, &DashboardPage::openAgent);
    layout->addWidget(header);

    m_banner = new QLabel(body);
    m_banner->setObjectName("inlineBanner");
    m_banner->setWordWrap(true);
    m_banner->hide();
    layout->addWidget(m_banner);

    auto *stats = new QGridLayout();
    m_statsLayout = stats;
    stats->setHorizontalSpacing(14);
    stats->setVerticalSpacing(14);
    const struct { const char *title; const char *icon; const char *key; } specs[] = {
        {"记忆总数", ":/icons/database.svg", ""},
        {"偏好记忆", ":/icons/preference.svg", "mem/preference"},
        {"知识记忆", ":/icons/knowledge.svg", "mem/knowledge"},
        {"事实知识", ":/icons/fact.svg", "mem/knowledge"}
    };
    for (int i = 0; i < 4; ++i) {
        auto *card = new StatCard(body);
        card->setCaption(QString::fromUtf8(specs[i].title));
        card->setIcon(QIcon(specs[i].icon));
        card->setNumber("—");
        const QString key = QString::fromUtf8(specs[i].key);
        card->setClickable(!key.isEmpty());
        if (!key.isEmpty()) connect(card, &StatCard::clicked, this,
            [key]() { AppContext::instance()->navigate(key); });
        stats->addWidget(card, 0, i);
        stats->setColumnStretch(i, 1);
        m_statCards.append(card);
    }
    m_statCards[2]->setHint("等待知识数据…");
    m_statCards[3]->setHint("等待知识数据…");
    layout->addLayout(stats);

    auto *chartRow = new QHBoxLayout();
    m_chartLayout = chartRow;
    chartRow->setSpacing(16);
    QVBoxLayout *barLayout = nullptr;
    auto *barCard = makeCard(body, "记忆构成对比", "偏好记忆与知识记忆各子类型的绝对数量", &barLayout);
    m_barCard = barCard;
    m_barSeries = new QtCharts::QStackedBarSeries();
    m_barSeries->setBarWidth(0.62);
    m_barSeries->setLabelsVisible(true);
    m_barSeries->setLabelsPosition(QtCharts::QAbstractBarSeries::LabelsCenter);
    auto *barChart = new QtCharts::QChart();
    barChart->addSeries(m_barSeries);
    barChart->legend()->hide();
    barChart->setBackgroundVisible(false);
    barChart->setMargins(QMargins(4, 4, 4, 4));
    barChart->setAnimationOptions(QtCharts::QChart::SeriesAnimations);
    barChart->setAnimationDuration(450);
    auto *axisX = new QtCharts::QBarCategoryAxis();
    axisX->append({"偏好", "工作流", "案例", "模板", "事实"});
    barChart->addAxis(axisX, Qt::AlignBottom);
    m_barSeries->attachAxis(axisX);
    m_barAxisY = new QtCharts::QValueAxis();
    m_barAxisY->setRange(0, 4);
    m_barAxisY->setTickCount(5);
    m_barAxisY->setLabelFormat("%d");
    m_barAxisY->setGridLineColor(QColor("#E8EBF0"));
    barChart->addAxis(m_barAxisY, Qt::AlignLeft);
    m_barSeries->attachAxis(m_barAxisY);
    auto *barView = new QtCharts::QChartView(barChart, barCard);
    barView->setRenderHint(QPainter::Antialiasing);
    barView->setMinimumHeight(245);
    barLayout->addWidget(barView, 1);
    chartRow->addWidget(barCard, 3);

    QVBoxLayout *pieLayout = nullptr;
    auto *pieCard = makeCard(body, "记忆类型分布", "当前有效记忆构成（事实已并入知识）", &pieLayout);
    m_pieCard = pieCard;
    m_pieSeries = new QtCharts::QPieSeries();
    m_pieSeries->setHoleSize(0.58);
    auto *pieChart = new QtCharts::QChart();
    pieChart->addSeries(m_pieSeries);
    pieChart->legend()->setAlignment(Qt::AlignBottom);
    pieChart->legend()->setLabelColor(QColor("#526174"));
    pieChart->setBackgroundVisible(false);
    pieChart->setMargins(QMargins(2, 2, 2, 2));
    pieChart->setAnimationOptions(QtCharts::QChart::SeriesAnimations);
    pieChart->setAnimationDuration(450);
    auto *pieContainer = new QWidget(pieCard);
    auto *pieOverlay = new QGridLayout(pieContainer);
    pieOverlay->setContentsMargins(0, 0, 0, 0);
    auto *pieView = new QtCharts::QChartView(pieChart, pieContainer);
    pieView->setRenderHint(QPainter::Antialiasing);
    pieView->setMinimumHeight(245);
    pieOverlay->addWidget(pieView, 0, 0);
    m_chartEmpty = new QLabel("正在读取记忆数据…", pieContainer);
    m_chartEmpty->setObjectName("chartEmpty");
    m_chartEmpty->setAlignment(Qt::AlignCenter);
    pieOverlay->addWidget(m_chartEmpty, 0, 0, Qt::AlignCenter);
    m_pieCenter = new QLabel("—\n总记忆", pieContainer);
    m_pieCenter->setObjectName("pieCenter");
    m_pieCenter->setAlignment(Qt::AlignCenter);
    pieOverlay->addWidget(m_pieCenter, 0, 0, Qt::AlignCenter);
    pieLayout->addWidget(pieContainer, 1);
    chartRow->addWidget(pieCard, 2);
    layout->addLayout(chartRow);

    auto *bottom = new QHBoxLayout();
    m_bottomLayout = bottom;
    bottom->setSpacing(16);
    QVBoxLayout *activityLayout = nullptr;
    auto *activityCard = makeCard(body, "最近活动", "系统中的最新变化", &activityLayout);
    m_activityCard = activityCard;
    m_activityContainer = new QWidget(activityCard);
    m_activityLayout = new QVBoxLayout(m_activityContainer);
    m_activityLayout->setContentsMargins(0, 0, 0, 0);
    m_activityLayout->setSpacing(2);
    m_activityState = new PageStateView(m_activityContainer);
    m_activityState->setState(PageState::Loading, "正在加载活动", "正在读取最近变化…");
    m_activityLayout->addWidget(m_activityState);
    activityLayout->addWidget(m_activityContainer);
    bottom->addWidget(activityCard, 3);

    QVBoxLayout *taskLayout = nullptr;
    auto *taskCard = makeCard(body, "待处理事项", "需要你的关注", &taskLayout);
    m_taskCard = taskCard;
    auto *conflict = makeTask(taskCard, QIcon(":/icons/conflict.svg"), "记忆冲突",
                              "进入冲突中心检查", &m_conflictCount);
    auto *dead = makeTask(taskCard, QIcon(":/icons/history.svg"), "抽取死信",
                          "进入待审查队列处理", &m_deadLetterCount);
    conflict->setCursor(Qt::PointingHandCursor);
    conflict->setFocusPolicy(Qt::StrongFocus);
    conflict->setAccessibleName("打开冲突中心");
    dead->setAccessibleName("抽取死信数量");
    taskLayout->addWidget(conflict);
    taskLayout->addWidget(dead);
    taskLayout->addStretch();
    conflict->installEventFilter(this);
    conflict->setProperty("navKey", "conflicts");
    bottom->addWidget(taskCard, 2);
    layout->addLayout(bottom);
}

void DashboardPage::beginLoading() {
    m_pendingRequests = 10;
    m_successfulRequests = 0;
    m_pref = m_know = -1;
    m_knowWorkflow = m_knowCase = m_knowTemplate = m_knowFact = -1;
    m_conflicts = m_deadLetters = -1;
    for (auto *card : m_statCards) card->setLoading(true);
    m_statCards[2]->setHint("等待知识数据…");
    m_statCards[3]->setHint("等待知识数据…");
    m_activityState->setState(PageState::Loading, "正在加载活动", "正在读取最近变化…");
    m_activityState->clearAction();
    m_conflictCount->setText("—");
    m_deadLetterCount->setText("—");
    m_chartEmpty->setText("正在读取记忆数据…");
    m_chartEmpty->show();
    m_pieCenter->setText("—\n总记忆");
    m_pieCenter->hide();
    setBanner(QString(), "info");
}

void DashboardPage::refresh() {
    const int generation = ++m_generation;
    beginLoading();
    const QString uid = AppContext::instance()->userId();
    auto *api = AppContext::instance()->api();
    auto query = [uid](const QString &path, const QList<QPair<QString, QString>> &extra = {}) {
        QList<QPair<QString, QString>> params{{"user_id", uid}};
        params.append(extra);
        return api::ApiClient::urlWithQuery(path, params);
    };

    api->getAsync(query("/api/memory/preferences", {{"status", "active"}}),
        [this, generation](const api::Result &r) { if (generation != m_generation) return;
            if (r.ok && r.hasJsonArray()) { m_pref = r.jsonArray().size(); m_statCards[1]->setLoading(false); m_statCards[1]->setNumber(QString::number(m_pref)); }
            else m_statCards[1]->setError(r.errorMessage.isEmpty() ? "偏好记忆加载失败" : r.errorMessage);
            updateMemoryVisuals(); finishRequest(r.ok); }, this);
    api->getAsync(query("/api/memory/knowledge", {{"status", "active"}}),
        [this, generation](const api::Result &r) { if (generation != m_generation) return;
            if (r.ok && r.hasJsonArray()) { m_know = r.jsonArray().size(); m_statCards[2]->setLoading(false); m_statCards[2]->setNumber(QString::number(m_know)); }
            else m_statCards[2]->setError(r.errorMessage.isEmpty() ? "知识记忆加载失败" : r.errorMessage);
            updateMemoryVisuals(); finishRequest(r.ok); }, this);
    const struct { const char *arg; int *target; } subtypes[] = {
        {"workflow", &m_knowWorkflow},
        {"case", &m_knowCase},
        {"template", &m_knowTemplate},
        {"fact", &m_knowFact},
    };
    for (const auto &sub : subtypes) {
        api->getAsync(query("/api/memory/knowledge", {{"status", "active"}, {"knowledge_type", QString::fromUtf8(sub.arg)}}),
            [this, generation, sub](const api::Result &r) { if (generation != m_generation) return;
                if (r.ok && r.hasJsonArray()) *sub.target = r.jsonArray().size();
                else *sub.target = -2;
                updateMemoryVisuals(); finishRequest(r.ok); }, this);
    }
    api->getAsync(query("/api/memory/conflicts", {{"status", "pending"}}),
        [this, generation](const api::Result &r) { if (generation != m_generation) return;
            if (r.ok && r.hasJsonArray()) m_conflicts = r.jsonArray().size(); else m_conflicts = -2; updateTasks(); finishRequest(r.ok); }, this);
    api->getAsync(query("/api/memory/extraction/tasks", {{"status", "dead_letter"}}),
        [this, generation](const api::Result &r) { if (generation != m_generation) return;
            if (r.ok && r.hasJsonArray()) m_deadLetters = r.jsonArray().size(); else m_deadLetters = -2; updateTasks(); finishRequest(r.ok); }, this);
    api->getAsync(query("/api/memory/events", {{"limit", "8"}, {"offset", "0"}}),
        [this, generation](const api::Result &r) { if (generation != m_generation) return;
            updateActivity(r.jsonObject().value("items").toArray(), r.ok && r.hasJsonObject()); finishRequest(r.ok); }, this);
    api->getAsync("/api/health", [this, generation](const api::Result &r) {
        if (generation != m_generation) return; finishRequest(r.ok); }, this);
}

void DashboardPage::resizeEvent(QResizeEvent *event) {
    BasePage::resizeEvent(event);
    const bool narrow = width() < 1050;
    if (narrow == m_narrowLayout || !m_statsLayout || !m_chartLayout || !m_bottomLayout) return;
    m_narrowLayout = narrow;

    while (m_statsLayout->count() > 0) delete m_statsLayout->takeAt(0);
    for (int i = 0; i < m_statCards.size(); ++i) {
        m_statsLayout->addWidget(m_statCards[i], narrow ? i / 2 : 0, narrow ? i % 2 : i);
    }
    for (int i = 0; i < 4; ++i) m_statsLayout->setColumnStretch(i, narrow ? (i < 2 ? 1 : 0) : 1);

    m_chartLayout->removeWidget(m_barCard);
    m_chartLayout->removeWidget(m_pieCard);
    m_chartLayout->addWidget(m_barCard, narrow ? 1 : 3);
    m_chartLayout->addWidget(m_pieCard, narrow ? 1 : 2);

    m_bottomLayout->removeWidget(m_activityCard);
    m_bottomLayout->removeWidget(m_taskCard);
    m_bottomLayout->addWidget(m_activityCard, narrow ? 1 : 3);
    m_bottomLayout->addWidget(m_taskCard, narrow ? 1 : 2);
}

void DashboardPage::finishRequest(bool ok) {
    if (ok) ++m_successfulRequests;
    if (--m_pendingRequests > 0) return;
    m_updateTime->setText("更新于 " + QDateTime::currentDateTime().toString("HH:mm"));
    if (m_successfulRequests == 0) {
        setBanner("后端当前不可用。界面仍可正常浏览，你可以启动服务后点击“刷新数据”重试。", "offline");
    } else if (m_successfulRequests < 10) {
        setBanner("部分数据暂时无法获取，已保留成功加载的内容。", "warning");
    } else {
        setBanner(QString(), "info");
    }
    // 保证指标卡不卡在 loading：总数卡在全部请求结束后仍未落定（存在失败项）时进入终态。
    const bool partialMemory = m_pref < 0 || m_know < 0 ||
        m_knowWorkflow == -2 || m_knowCase == -2 || m_knowTemplate == -2 || m_knowFact == -2;
    if (m_statCards[0]->isLoading()) {
        if (m_successfulRequests == 0) {
            m_statCards[0]->setError("后端当前不可用");
        } else if (partialMemory) {
            m_statCards[0]->setError("部分数据不可用");
        }
    }
    if (m_successfulRequests == 0 && m_chartEmpty->isVisible()) {
        m_chartEmpty->setText("数据不可用");
        m_pieCenter->hide();
    } else if (partialMemory && m_chartEmpty->isVisible()) {
        m_chartEmpty->setText("部分数据不可用");
        m_pieCenter->hide();
    }
}

void DashboardPage::updateMemoryVisuals() {
    QStringList parts;
    const struct { int value; const char *name; } knownParts[] = {
        {m_knowWorkflow, "工作流"},
        {m_knowCase, "案例"},
        {m_knowTemplate, "模板"},
        {m_knowFact, "事实"},
    };
    bool allKnown = true;
    for (const auto &p : knownParts) {
        if (p.value < 0) { allKnown = false; continue; }
        parts << QString("%1 %2").arg(QString::fromUtf8(p.name)).arg(p.value);
    }
    if (!parts.isEmpty()) m_statCards[2]->setHint(parts.join(" · "));
    if (m_knowFact >= 0) {
        m_statCards[3]->setLoading(false);
        m_statCards[3]->setNumber(QString::number(m_knowFact));
    } else if (m_knowFact == -2) {
        m_statCards[3]->setLoading(false);
        m_statCards[3]->setHint("事实数据不可用");
    } else if (m_knowFact < 0) m_statCards[3]->setHint(allKnown ? "事实数据不可用" : "等待知识数据…");
    else if (m_know > 0) m_statCards[3]->setHint(QString("占知识记忆 %1%").arg(qRound(m_knowFact * 100.0 / m_know)));
    else if (m_know == 0) m_statCards[3]->setHint("暂无知识记忆");

    if (m_pref >= 0 && m_know >= 0 && m_knowWorkflow >= 0 && m_knowCase >= 0 &&
        m_knowTemplate >= 0 && m_knowFact >= 0) {
        const int total = m_pref + m_know;
        m_statCards[0]->setNumber(QString::number(total));
        m_statCards[0]->setLoading(false);
        m_pieCenter->setText(QString("%1\n总记忆").arg(total));
        m_barSeries->clear();
        const struct { int value; const QColor &color; const char *name; } barValues[] = {
            {m_pref, kPrefColor, "偏好"},
            {m_knowWorkflow, kWorkflowColor, "工作流"},
            {m_knowCase, kCaseColor, "案例"},
            {m_knowTemplate, kTemplateColor, "模板"},
            {m_knowFact, kFactColor, "事实"},
        };
        int largest = 0;
        for (int i = 0; i < 5; ++i) {
            auto *set = new QtCharts::QBarSet(QString::fromUtf8(barValues[i].name));
            set->setColor(barValues[i].color);
            for (int category = 0; category < 5; ++category)
                set->append(category == i ? barValues[i].value : 0);
            m_barSeries->append(set);
            largest = qMax(largest, barValues[i].value);
        }
        const int axisMax = qMax(4, static_cast<int>(qCeil(largest * 1.25)));
        m_barAxisY->setRange(0, axisMax);
        m_barAxisY->setTickCount(qMin(6, axisMax + 1));
        m_pieSeries->clear();
        if (total == 0) {
            auto *empty = m_pieSeries->append("暂无数据", 1);
            empty->setColor(QColor("#E8EBF0"));
            m_chartEmpty->setText("还没有有效记忆");
            m_chartEmpty->show();
            m_pieCenter->hide();
        } else {
            const struct { int value; const QColor &color; const char *name; } slices[] = {
                {m_pref, kPrefColor, "偏好"},
                {m_knowWorkflow, kWorkflowColor, "知识·工作流"},
                {m_knowCase, kCaseColor, "知识·案例"},
                {m_knowTemplate, kTemplateColor, "知识·模板"},
                {m_knowFact, kFactColor, "知识·事实"},
            };
            for (const auto &s : slices) {
                if (s.value <= 0) continue;
                auto *slice = m_pieSeries->append(
                    QString("%1 %2 (%3%)").arg(QString::fromUtf8(s.name)).arg(s.value)
                        .arg(qRound(s.value * 100.0 / total)), s.value);
                QLinearGradient gradient(0, 0, 1, 1);
                gradient.setCoordinateMode(QGradient::ObjectBoundingMode);
                gradient.setColorAt(0.0, s.color.lighter(118));
                gradient.setColorAt(1.0, s.color.darker(106));
                slice->setBrush(gradient);
                slice->setBorderColor(QColor("#FFFFFF"));
                slice->setBorderWidth(2);
                slice->setLabelColor(QColor("#334155"));
                connect(slice, &QtCharts::QPieSlice::hovered, slice,
                        [slice](bool hovered) {
                            slice->setExploded(hovered);
                            slice->setExplodeDistanceFactor(hovered ? 0.06 : 0.0);
                            slice->setLabelVisible(hovered);
                        });
            }
            m_chartEmpty->hide();
            m_pieCenter->show();
        }
    }
}

void DashboardPage::updateActivity(const QJsonArray &items, bool ok) {
    while (QLayoutItem *item = m_activityLayout->takeAt(0)) {
        if (QWidget *widget = item->widget()) {
            if (widget != m_activityState) widget->deleteLater();
        }
        delete item;
    }
    if (!ok || items.isEmpty()) {
        m_activityState->setState(ok ? PageState::Empty : PageState::Error,
                                   ok ? "暂无最近活动" : "最近活动加载失败",
                                   ok ? "后端尚未返回可展示的事件。" : "请稍后重试。");
        if (!ok) m_activityState->setAction("重试", [this]() { refresh(); });
        m_activityLayout->addWidget(m_activityState);
        return;
    }
    m_activityState->setState(PageState::Content, QString(), QString());
    for (const auto &value : items) {
        const QJsonObject event = value.toObject();
        auto *row = new QFrame(m_activityContainer);
        row->setObjectName("activityItem");
        auto *rowLayout = new QHBoxLayout(row);
        rowLayout->setContentsMargins(6, 6, 6, 6);
        auto *icon = new QLabel(row);
        icon->setPixmap(QIcon(":/icons/activity.svg").pixmap(16, 16));
        icon->setFixedSize(22, 22);
        icon->setAlignment(Qt::AlignCenter);
        const QString rawType = j::str(event, "event_type", "记忆事件");
        auto *tag = new QLabel(eventTypeLabel(rawType), row);
        tag->setObjectName("activityTag");
        tag->setProperty("tone", eventTypeTone(rawType));
        auto *texts = new QVBoxLayout();
        texts->setSpacing(1);
        const QString full = j::str(event, "text");
        auto *title = new QLabel(j::str(event, "scene", "未分类"), row);
        title->setObjectName("activityTitle");
        auto *detail = new QLabel(full, row);
        detail->setObjectName("activityDetail");
        detail->setToolTip(full);
        detail->setWordWrap(false);
        texts->addWidget(title);
        texts->addWidget(detail);
        auto *time = new QLabel(j::timeAgo(j::str(event, "occurred_at")), row);
        time->setObjectName("activityTime");
        time->setToolTip(j::fmtTime(j::str(event, "occurred_at")));
        rowLayout->addWidget(icon);
        rowLayout->addWidget(tag);
        rowLayout->addLayout(texts, 1);
        rowLayout->addWidget(time);
        m_activityLayout->addWidget(row);
    }
    m_activityLayout->addStretch();
}

void DashboardPage::updateTasks() {
    m_conflictCount->setText(m_conflicts == -2 ? "不可用" : (m_conflicts >= 0 ? QString::number(m_conflicts) : "—"));
    m_deadLetterCount->setText(m_deadLetters == -2 ? "不可用" : (m_deadLetters >= 0 ? QString::number(m_deadLetters) : "—"));
}

void DashboardPage::setBanner(const QString &text, const QString &state) {
    m_banner->setText(text);
    m_banner->setProperty("state", state);
    m_banner->setVisible(!text.isEmpty());
    m_banner->style()->unpolish(m_banner);
    m_banner->style()->polish(m_banner);
}

bool DashboardPage::eventFilter(QObject *watched, QEvent *event) {
    if (event->type() == QEvent::MouseButtonRelease) {
        const QString key = watched->property("navKey").toString();
        if (!key.isEmpty()) {
            AppContext::instance()->navigate(key);
            return true;
        }
    }
    if (event->type() == QEvent::KeyPress) {
        const auto *keyEvent = static_cast<QKeyEvent *>(event);
        const QString key = watched->property("navKey").toString();
        if (!key.isEmpty() && (keyEvent->key() == Qt::Key_Return || keyEvent->key() == Qt::Key_Space)) {
            AppContext::instance()->navigate(key);
            return true;
        }
    }
    return BasePage::eventFilter(watched, event);
}

void DashboardPage::configureOpenCode() {
#ifdef Q_OS_WIN
    setBanner("当前平台不支持 OpenCode 一键配置（Windows）。", "warning");
    return;
#endif
    if (m_configProcess) return;
    const QString helper = installedHelper(QStringLiteral("memoryhub-configure-opencode"));
    if (helper.isEmpty()) {
        setBanner("未找到 OpenCode 配置工具，请重新安装最新版 MemoryHub。", "warning");
        return;
    }
    m_configureButton->setEnabled(false);
    m_configureButton->setText("配置中…");
    setBanner("正在为当前 Linux 用户配置 OpenCode 插件…", "info");
    m_configProcess = new QProcess(this);
    QProcess *proc = m_configProcess;
    proc->setProcessChannelMode(QProcess::MergedChannels);
    connect(proc, &QProcess::errorOccurred, this, [this, proc](QProcess::ProcessError error) {
        setBanner(error == QProcess::FailedToStart
                     ? "OpenCode 配置失败：无法运行配置工具。"
                     : "OpenCode 配置失败：配置进程异常退出。",
                  "warning");
        if (m_configProcess == proc) m_configProcess = nullptr;
        proc->deleteLater();
        m_configureButton->setText("一键配置");
        m_configureButton->setEnabled(true);
    });
    connect(proc, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this, proc](int exitCode, QProcess::ExitStatus status) {
                const QString output = QString::fromUtf8(proc->readAll()).trimmed();
                const bool ok = status == QProcess::NormalExit && exitCode == 0;
                setBanner(ok ? "OpenCode 插件配置完成，可以直接打开 Agent。"
                             : QString("OpenCode 配置失败：%1").arg(output.isEmpty() ? "请查看系统日志" : output),
                          ok ? "success" : "warning");
                if (m_configProcess == proc) m_configProcess = nullptr;
                proc->deleteLater();
                m_configureButton->setText("一键配置");
                m_configureButton->setEnabled(true);
            });
    proc->start(helper, {QStringLiteral("--current-user")});
    QTimer::singleShot(10000, proc, [this]() {
        if (!m_configProcess || m_configProcess->state() == QProcess::NotRunning) return;
        m_configProcess->kill();
        setBanner("OpenCode 配置超时，已终止。", "warning");
        m_configureButton->setText("一键配置");
        m_configureButton->setEnabled(true);
    });
}

void DashboardPage::openAgent() {
#ifdef Q_OS_WIN
    setBanner("当前平台不支持 Agent 启动（Windows）。", "warning");
    return;
#endif
    const QString helper = installedHelper(QStringLiteral("memoryhub-open-agent"));
    if (helper.isEmpty()) {
        setBanner("未找到 Agent 启动工具，当前无法启动。", "warning");
        return;
    }
    if (m_agentProcess) return;
    m_openAgentButton->setEnabled(false);
    setBanner("正在启动 Agent…", "info");
    m_agentProcess = new QProcess(this);
    m_agentProcess->setProcessChannelMode(QProcess::MergedChannels);
    connect(m_agentProcess, &QProcess::errorOccurred, this, [this](QProcess::ProcessError) {
        setBanner("Agent 启动失败：无法运行启动工具。", "warning");
        m_openAgentButton->setEnabled(true);
        if (m_agentProcess) { m_agentProcess->deleteLater(); m_agentProcess = nullptr; }
    });
    connect(m_agentProcess, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this](int code, QProcess::ExitStatus status) {
        const bool ok = status == QProcess::NormalExit && code == 0;
        setBanner(ok ? "已在主目录打开系统终端并启动 OpenCode。"
                     : "Agent 启动失败：" + QString::fromUtf8(m_agentProcess->readAll()).trimmed(),
                  ok ? "success" : "warning");
        m_openAgentButton->setEnabled(true);
        m_agentProcess->deleteLater(); m_agentProcess = nullptr;
    });
    m_agentProcess->start(helper, QStringList{});
    QTimer::singleShot(10000, m_agentProcess, [this]() {
        if (!m_agentProcess || m_agentProcess->state() == QProcess::NotRunning) return;
        m_agentProcess->kill();
        setBanner("Agent 启动超时，请检查系统终端和 OpenCode。", "warning");
        m_openAgentButton->setEnabled(true);
    });
}
