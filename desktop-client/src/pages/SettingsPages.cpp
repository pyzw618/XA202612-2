// 系统设置 · 3 个子页完整实现

#include "SettingsPages.h"

#include <QFrame>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/PageHeader.h"
#include "../widgets/StatusTag.h"

// ============================================================
// P8.1 后端状态
// ============================================================
SettingsStatusPage::SettingsStatusPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("后端状态");
    header->setSubtitle("子系统状态灯 · 各表计数 · 连接信息");
    root->addWidget(header);

    m_table = new QTableWidget(this);
    m_table->setColumnCount(3);
    m_table->setHorizontalHeaderLabels({"组件", "状态", "详情"});
    m_table->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    root->addWidget(m_table, 1);

    auto *connCard = new QFrame(this);
    connCard->setObjectName("card");
    auto *cl = new QVBoxLayout(connCard);
    auto *ct = new QLabel("连接信息", connCard);
    ct->setObjectName("cardTitle");
    cl->addWidget(ct);
    m_connLabel = new QLabel(connCard);
    m_connLabel->setTextFormat(Qt::RichText);
    m_connLabel->setWordWrap(true);
    m_connLabel->setStyleSheet("color:#374151;font-size:13px;line-height:1.8;");
    cl->addWidget(m_connLabel);
    root->addWidget(connCard);
}

void SettingsStatusPage::refresh() { loadStatus(); }

void SettingsStatusPage::loadStatus() {
    const int generation = ++m_generation;
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync("/api/memory/system/status", [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    m_table->setRowCount(0);
    if (!r.hasJsonObject()) {
        m_table->insertRow(0);
        m_table->setItem(0, 0, new QTableWidgetItem("REST 服务"));
        auto *tag = new StatusTag();
        tag->setStatus("deleted");
        tag->setText("离线");
        m_table->setCellWidget(0, 1, tag);
        m_table->setItem(0, 2, new QTableWidgetItem("无法连接后端，请确认服务已启动"));
        return;
    }
    const QJsonObject s = r.jsonObject();
    auto addRow = [this](const QString &name, bool ok, const QString &detail) {
        const int row = m_table->rowCount();
        m_table->insertRow(row);
        m_table->setItem(row, 0, new QTableWidgetItem(name));
        auto *tag = new StatusTag();
        tag->setStatus(ok ? "active" : "deleted");
        tag->setText(ok ? "正常" : "异常");
        m_table->setCellWidget(row, 1, tag);
        m_table->setItem(row, 2, new QTableWidgetItem(detail));
    };

    const QJsonObject storage = j::obj(s, "storage");
    const QJsonObject embed = j::obj(s, "embedding");
    const QJsonObject llm = j::obj(s, "llm");
    const QJsonObject vec = j::obj(s, "vector_engine");
    const QJsonObject retr = j::obj(s, "retrieval");
    const QJsonObject safety = j::obj(s, "safety");

    addRow("REST 服务", true, j::str(s, "service") + " v" + j::str(s, "version") + " · " + j::str(s, "runtime_mode"));
    addRow("SQLite 存储", true, QString("事件 %1 · 偏好 %2 · 知识 %3 · 事实 %4 · 冲突 %5 · 遗忘 %6")
        .arg(j::integer(storage, "event_count")).arg(j::integer(storage, "preference_count"))
        .arg(j::integer(storage, "knowledge_count")).arg(j::integer(storage, "fact_count"))
        .arg(j::integer(storage, "conflict_count")).arg(j::integer(storage, "forget_count")));
    addRow("Embedding", true, QString("%1 · dim %2 · %3")
        .arg(j::str(embed, "provider")).arg(j::integer(embed, "dimension")).arg(j::str(embed, "model_name")));
    addRow("LLM", true, QString("%1 · %2").arg(j::str(llm, "provider"), j::str(llm, "model")));
    const bool vecConnected = vec.value("connected").isBool() ? j::boolean(vec, "connected") : true;
    addRow("向量引擎", vecConnected, QString("%1 · %2 · %3 条")
        .arg(j::str(vec, "provider"), j::str(vec, "collection"))
        .arg(j::integer(vec, "vector_count")));
    addRow("检索配置", true, QString("type=%1 · top_k=%2 · cache_ttl=%3s")
        .arg(j::str(retr, "type")).arg(j::integer(retr, "default_top_k"))
        .arg(j::integer(retr, "cache_ttl_seconds")));
    addRow("安全门禁", j::boolean(safety, "gate_available"),
           QString("规则集 %1 · 审计 %2 · 隔离区 %3")
               .arg(j::str(safety, "rule_set_version"))
               .arg(j::boolean(safety, "audit_enabled") ? "开" : "关")
               .arg(j::boolean(safety, "quarantine_enabled") ? "开" : "关"));

    api::ApiClient *configApi = AppContext::instance()->api();
    configApi->getAsync("/api/memory/system/config", [this, generation, storage](const api::Result &rCfg) {
        if (generation != m_generation) return;
        QString indexPath = "—";
        if (rCfg.hasJsonObject()) indexPath = j::str(j::obj(rCfg.jsonObject(), "storage"), "vector_index_path", "—");
        m_connLabel->setText(QString("<b>API Base URL</b> %1<br/><b>数据库路径</b> %2<br/><b>索引路径</b> %3")
            .arg(AppContext::instance()->baseUrl(), j::str(storage, "db_path"), indexPath));
    }, this);
    }, this);
}

