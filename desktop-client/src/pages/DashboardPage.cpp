#include "DashboardPage.h"

#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QScrollArea>
#include <QTableWidget>
#include <QVBoxLayout>

#include <QtCharts/QBarCategoryAxis>
#include <QtCharts/QBarSeries>
#include <QtCharts/QBarSet>
#include <QtCharts/QChart>
#include <QtCharts/QChartView>
#include <QtCharts/QPieSeries>
#include <QtCharts/QValueAxis>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/PageHeader.h"
#include "../widgets/StatCard.h"
#include "../widgets/StatusTag.h"

DashboardPage::DashboardPage(QWidget *parent) : BasePage(parent) {
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto *body = new QWidget(scroll);
    auto *lay = new QVBoxLayout(body);
    lay->setContentsMargins(20, 20, 20, 20);
    lay->setSpacing(16);
    scroll->setWidget(body);

    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->addWidget(scroll);

    auto *header = new PageHeader(body);
    header->setTitle("总览");
    header->setSubtitle("3 秒看懂系统状态 · 演示首屏");
    lay->addWidget(header);

    // ---- 统计卡片行 ----
    m_statGrid = new QGridLayout(body);
    m_statGrid->setHorizontalSpacing(12);
    m_statGrid->setVerticalSpacing(12);

    struct StatSpec {
        const char *icon;
        const char *caption;
        const char *navKey;
    };
    const StatSpec specs[6] = {
        {"📚", "记忆总数", ""},
        {"💙", "偏好记忆", "mem/preference"},
        {"💜", "知识记忆", "mem/knowledge"},
        {"💠", "事实记忆", "mem/fact"},
        {"⚠️", "待处理冲突", "conflicts"},
        {"🕸️", "抽取死信", "forget/pending"},
    };
    for (int i = 0; i < 6; ++i) {
        auto *card = new StatCard(body);
        card->setIconText(QString::fromUtf8(specs[i].icon));
        card->setCaption(QString::fromUtf8(specs[i].caption));
        card->setNumber("–");
        if (QString(specs[i].navKey).isEmpty()) {
            card->setClickable(false);
        } else {
            card->setClickable(true);
            const QString key = QString::fromUtf8(specs[i].navKey);
            connect(card, &StatCard::clicked, this, [key]() {
                AppContext::instance()->navigate(key);
            });
        }
        m_statGrid->addWidget(card, 0, i);
        m_statCards.append(card);
    }
    lay->addLayout(m_statGrid);

    // ---- 图表行 ----
    auto *chartRow = new QHBoxLayout(body);
    chartRow->setSpacing(16);

    auto *pieCard = new QFrame(body);
    pieCard->setObjectName("card");
    auto *pieLay = new QVBoxLayout(pieCard);
    auto *pieTitle = new QLabel("记忆类型占比", pieCard);
    pieTitle->setObjectName("cardTitle");
    pieLay->addWidget(pieTitle);
    m_pieSeries = new QtCharts::QPieSeries();
    m_pieSeries->setHoleSize(0.55);
    auto *pieChart = new QtCharts::QChart();
    pieChart->addSeries(m_pieSeries);
    pieChart->legend()->setAlignment(Qt::AlignBottom);
    pieChart->setBackgroundVisible(false);
    m_pieView = new QtCharts::QChartView(pieChart);
    m_pieView->setRenderHint(QPainter::Antialiasing);
    m_pieView->setMinimumHeight(260);
    pieLay->addWidget(m_pieView, 1);
    chartRow->addWidget(pieCard, 1);

    auto *barCard = new QFrame(body);
    barCard->setObjectName("card");
    auto *barLay = new QVBoxLayout(barCard);
    auto *barTitle = new QLabel("记忆状态分布", barCard);
    barTitle->setObjectName("cardTitle");
    barLay->addWidget(barTitle);
    m_barSeries = new QtCharts::QBarSeries();
    auto *barChart = new QtCharts::QChart();
    barChart->addSeries(m_barSeries);
    barChart->setBackgroundVisible(false);
    auto *axisX = new QtCharts::QBarCategoryAxis();
    axisX->append({"有效", "归档", "待审", "删除"});
    barChart->addAxis(axisX, Qt::AlignBottom);
    m_barSeries->attachAxis(axisX);
    auto *axisY = new QtCharts::QValueAxis();
    axisY->setRange(0, 100);
    barChart->addAxis(axisY, Qt::AlignLeft);
    m_barSeries->attachAxis(axisY);
    m_barView = new QtCharts::QChartView(barChart);
    m_barView->setRenderHint(QPainter::Antialiasing);
    m_barView->setMinimumHeight(260);
    barLay->addWidget(m_barView, 1);
    chartRow->addWidget(barCard, 1);
    lay->addLayout(chartRow);

    // ---- 底部：最近事件 + 系统状态 ----
    auto *bottom = new QHBoxLayout(body);
    bottom->setSpacing(16);

    auto *eventCard = new QFrame(body);
    eventCard->setObjectName("card");
    auto *eventLay = new QVBoxLayout(eventCard);
    auto *eventTitle = new QLabel("最近事件流", eventCard);
    eventTitle->setObjectName("cardTitle");
    eventLay->addWidget(eventTitle);
    m_eventTable = new QTableWidget(0, 4, eventCard);
    m_eventTable->setHorizontalHeaderLabels({"类型", "场景", "质量", "时间"});
    m_eventTable->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    m_eventTable->verticalHeader()->setVisible(false);
    m_eventTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_eventTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_eventTable->setAlternatingRowColors(true);
    eventLay->addWidget(m_eventTable, 1);
    bottom->addWidget(eventCard, 3);

    auto *statusCard = new QFrame(body);
    statusCard->setObjectName("card");
    auto *statusLay = new QVBoxLayout(statusCard);
    auto *statusTitle = new QLabel("系统状态", statusCard);
    statusTitle->setObjectName("cardTitle");
    statusLay->addWidget(statusTitle);
    m_statusBody = new QLabel(statusCard);
    m_statusBody->setWordWrap(true);
    m_statusBody->setTextFormat(Qt::RichText);
    m_statusBody->setStyleSheet("color:#4B5563;font-size:12px;line-height:1.6;");
    statusLay->addWidget(m_statusBody);
    statusLay->addStretch();
    bottom->addWidget(statusCard, 2);
    lay->addLayout(bottom);
}

