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
#include <QScrollBar>
#include <QSpinBox>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/EmptyState.h"
#include "../widgets/JsonViewer.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"
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
    m_searchButton = new QPushButton("检索", this);
    m_searchButton->setObjectName("primaryBtn");
    m_searchButton->setMinimumHeight(38);
    m_searchButton->setFixedWidth(100);
    m_searchButton->setAccessibleName("执行记忆检索");
    connect(m_searchButton, &QPushButton::clicked, this, &SearchPage::runSearch);
    searchRow->addWidget(m_queryEdit, 1);
    searchRow->addWidget(m_searchButton);
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
    m_topK->setObjectName("filterSpin");
    m_topK->setButtonSymbols(QAbstractSpinBox::NoButtons);
    m_topK->setRange(1, 30);
    m_topK->setValue(10);
    m_topK->setFixedWidth(68);
    auto *topKLabel = new QLabel("TopK", this);
    topKLabel->setObjectName("filterLabel");
    m_cbPreference = new QCheckBox("偏好", this);
    m_cbPreference->setChecked(true);
    m_cbKnowledge = new QCheckBox("知识", this);
    m_cbKnowledge->setChecked(true);
    m_cbFact = new QCheckBox("事实", this);
    m_cbFact->setChecked(true);
    m_minConf = new QDoubleSpinBox(this);
    m_minConf->setObjectName("filterSpin");
    m_minConf->setButtonSymbols(QAbstractSpinBox::NoButtons);
    m_minConf->setRange(0, 1);
    m_minConf->setSingleStep(0.05);
    m_minConf->setValue(0);
    m_minConf->setDecimals(2);
    m_minConf->setFixedWidth(78);
    auto *minConfLabel = new QLabel("置信 ≥", this);
    minConfLabel->setObjectName("filterLabel");
    filterRow->addWidget(m_sceneCombo);
    filterRow->addWidget(m_taskEdit);
    filterRow->addWidget(topKLabel);
    filterRow->addWidget(m_topK);
    filterRow->addWidget(m_cbPreference);
    filterRow->addWidget(m_cbKnowledge);
    filterRow->addWidget(m_cbFact);
    filterRow->addWidget(minConfLabel);
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
    m_stateView = new PageStateView(m_resultsContainer);
    m_stateView->setState(PageState::Empty, "输入查询开始检索", "结果会显示在这里。");
    m_resultsLayout->addWidget(m_stateView);

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
    m_contextText->setTextFormat(Qt::PlainText);
    m_contextText->setWordWrap(true);
    m_contextText->setTextInteractionFlags(Qt::TextSelectableByMouse);
    m_contextText->setStyleSheet("background:#F8F9FB;border:1px solid #ECEEF2;border-radius:6px;"
                                 "padding:10px;color:#374151;font-family:Consolas,monospace;font-size:12px;");
    ctxCard.second->addWidget(m_contextText);
    auto *ctxBtns = new QHBoxLayout();
    m_contextButton = new QPushButton("生成上下文", ctxCard.first);
    m_contextButton->setObjectName("primaryBtn");
    m_contextButton->setAccessibleName("生成检索上下文");
    connect(m_contextButton, &QPushButton::clicked, this, &SearchPage::generateContext);
    m_copyContextBtn = new QPushButton("复制", ctxCard.first);
    m_copyContextBtn->setEnabled(false);
    connect(m_copyContextBtn, &QPushButton::clicked, this, [this]() {
        if (m_contextText->text().isEmpty()) return;
        QApplication::clipboard()->setText(m_contextText->text());
        m_copyContextBtn->setText("已复制 ✓");
        QTimer::singleShot(1200, m_copyContextBtn, [this]() { m_copyContextBtn->setText("复制"); });
    });
    ctxBtns->addWidget(m_contextButton);
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
    m_requestView = new JsonViewer(reqCard.first);
    m_requestView->editor()->setMaximumHeight(260);
    reqCard.second->addWidget(m_requestView);
    sideLay->addWidget(reqCard.first);
    sideLay->addStretch();

    mainRow->addWidget(side);
    root->addWidget(content, 1);
    // Any change to context inputs invalidates both displayed and in-flight context.
    connect(m_queryEdit, &QLineEdit::textChanged, this, &SearchPage::clearContext);
    connect(m_taskEdit, &QLineEdit::textChanged, this, &SearchPage::clearContext);
    connect(m_sceneCombo, QOverload<int>::of(&QComboBox::currentIndexChanged), this, &SearchPage::clearContext);
    connect(m_topK, QOverload<int>::of(&QSpinBox::valueChanged), this, &SearchPage::clearContext);
    connect(m_minConf, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, &SearchPage::clearContext);
    for (auto *check : {m_cbPreference, m_cbKnowledge, m_cbFact})
        connect(check, &QCheckBox::toggled, this, &SearchPage::clearContext);
}

void SearchPage::clearResults() {
    while (QLayoutItem *item = m_resultsLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) {
            if (w != m_stateView) { w->hide(); w->deleteLater(); }
        }
        delete item;
    }
    m_resultsLayout->addWidget(m_stateView);
    m_resultsScroll->verticalScrollBar()->setValue(0);
    m_stateView->clearAction();
}

void SearchPage::clearContext() {
    ++m_contextGeneration;
    m_contextLoading = false;
    m_contextText->clear();
    m_contextText->setToolTip(QString());
    m_copyContextBtn->setEnabled(false);
    m_copyContextBtn->setText("复制");
    m_contextButton->setEnabled(true);
    m_contextButton->setText("生成上下文");
}