// ============================================================
// P8.2 参数查看
// ============================================================
SettingsConfigPage::SettingsConfigPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("参数查看");
    header->setSubtitle("只读展示后端配置 · 修改需编辑 config.yaml 后重启");
    root->addWidget(header);

    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    m_body = new QWidget(scroll);
    m_layout = new QVBoxLayout(m_body);
    m_layout->setContentsMargins(0, 8, 0, 0);
    m_layout->setSpacing(12);
    scroll->setWidget(m_body);
    root->addWidget(scroll, 1);
}

void SettingsConfigPage::refresh() { loadConfig(); }

void SettingsConfigPage::addGroup(QVBoxLayout *lay, const QString &title, const QString &html) {
    auto *card = new QFrame();
    card->setObjectName("card");
    auto *cl = new QVBoxLayout(card);
    auto *t = new QLabel(title, card);
    t->setObjectName("cardTitle");
    cl->addWidget(t);
    auto *body = new QLabel(html, card);
    body->setTextFormat(Qt::RichText);
    body->setWordWrap(true);
    body->setStyleSheet("color:#374151;font-size:12px;line-height:1.7;"
                        "font-family:Consolas,monospace;");
    cl->addWidget(body);
    lay->addWidget(card);
}

void SettingsConfigPage::loadConfig() {
    const int generation = ++m_generation;
    // 清空旧分组
    while (QLayoutItem *item = m_layout->takeAt(0)) {
        if (QWidget *w = item->widget()) w->deleteLater();
        delete item;
    }
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync("/api/memory/system/config", [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    if (!r.hasJsonObject()) {
        auto *lbl = new QLabel("配置接口不可用", m_body);
        lbl->setObjectName("pageSubtitle");
        m_layout->addWidget(lbl);
        m_layout->addStretch();
        return;
    }
    const QJsonObject cfg = r.jsonObject();
    const QJsonObject storage = j::obj(cfg, "storage");
    const QJsonObject retr = j::obj(cfg, "retrieval");
    const QJsonObject llm = j::obj(cfg, "llm");
    const QJsonObject embed = j::obj(cfg, "embedding");
    const QJsonObject vec = j::obj(cfg, "vector_engine");
    const QJsonObject safety = j::obj(cfg, "safety");

    addGroup(m_layout, "存储", QString("db_path: %1<br/>vector_index: %2<br/>evidence: %3<br/>cache_max_size: %4")
        .arg(j::str(storage, "db_path"), j::str(storage, "vector_index_path"),
             j::str(storage, "evidence_path")).arg(j::integer(storage, "cache_max_size")));
    addGroup(m_layout, "检索", QString("top_k: %1 · vector %2 · keyword %3 · metadata %4<br/>rerank: %5 · cache_ttl: %6s · p95: %7ms · p99: %8ms")
        .arg(j::integer(retr, "default_top_k"))
        .arg(j::num(retr, "vector_weight"), 0, 'f', 1)
        .arg(j::num(retr, "keyword_weight"), 0, 'f', 1)
        .arg(j::num(retr, "metadata_weight"), 0, 'f', 1)
        .arg(j::boolean(retr, "rerank_enabled") ? "开" : "关")
        .arg(j::integer(retr, "cache_ttl_seconds"))
        .arg(j::num(retr, "target_p95_ms"), 0, 'f', 0)
        .arg(j::num(retr, "target_p99_ms"), 0, 'f', 0));
    addGroup(m_layout, "LLM / Embedding",
        QString("llm: %1 · %2<br/>api_base: %3<br/>embedding: %4 · dim %5")
            .arg(j::str(llm, "provider"), j::str(llm, "model"), j::str(llm, "api_base"))
            .arg(j::str(embed, "provider")).arg(j::integer(embed, "dimension")));
    addGroup(m_layout, "向量引擎",
        QString("provider: %1 · host:%2:%3<br/>collection: %4 · dim %5 · timeout %6ms")
            .arg(j::str(vec, "provider")).arg(j::str(vec, "host")).arg(j::integer(vec, "port"))
            .arg(j::str(vec, "collection")).arg(j::integer(vec, "dimension"))
            .arg(j::integer(vec, "search_timeout_ms")));
    const QJsonObject policy = j::obj(safety, "policy");
    addGroup(m_layout, "安全策略",
        QString("rule_set: %1 · v%2<br/>policy: %3 v%4 · fallback %5 · fail_closed %6<br/>audit: %7 · quarantine: %8")
            .arg(j::str(safety, "rule_set_id"), j::str(safety, "rule_set_version"))
            .arg(j::str(policy, "policy_id"), j::str(policy, "version"))
            .arg(j::str(policy, "fallback_action"))
            .arg(j::boolean(policy, "fail_closed") ? "是" : "否")
            .arg(j::boolean(j::obj(safety, "audit"), "enabled") ? "开" : "关")
            .arg(j::boolean(j::obj(safety, "quarantine"), "enabled") ? "开" : "关"));
    m_layout->addStretch();
    }, this);
}