void DashboardPage::refresh() {
    loadStats();
}

void DashboardPage::loadStats() {
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();

    // 三类记忆计数
    const api::Result rPref = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/preferences", {{"user_id", uid}, {"status", "active"}}));
    const api::Result rKnow = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge", {{"user_id", uid}}));
    const api::Result rFact = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "active"}}));

    const int nPref = rPref.jsonArray().size();
    const int nKnow = rKnow.jsonArray().size();
    const int nFact = rFact.jsonArray().size();
    const int total = nPref + nKnow + nFact;

    // 冲突 / 死信
    const api::Result rConf = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/conflicts", {{"user_id", uid}, {"status", "pending"}}));
    const int nConf = rConf.jsonArray().size();

    const api::Result rDead = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/extraction/tasks", {{"user_id", uid}, {"status", "dead_letter"}}));
    const int nDead = rDead.jsonArray().size();

    // 事件总数（来自 health）
    int eventCount = 0;
    const api::Result rHealth = api->get("/api/memory/health");
    if (rHealth.hasJsonObject()) {
        eventCount = j::integer(rHealth.jsonObject(), "event_count", eventCount);
    }

    m_statCards[0]->setNumber(QString::number(total));
    m_statCards[1]->setNumber(QString::number(nPref));
    m_statCards[2]->setNumber(QString::number(nKnow));
    m_statCards[3]->setNumber(QString::number(nFact));
    m_statCards[4]->setNumber(QString::number(nConf));
    m_statCards[5]->setNumber(QString::number(nDead));
    m_statCards[0]->setCaption(QString("事件总数 %1").arg(eventCount));

    loadCharts(nPref, nKnow, nFact);
    loadRecentEvents();
    loadSystemStatus();
}

void DashboardPage::loadCharts(int pref, int know, int fact) {
    // 环图
    m_pieSeries->clear();
    const int total = pref + know + fact;
    auto addSlice = [this](int v, const QString &label, const QString &color) {
        if (v <= 0) return;
        auto *slice = m_pieSeries->append(label, v);
        slice->setColor(QColor(color));
    };
    addSlice(pref, QString("偏好 %1").arg(pref), "#3B82F6");
    addSlice(know, QString("知识 %1").arg(know), "#8B5CF6");
    addSlice(fact, QString("事实 %1").arg(fact), "#06B6D4");
    if (total == 0) {
        auto *slice = m_pieSeries->append("暂无数据", 1);
        slice->setColor(QColor("#E5E7EB"));
        slice->setLabelVisible(true);
    } else {
        for (auto *s : m_pieSeries->slices()) s->setLabelVisible(true);
    }

    // 柱图：按状态统计各类别数量
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    int prefA = 0, prefAr = 0, prefP = 0, prefD = 0;
    int knowA = 0, knowAr = 0, knowP = 0, knowD = 0;
    int factA = 0, factAr = 0, factP = 0, factD = 0;

    // 用三个状态请求分别计数（避免后端不支持 status=all）
    auto countStatus = [&](const QString &endpoint, const QString &status) {
        const api::Result r = api->get(api::ApiClient::urlWithQuery(
            endpoint, {{"user_id", uid}, {"status", status}}));
        return r.jsonArray().size();
    };
    prefA = countStatus("/api/memory/preferences", "active");
    prefAr = countStatus("/api/memory/preferences", "archived");
    prefP = countStatus("/api/memory/preferences", "pending");
    prefD = countStatus("/api/memory/preferences", "deleted");

    knowA = countStatus("/api/memory/knowledge", "active");
    knowAr = countStatus("/api/memory/knowledge", "archived");
    knowP = countStatus("/api/memory/knowledge", "pending");
    knowD = countStatus("/api/memory/knowledge", "deleted");

    const api::Result fA = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "active"}}));
    const api::Result fAr = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "archived"}}));
    const api::Result fP = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "pending"}}));
    const api::Result fD = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "deleted"}}));
    factA = fA.jsonArray().size();
    factAr = fAr.jsonArray().size();
    factP = fP.jsonArray().size();
    factD = fD.jsonArray().size();

    m_barSeries->clear();
    auto *setPref = new QtCharts::QBarSet("偏好");
    setPref->setColor(QColor("#3B82F6"));
    *setPref << prefA << prefAr << prefP << prefD;
    auto *setKnow = new QtCharts::QBarSet("知识");
    setKnow->setColor(QColor("#8B5CF6"));
    *setKnow << knowA << knowAr << knowP << knowD;
    auto *setFact = new QtCharts::QBarSet("事实");
    setFact->setColor(QColor("#06B6D4"));
    *setFact << factA << factAr << factP << factD;
    m_barSeries->append(setPref);
    m_barSeries->append(setKnow);
    m_barSeries->append(setFact);
}

