// 系统设置 · 4 个子页完整实现

#include "SettingsPages.h"

#include <QFormLayout>
#include <QFrame>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
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
    // 传 user_id：fact_count 按当前用户统计，与总览/事实页口径一致
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/system/status", {{"user_id", AppContext::instance()->userId()}}),
        [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    m_table->setRowCount(0);
    if (!r.ok || !r.hasJsonObject()) {
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
    // 状态灯三态：正常 / 异常 / 未知。未知=后端未提供判定字段，
    // 不再默认显示"正常"绿灯伪装。
    auto addRow = [this](const QString &name, const QString &state, const QString &detail) {
        const int row = m_table->rowCount();
        m_table->insertRow(row);
        m_table->setItem(row, 0, new QTableWidgetItem(name));
        auto *tag = new StatusTag();
        if (state == "ok") { tag->setStatus("active"); tag->setText("正常"); }
        else if (state == "bad") { tag->setStatus("deleted"); tag->setText("异常"); }
        else { tag->setStatus("pending"); tag->setText("未知"); }
        m_table->setCellWidget(row, 1, tag);
        m_table->setItem(row, 2, new QTableWidgetItem(detail));
    };

    const QJsonObject storage = j::obj(s, "storage");
    const QJsonObject embed = j::obj(s, "embedding");
    const QJsonObject llm = j::obj(s, "llm");
    const QJsonObject vec = j::obj(s, "vector_engine");
    const QJsonObject retr = j::obj(s, "retrieval");
    const QJsonObject safety = j::obj(s, "safety");

    addRow("REST 服务", "ok", j::str(s, "service") + " v" + j::str(s, "version") + " · " + j::str(s, "runtime_mode"));
    addRow("SQLite 存储", "ok", QString("事件 %1 · 偏好 %2 · 知识 %3 · 事实 %4（当前用户）· 冲突 %5 · 遗忘 %6")
        .arg(j::integer(storage, "event_count")).arg(j::integer(storage, "preference_count"))
        .arg(j::integer(storage, "knowledge_count")).arg(j::integer(storage, "fact_count"))
        .arg(j::integer(storage, "conflict_count")).arg(j::integer(storage, "forget_count")));
    addRow("Embedding", j::str(embed, "provider").isEmpty() ? "bad" : "ok",
           QString("%1 · dim %2 · %3")
               .arg(j::str(embed, "provider").isEmpty() ? "未配置" : j::str(embed, "provider"))
               .arg(j::integer(embed, "dimension")).arg(j::str(embed, "model_name")));
    addRow("LLM", j::str(llm, "model").isEmpty() ? "bad" : "ok",
           QString("%1 · %2").arg(j::str(llm, "provider").isEmpty() ? "未配置" : j::str(llm, "provider"),
                                  j::str(llm, "model").isEmpty() ? "未配置" : j::str(llm, "model")));
    QString vecState = "unknown";
    if (vec.value("connected").isBool())
        vecState = j::boolean(vec, "connected") ? "ok" : "bad";
    addRow("向量引擎", vecState, QString("%1 · %2 · %3")
           .arg(j::str(vec, "provider").isEmpty() ? "未装配" : j::str(vec, "provider"),
                j::str(vec, "collection").isEmpty() ? "—" : j::str(vec, "collection"),
                vec.value("vector_count").isNull() ? QString("—") : QString::number(j::integer(vec, "vector_count"))));
    addRow("检索配置", j::str(retr, "type").isEmpty() ? "unknown" : "ok",
           QString("type=%1 · top_k=%2 · cache_ttl=%3s")
               .arg(j::str(retr, "type").isEmpty() ? "—" : j::str(retr, "type"))
               .arg(j::integer(retr, "default_top_k"))
               .arg(j::integer(retr, "cache_ttl_seconds")));
    addRow("安全门禁", j::boolean(safety, "gate_available") ? "ok" : "bad",
           QString("规则集 %1 · 审计 %2 · 隔离区 %3")
               .arg(j::str(safety, "rule_set_version"))
               .arg(j::boolean(safety, "audit_enabled") ? "开" : "关")
               .arg(j::boolean(safety, "quarantine_enabled") ? "开" : "关"));

    api::ApiClient *configApi = AppContext::instance()->api();
    configApi->getAsync("/api/memory/system/config", [this, generation, storage](const api::Result &rCfg) {
        if (generation != m_generation) return;
        QString indexPath = "—";
        if (rCfg.ok && rCfg.hasJsonObject()) indexPath = j::str(j::obj(rCfg.jsonObject(), "storage"), "vector_index_path", "—");
        m_connLabel->setText(QString("<b>API Base URL</b> %1<br/><b>数据库路径</b> %2<br/><b>索引路径</b> %3")
            .arg(AppContext::instance()->baseUrl(), j::str(storage, "db_path"), indexPath));
    }, this);
    }, this);
}

