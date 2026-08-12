#include "SearchPage.h"

#include <QApplication>
#include <QCheckBox>
#include <QClipboard>
#include <QComboBox>
#include <QTimer>
#include <QDoubleSpinBox>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/EmptyState.h"
#include "../widgets/JsonViewer.h"
#include "../widgets/PageHeader.h"
#include "../widgets/StatusTag.h"

SearchPage::SearchPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("检索测试");
    header->setSubtitle("人工验证混合检索质量 · 偏好/知识/事实统一召回");
    root->addWidget(header);

    // ---- 顶部搜索区 ----
    auto *searchRow = new QHBoxLayout();
    searchRow->setSpacing(8);
    m_queryEdit = new QLineEdit(this);
    m_queryEdit->setPlaceholderText("输入查询，如：请用 Markdown 格式写周报");
    m_queryEdit->setMinimumHeight(38);
    m_queryEdit->setStyleSheet("font-size:14px;");
    connect(m_queryEdit, &QLineEdit::returnPressed, this, &SearchPage::runSearch);
    auto *searchBtn = new QPushButton("检索", this);
    searchBtn->setObjectName("primaryBtn");
    searchBtn->setMinimumHeight(38);
    searchBtn->setFixedWidth(100);
    connect(searchBtn, &QPushButton::clicked, this, &SearchPage::runSearch);
    searchRow->addWidget(m_queryEdit, 1);
    searchRow->addWidget(searchBtn);
    root->addLayout(searchRow);

    // ---- 筛选面板 ----
    auto *filterRow = new QHBoxLayout();
    filterRow->setSpacing(8);
    m_sceneCombo = new QComboBox(this);
    m_sceneCombo->addItem("场景：任意", "");
    m_sceneCombo->addItem("office", "office");
    m_sceneCombo->addItem("code", "code");
    m_sceneCombo->addItem("chat", "chat");
    m_taskEdit = new QLineEdit(this);
    m_taskEdit->setPlaceholderText("任务类型（如 office.weekly_report）");
    m_taskEdit->setFixedWidth(190);
    m_topK = new QSpinBox(this);
    m_topK->setRange(1, 30);
    m_topK->setValue(10);
    m_topK->setPrefix("TopK ");
    m_cbPreference = new QCheckBox("偏好", this);
    m_cbPreference->setChecked(true);
    m_cbKnowledge = new QCheckBox("知识", this);
    m_cbKnowledge->setChecked(true);
    m_cbFact = new QCheckBox("事实", this);
    m_cbFact->setChecked(true);
    m_minConf = new QDoubleSpinBox(this);
    m_minConf->setRange(0, 1);
    m_minConf->setSingleStep(0.05);
    m_minConf->setValue(0);
    m_minConf->setPrefix("置信≥ ");
    m_minConf->setDecimals(2);
    filterRow->addWidget(m_sceneCombo);
    filterRow->addWidget(m_taskEdit);
    filterRow->addWidget(m_topK);
    filterRow->addWidget(m_cbPreference);
    filterRow->addWidget(m_cbKnowledge);
    filterRow->addWidget(m_cbFact);
    filterRow->addWidget(m_minConf);
    filterRow->addStretch();
    root->addLayout(filterRow);

    // ---- 主内容：左结果 / 右侧栏 ----
    auto *content = new QWidget(this);
    auto *mainRow = new QHBoxLayout(content);
    mainRow->setContentsMargins(0, 8, 0, 0);
    mainRow->setSpacing(12);

    // 左：结果滚动区
    m_resultsScroll = new QScrollArea(content);
    m_resultsScroll->setWidgetResizable(true);
    m_resultsScroll->setFrameShape(QFrame::NoFrame);
    m_resultsContainer = new QWidget();
    m_resultsLayout = new QVBoxLayout(m_resultsContainer);
    m_resultsLayout->setContentsMargins(0, 0, 8, 0);
    m_resultsLayout->setSpacing(10);
    m_resultsScroll->setWidget(m_resultsContainer);
    mainRow->addWidget(m_resultsScroll, 3);

    // 右：侧栏
    auto *side = new QWidget(content);
    auto *sideLay = new QVBoxLayout(side);
    sideLay->setContentsMargins(0, 0, 0, 0);
    sideLay->setSpacing(12);
    side->setFixedWidth(380);

    auto makeCard = [&](const QString &title) -> QPair<QFrame *, QVBoxLayout *> {
        auto *card = new QFrame(side);
        card->setObjectName("card");
        auto *lay = new QVBoxLayout(card);
        auto *t = new QLabel(title, card);
        t->setObjectName("cardTitle");
        lay->addWidget(t);
        return {card, lay};
    };

    // 上下文预览
    auto ctxCard = makeCard("上下文预览（可直接注入 prompt）");
    m_contextText = new QLabel(ctxCard.first);
    m_contextText->setWordWrap(true);
    m_contextText->setTextInteractionFlags(Qt::TextSelectableByMouse);
    m_contextText->setStyleSheet("background:#F8F9FB;border:1px solid #ECEEF2;border-radius:6px;"
                                 "padding:10px;color:#374151;font-family:Consolas,monospace;font-size:12px;");
    ctxCard.second->addWidget(m_contextText);
    auto *ctxBtns = new QHBoxLayout();
    auto *genCtxBtn = new QPushButton("生成上下文", ctxCard.first);
    genCtxBtn->setObjectName("primaryBtn");
    connect(genCtxBtn, &QPushButton::clicked, this, &SearchPage::generateContext);
    m_copyContextBtn = new QPushButton("复制", ctxCard.first);
    connect(m_copyContextBtn, &QPushButton::clicked, this, [this]() {
        if (m_contextText->text().isEmpty()) return;
        QApplication::clipboard()->setText(m_contextText->text());
        m_copyContextBtn->setText("已复制 ✓");
        QTimer::singleShot(1200, m_copyContextBtn, [this]() { m_copyContextBtn->setText("复制"); });
    });
    ctxBtns->addWidget(genCtxBtn);
    ctxBtns->addWidget(m_copyContextBtn);
    ctxCard.second->addLayout(ctxBtns);
    sideLay->addWidget(ctxCard.first);

    // 性能
    auto perfCard = makeCard("性能");
    m_latencyLabel = new QLabel("—", perfCard.first);
    m_totalLabel = new QLabel("—", perfCard.first);
    m_cacheLabel = new QLabel("—", perfCard.first);
    perfCard.second->addWidget(m_latencyLabel);
    perfCard.second->addWidget(m_totalLabel);
    perfCard.second->addWidget(m_cacheLabel);
    sideLay->addWidget(perfCard.first);

    // 请求 JSON
    auto reqCard = makeCard("请求 JSON");
    auto *reqView = new JsonViewer(reqCard.first);
    reqView->editor()->setMaximumHeight(260);
    reqCard.second->addWidget(reqView);
    sideLay->addWidget(reqCard.first);
    sideLay->addStretch();

    mainRow->addWidget(side);
    root->addWidget(content, 1);
}