void SearchPage::refresh() {
    ++m_generation;
    clearResults();
    clearContext();
    m_lastRequest = QJsonObject();
    m_lastResponse = QJsonObject();
    m_requestView->setObject(m_lastRequest);
    for (auto *label : {m_latencyLabel, m_totalLabel, m_cacheLabel}) label->setText("—");
    m_searchButton->setEnabled(true);
    m_searchButton->setText("检索");
    m_stateView->setState(PageState::Empty, "输入查询开始检索", "结果会显示在这里。");
}

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

    refresh();
    m_lastRequest = QJsonObject{{"user_id", AppContext::instance()->userId()},
                                {"query", q}, {"top_k", m_topK->value()},
                                {"include_provenance", true}};
    m_requestView->setObject(m_lastRequest);
    const int generation = ++m_generation;
    m_searchButton->setEnabled(false);
    m_searchButton->setText("检索中…");
    m_stateView->setState(PageState::Loading, "正在检索", "正在查询真实记忆数据…");
    const QString provenancePath = api::ApiClient::urlWithQuery(
        "/api/memory/v2/search",
        {{"user_id", AppContext::instance()->userId()},
         {"query", q},
         {"top_k", QString::number(m_topK->value())},
         {"include_provenance", "true"}});
    AppContext::instance()->api()->getAsync(provenancePath,
        [this, generation](const api::Result &r) {
            if (generation != m_generation) return;
            m_searchButton->setEnabled(true);
            m_searchButton->setText("检索");
            if (!r.ok || !r.hasJsonObject()) {
                m_stateView->setState(r.networkError ? PageState::Offline : PageState::Error,
                                      r.networkError ? "后端离线" : "检索失败",
                                      r.errorMessage.isEmpty() ? "请检查后端状态后重试。" : r.errorMessage);
                m_stateView->setAction("重试", [this]() { runSearch(); });
                return;
            }
            m_lastResponse = r.jsonObject();
            m_stateView->setState(PageState::Content, QString(), QString());
            renderResults(m_lastResponse);
        }, this);
}

void SearchPage::renderResults(const QJsonObject &resp) {
    clearResults();

    const auto filterGroup = [this](const QJsonArray &source, const QCheckBox *enabled) {
        QJsonArray filtered;
        if (!enabled->isChecked()) return filtered;
        const QString scene = m_sceneCombo->currentData().toString();
        const QString taskType = m_taskEdit->text().trimmed();
        const double minConfidence = m_minConf->value();
        for (const QJsonValue &value : source) {
            const QJsonObject item = value.toObject();
            if (j::num(item, "confidence", 0.0) < minConfidence) continue;
            const QJsonObject scope = j::obj(item, "scope");
            if (!scene.isEmpty() && j::str(scope, "scene") != scene) continue;
            if (!taskType.isEmpty() && j::str(scope, "task_type") != taskType) continue;
            filtered.append(item);
        }
        return filtered;
    };
    // API v2 keeps the provenance-aware retrieval contract compact.  Retain the
    // existing desktop filters locally so the UI behavior stays compatible.
    const QJsonArray prefs = filterGroup(j::arr(resp, "preferences"), m_cbPreference);
    const QJsonArray knows = filterGroup(j::arr(resp, "knowledge"), m_cbKnowledge);
    const QJsonArray facts = filterGroup(j::arr(resp, "facts"), m_cbFact);

    const int total = prefs.size() + knows.size() + facts.size();
    if (total == 0) {
        auto *empty = new EmptyState();
        empty->setIcon(QIcon(":/icons/search.svg"));
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
    const QJsonValue cache = resp.value("cache_hit");
    m_cacheLabel->setText(cache.isBool() ? QString("缓存命中：%1").arg(cache.toBool() ? "是" : "否")
                                         : "缓存命中：接口未提供");
    m_stateView->setState(PageState::Content, QString(), QString());
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
        if (content.isEmpty()) content = j::str(item, "object_value");
        if (content.isEmpty()) content = j::str(item, "source_text");
        summ->setTextFormat(Qt::PlainText);
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
        const QJsonObject provenance = j::obj(m_lastResponse, "provenance")
                                           .value(j::str(item, "memory_id", j::str(item, "fact_id")))
                                           .toObject();
        if (!provenance.isEmpty()) {
            const int evidenceCount = j::integer(provenance, "evidence_count");
            const int lineageCount = j::integer(provenance, "lineage_count");
            const int auditCount = j::arr(provenance, "audit_ids").size();
            auto *provenanceLabel = new QLabel(
                QString("证据 %1 · 谱系 %2 · 审计 %3")
                    .arg(evidenceCount)
                    .arg(lineageCount)
                    .arg(auditCount));
            provenanceLabel->setStyleSheet("color:#64748B;font-size:11px;");
            provenanceLabel->setToolTip("来自 /api/memory/v2/search 的安全溯源摘要");
            metaRow->addWidget(provenanceLabel);
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
    if (m_contextLoading) return;
    clearContext();
    const int generation = m_contextGeneration;
    m_contextLoading = true;
    m_contextButton->setEnabled(false);
    m_contextButton->setText("生成中…");
    AppContext::instance()->api()->postAsync("/api/memory/context", req,
        [this, generation](const api::Result &r) {
            if (generation != m_contextGeneration) return;
            m_contextLoading = false;
            m_contextButton->setEnabled(true);
            m_contextButton->setText("生成上下文");
            if (!r.ok || !r.hasJsonObject()) {
                m_contextText->setText(r.errorMessage.isEmpty() ? "上下文生成失败" : r.errorMessage);
                m_copyContextBtn->setEnabled(false);
                return;
            }
            QString ctx = j::str(r.jsonObject(), "context_text");
            if (ctx.isEmpty()) ctx = j::str(r.jsonObject(), "context");
            m_contextText->setText(ctx);
            m_contextText->setToolTip(ctx);
            m_copyContextBtn->setEnabled(!ctx.isEmpty());
        }, false, this, 10000);
}