// ============================================================
// P8.2 LLM 服务配置
// ============================================================
SettingsLLMPage::SettingsLLMPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(12);

    auto *header = new PageHeader(this);
    header->setTitle("LLM 服务配置");
    header->setSubtitle("云端 OpenAI 兼容接口 · 保存后重启服务生效");
    root->addWidget(header);

    auto *card = new QFrame(this);
    card->setObjectName("card");
    auto *layout = new QVBoxLayout(card);
    auto *notice = new QLabel("仅支持 HTTPS 云端 API。密钥为只写字段，读取配置时不会回显；保存后将写入当前服务使用的 config.yaml。", card);
    notice->setWordWrap(true);
    notice->setStyleSheet("background:#EFF6FF;border:1px solid #BFDBFE;border-radius:6px;color:#1D4ED8;padding:8px;");
    layout->addWidget(notice);

    auto *form = new QFormLayout();
    form->setLabelAlignment(Qt::AlignRight);
    m_apiBase = new QLineEdit(card);
    m_apiBase->setPlaceholderText("https://api.example.com/v1");
    m_apiKey = new QLineEdit(card);
    m_apiKey->setEchoMode(QLineEdit::Password);
    m_apiKey->setPlaceholderText("首次配置必填；留空则保留当前密钥");
    m_model = new QLineEdit(card);
    m_model->setPlaceholderText("例如 gpt-4o-mini");
    form->addRow("LLM_API_BASE", m_apiBase);
    form->addRow("LLM_API_KEY", m_apiKey);
    form->addRow("LLM_MODEL", m_model);
    layout->addLayout(form);

    m_keyStatus = new QLabel(card);
    m_keyStatus->setObjectName("pageSubtitle");
    layout->addWidget(m_keyStatus);
    // dirty 追踪：有未保存修改时刷新不覆盖表单
    for (QLineEdit *edit : {m_apiBase, m_apiKey, m_model})
        connect(edit, &QLineEdit::textEdited, this, [this]() { m_dirty = true; });
    auto *actions = new QHBoxLayout();
    m_saveButton = new QPushButton("保存 LLM 配置", card);
    m_saveButton->setObjectName("primaryBtn");
    connect(m_saveButton, &QPushButton::clicked, this, &SettingsLLMPage::saveConfig);
    actions->addWidget(m_saveButton);
    actions->addStretch();
    layout->addLayout(actions);
    m_resultLabel = new QLabel(card);
    m_resultLabel->setWordWrap(true);
    m_resultLabel->setStyleSheet("color:#16A34A;font-size:13px;");
    layout->addWidget(m_resultLabel);
    root->addWidget(card);
    root->addStretch();
}

void SettingsLLMPage::refresh() { loadConfig(); }

void SettingsLLMPage::loadConfig() {
    const int generation = ++m_generation;
    m_saveButton->setEnabled(true);
    AppContext::instance()->api()->getAsync("/api/memory/system/config", [this, generation](const api::Result &r) {
        if (generation != m_generation) return;
        if (!r.ok || !r.hasJsonObject()) {
            m_resultLabel->setStyleSheet("color:#DC2626;font-size:13px;");
            m_resultLabel->setText("无法读取 LLM 配置：" +
                                   (r.errorCode.isEmpty() && r.errorMessage.isEmpty()
                                        ? QStringLiteral("网络错误") : r.errorCode + " " + r.errorMessage));
            return;
        }
        if (m_dirty) {
            // 有未保存修改：不覆盖表单，如实提示
            m_keyStatus->setText(m_keyStatus->text().isEmpty()
                ? "表单有未保存的修改，未用服务端配置覆盖；保存或还原后才会刷新。" : m_keyStatus->text());
            return;
        }
        const QJsonObject llm = j::obj(r.jsonObject(), "llm");
        m_apiBase->setText(j::str(llm, "api_base"));
        m_model->setText(j::str(llm, "model"));
        m_apiKey->clear();
        m_keyStatus->setText(j::boolean(llm, "api_key_configured")
            ? "当前服务已配置 API Key；留空保存将保留该密钥。"
            : "当前服务尚未配置 API Key。首次保存时必须填写。"
        );
        m_resultLabel->clear();
    }, this);
}