void SearchPage::refresh() {}

void SearchPage::applySearchQuery(const QString &query) {
    m_queryEdit->setText(query);
    runSearch();
}

QJsonObject SearchPage::updateRequestJson() {
    QJsonObject context;
    context["scene"] = m_sceneCombo->currentData().toString();
    context["task_type"] = m_taskEdit->text().trimmed();
    context["app"] = "";

    QJsonArray types;
    if (m_cbPreference->isChecked()) types.append("preference");
    if (m_cbKnowledge->isChecked()) types.append("knowledge");
    if (m_cbFact->isChecked()) types.append("fact");

    QJsonObject req;
    req["user_id"] = AppContext::instance()->userId();
    req["query"] = m_queryEdit->text().trimmed();
    req["context"] = context;
    req["project_id"] = "";
    req["top_k"] = m_topK->value();
    req["memory_types"] = types;
    req["min_confidence"] = m_minConf->value();
    return req;
}

void SearchPage::runSearch() {
    const QString q = m_queryEdit->text().trimmed();
    if (q.isEmpty()) { QMessageBox::information(this, "提示", "请输入查询内容"); return; }

    m_lastRequest = updateRequestJson();
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->post("/api/memory/search", m_lastRequest);

    if (!r.ok) {
        // 空态：显示错误
        QMessageBox::warning(this, "检索失败", r.errorCode + " " + r.errorMessage);
        return;
    }
    m_lastResponse = r.jsonObject();
    renderResults(m_lastResponse);
}