// ============================================================
// P8.3 演示数据工具
// ============================================================
SettingsDemoPage::SettingsDemoPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("演示数据工具");
    header->setSubtitle("危险操作需二次确认（输入确认文本）");
    root->addWidget(header);

    auto *card = new QFrame(this);
    card->setObjectName("card");
    auto *cl = new QVBoxLayout(card);
    auto *warn = new QLabel("以下操作会删除当前用户（" + AppContext::instance()->userId() + "）的演示数据，请谨慎执行。", card);
    warn->setStyleSheet("background:#FEF2F2;border:1px solid #FECACA;border-radius:6px;color:#B91C1C;padding:8px;");
    warn->setWordWrap(true);
    cl->addWidget(warn);

    auto *row1 = new QHBoxLayout();
    auto *b1 = new QPushButton("清空偏好", card);
    m_clearPreferencesButton = b1;
    b1->setObjectName("dangerBtn");
    connect(b1, &QPushButton::clicked, this, &SettingsDemoPage::clearPreferences);
    auto *desc1 = new QLabel("仅删除当前用户的偏好记忆（含向量索引投影）", card);
    desc1->setObjectName("pageSubtitle");
    row1->addWidget(b1);
    row1->addWidget(desc1, 1);
    cl->addLayout(row1);

    auto *row2 = new QHBoxLayout();
    auto *b2 = new QPushButton("清空全部演示数据", card);
    m_clearAllButton = b2;
    b2->setObjectName("solidDangerBtn");
    connect(b2, &QPushButton::clicked, this, &SettingsDemoPage::clearAllDemo);
    auto *desc2 = new QLabel("删除偏好/知识/事实/事件/冲突/遗忘历史等全部演示数据", card);
    desc2->setObjectName("pageSubtitle");
    row2->addWidget(b2);
    row2->addWidget(desc2, 1);
    cl->addLayout(row2);

    m_resultLabel = new QLabel(card);
    m_resultLabel->setWordWrap(true);
    m_resultLabel->setTextFormat(Qt::RichText);
    m_resultLabel->setStyleSheet("color:#16A34A;font-size:13px;line-height:1.8;");
    cl->addWidget(m_resultLabel);
    root->addWidget(card);
    root->addStretch();
}

void SettingsDemoPage::refresh() {}

void SettingsDemoPage::clearPreferences() {
    if (!ConfirmDialog::confirm(this, "清空偏好", "确认清空当前用户的全部偏好记忆？", "清空")) return;
    m_clearPreferencesButton->setEnabled(false);
    AppContext::instance()->api()->deleteAsync(
        api::ApiClient::urlWithQuery("/api/agent/preferences", {{"user_id", AppContext::instance()->userId()}}),
        [this](const api::Result &r) {
            m_clearPreferencesButton->setEnabled(true);
            if (r.ok) m_resultLabel->setText(QString("已清空 %1 条偏好记忆。").arg(j::integer(r.jsonObject(), "deleted")));
            else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
        }, false, this);
}

void SettingsDemoPage::clearAllDemo() {
    if (!ConfirmDialog::confirm(this, "清空全部演示数据",
                                "将删除偏好/知识/事实/事件/冲突/遗忘历史等全部数据，且不可恢复。确认输入“清空全部”执行。",
                                "清空全部", "确认清空")) return;
    m_clearAllButton->setEnabled(false);
    AppContext::instance()->api()->deleteAsync(
        api::ApiClient::urlWithQuery("/api/agent/demo-data", {{"user_id", AppContext::instance()->userId()}}),
        [this](const api::Result &r) {
            m_clearAllButton->setEnabled(true);
            if (r.ok) {
                const QJsonObject del = j::obj(r.jsonObject(), "deleted");
                QString html = "<b>清理结果：</b><br/>";
                const QStringList keys = {"preferences", "knowledge", "knowledge_versions", "events", "conflicts", "forget_history", "extraction_tasks", "facts"};
                for (const QString &k : keys) html += QString("%1: %2　").arg(k).arg(j::integer(del, k));
                m_resultLabel->setText(html);
            } else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
        }, false, this);
}