void SettingsLLMPage::saveConfig() {
    const QString apiBase = m_apiBase->text().trimmed();
    const QString model = m_model->text().trimmed();
    if (!apiBase.startsWith("https://", Qt::CaseInsensitive)) {
        QMessageBox::warning(this, "配置无效", "LLM_API_BASE 必须是 HTTPS 云端 API 地址。");
        return;
    }
    if (model.isEmpty()) {
        QMessageBox::warning(this, "配置无效", "请填写 LLM_MODEL。");
        return;
    }
    QJsonObject body;
    body["api_base"] = apiBase;
    body["model"] = model;
    if (!m_apiKey->text().isEmpty()) body["api_key"] = m_apiKey->text();

    m_saveButton->setEnabled(false);
    AppContext::instance()->api()->putAsync("/api/memory/system/llm", body,
        [this](const api::Result &r) {
            m_saveButton->setEnabled(true);
            if (!r.ok) {
                QMessageBox::warning(this, "保存失败", r.errorCode + " " + r.errorMessage);
                return;
            }
            m_apiKey->clear();
            m_dirty = false;
            m_keyStatus->setText("当前服务已配置 API Key；留空保存将保留该密钥。");
            m_resultLabel->setStyleSheet("color:#16A34A;font-size:13px;");
            m_resultLabel->setText("LLM 配置已保存。请重启 MemoryHub 服务后，新的云端模型配置才会用于记忆提取。");
        }, false, this);
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
    header->setSubtitle("清理功能暂不可用");
    root->addWidget(header);

    auto *card = new QFrame(this);
    card->setObjectName("card");
    auto *cl = new QVBoxLayout(card);
    auto *warn = new QLabel(card);
    m_warningLabel = warn;
    warn->setText("清理功能已暂停：当前接口会清空全局向量索引，影响所有用户；待支持按用户清理后恢复。当前用户：" + AppContext::instance()->userId().toHtmlEscaped());
    warn->setStyleSheet("background:#FEF2F2;border:1px solid #FECACA;border-radius:6px;color:#B91C1C;padding:8px;");
    warn->setWordWrap(true);
    cl->addWidget(warn);

    auto *row1 = new QHBoxLayout();
    auto *b1 = new QPushButton("清空偏好", card);
    m_clearPreferencesButton = b1;
    b1->setEnabled(false);
    b1->setObjectName("dangerBtn");
    connect(b1, &QPushButton::clicked, this, &SettingsDemoPage::clearPreferences);
    auto *desc1 = new QLabel("暂不可用：不会恢复跨用户清理能力；接口会清空全局向量索引", card);
    desc1->setObjectName("pageSubtitle");
    row1->addWidget(b1);
    row1->addWidget(desc1, 1);
    cl->addLayout(row1);

    auto *row2 = new QHBoxLayout();
    auto *b2 = new QPushButton("清空全部演示数据", card);
    m_clearAllButton = b2;
    b2->setEnabled(false);
    b2->setObjectName("solidDangerBtn");
    connect(b2, &QPushButton::clicked, this, &SettingsDemoPage::clearAllDemo);
    auto *desc2 = new QLabel("暂不可用：接口会清空全局向量索引和缓存", card);
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

void SettingsDemoPage::refresh() {
    m_warningLabel->setText("清理功能已暂停：当前接口会清空全局向量索引，影响所有用户；待支持按用户清理后恢复。当前用户：" + AppContext::instance()->userId().toHtmlEscaped());
    m_resultLabel->setText("当前用户：" + AppContext::instance()->userId().toHtmlEscaped() +
                           "。清理按钮已禁用，避免跨用户清空全局向量索引。");
}

void SettingsDemoPage::clearPreferences() {
    // Disabled until the backend supports user-scoped index cleanup.
}

void SettingsDemoPage::clearAllDemo() {
    // Disabled until the backend supports user-scoped index cleanup.
}