void SearchPage::renderResults(const QJsonObject &resp) {
    // 清空
    while (QLayoutItem *item = m_resultsLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) w->deleteLater();
        delete item;
    }

    const QJsonArray prefs = j::arr(resp, "preferences");
    const QJsonArray knows = j::arr(resp, "knowledge");
    const QJsonArray facts = j::arr(resp, "facts");

    const int total = prefs.size() + knows.size() + facts.size();
    if (total == 0) {
        auto *empty = new EmptyState();
        empty->setIconText("🔍");
        empty->setTitle("未检索到相关记忆");
        empty->setHint("尝试调整查询词、放宽类型或置信度阈值");
        m_resultsLayout->addWidget(empty, 1);
    } else {
        renderGroup("偏好记忆", QColor("#3B82F6"), prefs);
        renderGroup("知识记忆", QColor("#8B5CF6"), knows);
        renderGroup("事实记忆", QColor("#06B6D4"), facts);
    }
    m_resultsLayout->addStretch();

    m_totalLabel->setText(QString("结果总数：%1").arg(total));
    m_latencyLabel->setText(QString("耗时：%1 ms").arg(j::num(resp, "latency_ms"), 0, 'f', 1));
    m_cacheLabel->setText("缓存命中：—");
}

void SearchPage::renderGroup(const QString &title, const QColor &color, const QJsonArray &items) {
    if (items.isEmpty()) return;
    auto *head = new QLabel(QString("%1（%2）").arg(title).arg(items.size()));
    head->setObjectName("cardTitle");
    head->setStyleSheet("color:" + color.name() + ";");
    m_resultsLayout->addWidget(head);

    for (const QJsonValue &v : items) {
        const QJsonObject item = v.toObject();
        auto *card = new QFrame();
        card->setObjectName("card");
        auto *lay = new QVBoxLayout(card);
        lay->setContentsMargins(12, 10, 12, 10);

        auto *topRow = new QHBoxLayout();
        auto *summ = new QLabel();
        summ->setWordWrap(true);
        summ->setStyleSheet("color:#1F2430;");
        QString content = j::str(item, "text").isEmpty() ? j::str(item, "name") : j::str(item, "text");
        if (content.isEmpty()) content = j::str(item, "content");
        summ->setText(content);
        topRow->addWidget(summ, 1);

        const double score = j::num(item, "confidence", j::num(item, "score"));
        auto *scoreLabel = new QLabel(QString::number(score, 'f', 2));
        scoreLabel->setStyleSheet("color:#3790FA;font-weight:700;font-size:13px;");
        topRow->addWidget(scoreLabel, 0, Qt::AlignTop);
        lay->addLayout(topRow);

        auto *metaRow = new QHBoxLayout();
        metaRow->setSpacing(6);
        // 类型标签
        auto *typeTag = new StatusTag();
        typeTag->setMemoryType(j::str(item, "memory_type"));
        metaRow->addWidget(typeTag);
        // 来源标签
        const QString source = j::str(item, "source");
        if (!source.isEmpty()) {
            auto *srcTag = new StatusTag();
            srcTag->setTag(source, "statusTag",
                           source == "vector" ? "active" : (source == "keyword" ? "pending" : "archived"));
            metaRow->addWidget(srcTag);
        }
        metaRow->addStretch();
        lay->addLayout(metaRow);
        m_resultsLayout->addWidget(card);
    }
}

void SearchPage::generateContext() {
    if (m_queryEdit->text().trimmed().isEmpty()) {
        QMessageBox::information(this, "提示", "请先输入查询内容");
        return;
    }
    const QJsonObject req = updateRequestJson();
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->post("/api/memory/context", req);
    if (!r.ok) {
        QMessageBox::warning(this, "生成失败", r.errorCode + " " + r.errorMessage);
        return;
    }
    QString ctx = j::str(r.jsonObject(), "context_text");
    if (ctx.isEmpty()) ctx = j::str(r.jsonObject(), "context");
    m_contextText->setText(ctx);
    m_contextText->setToolTip(ctx);
    m_copyContextBtn->setEnabled(!ctx.isEmpty());
}