void DashboardPage::loadRecentEvents() {
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/events", {{"user_id", uid}, {"limit", "10"}, {"offset", "0"}}));

    m_eventTable->setRowCount(0);
    const QJsonArray items = r.jsonObject().value("items").toArray();
    for (const QJsonValue &v : items) {
        const QJsonObject e = v.toObject();
        const int row = m_eventTable->rowCount();
        m_eventTable->insertRow(row);
        m_eventTable->setItem(row, 0, new QTableWidgetItem(j::str(e, "event_type")));
        m_eventTable->setItem(row, 1, new QTableWidgetItem(j::str(e, "scene")));
        const double q = j::num(j::obj(e, "quality"), "score", 0.0);
        m_eventTable->setItem(row, 2, new QTableWidgetItem(j::pct(q, 0)));
        m_eventTable->setItem(row, 3, new QTableWidgetItem(j::timeAgo(j::str(e, "occurred_at"))));
    }
}

void DashboardPage::loadSystemStatus() {
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->get("/api/memory/system/status");
    if (!r.hasJsonObject()) {
        m_statusBody->setText("<span style='color:#DC2626'>后端离线或状态接口不可用</span>");
        return;
    }
    const QJsonObject s = r.jsonObject();
    const QJsonObject storage = j::obj(s, "storage");
    const QJsonObject embed = j::obj(s, "embedding");
    const QJsonObject llm = j::obj(s, "llm");
    const QJsonObject vec = j::obj(s, "vector_engine");
    const QJsonObject retr = j::obj(s, "retrieval");
    const QJsonObject safety = j::obj(s, "safety");

    QString html;
    html += QString("<b>服务</b> %1 v%2<br/>")
                .arg(j::str(s, "service"), j::str(s, "version"));
    html += QString("<b>模式</b> %1<br/>").arg(j::str(s, "runtime_mode"));
    html += QString("<b>数据库</b> %1<br/>").arg(j::str(storage, "db_path"));
    html += QString("<b>事件 / 偏好 / 知识 / 事实</b> %1 / %2 / %3 / %4<br/>")
                .arg(j::integer(storage, "event_count"))
                .arg(j::integer(storage, "preference_count"))
                .arg(j::integer(storage, "knowledge_count"))
                .arg(j::integer(storage, "fact_count"));
    html += QString("<b>向量引擎</b> %1 · %2<br/>")
                .arg(j::str(vec, "provider"), j::str(vec, "collection"));
    html += QString("<b>Embedding</b> %1 · dim %2<br/>")
                .arg(j::str(embed, "provider"), QString::number(j::integer(embed, "dimension")));
    html += QString("<b>LLM</b> %1 · %2<br/>").arg(j::str(llm, "provider"), j::str(llm, "model"));
    html += QString("<b>检索权重</b> 向量 %1 / 关键词 %2 / 元数据 %3<br/>")
                .arg(j::num(j::obj(retr, "weights"), "vector", 0.0), 0, 'f', 2)
                .arg(j::num(j::obj(retr, "weights"), "keyword", 0.0), 0, 'f', 2)
                .arg(j::num(j::obj(retr, "weights"), "metadata", 0.0), 0, 'f', 2);
    html += QString("<b>安全门禁</b> %1 · 审计 %2 · 隔离区 %3")
                .arg(j::boolean(safety, "gate_available") ? "可用" : "不可用")
                .arg(j::boolean(safety, "audit_enabled") ? "开" : "关")
                .arg(j::boolean(safety, "quarantine_enabled") ? "开" : "关");
    m_statusBody->setText(html);
}
