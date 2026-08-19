#include "MemoryTierPage.h"

#include <QHeaderView>
#include <QJsonObject>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"

MemoryTierPage::MemoryTierPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("记忆分层");
    header->setSubtitle("短期工作记忆（会话内） → 中期情景（跨会话） → 长期偏好/知识/事实。");
    auto *refresh = new QPushButton("刷新", header);
    refresh->setObjectName("primaryBtn");
    connect(refresh, &QPushButton::clicked, this, &MemoryTierPage::load);
    header->actionLayout()->addWidget(refresh);
    m_consolidateBtn = new QPushButton("立即流转 Consolidate", header);
    m_consolidateBtn->setObjectName("primaryBtn");
    connect(m_consolidateBtn, &QPushButton::clicked, this, &MemoryTierPage::runConsolidate);
    header->actionLayout()->addWidget(m_consolidateBtn);
    root->addWidget(header);

    auto *tabs = new QTabWidget(this);
    tabs->setDocumentMode(true);

    // 短期记忆（工作记忆）
    auto *shortW = new QWidget(this);
    auto *shortLay = new QVBoxLayout(shortW);
    shortLay->setContentsMargins(4, 4, 4, 4);
    m_shortSummary = new QLabel("加载中…", shortW);
    m_shortSummary->setStyleSheet("color:#6B7280;");
    shortLay->addWidget(m_shortSummary);
    m_shortTable = new QTableWidget(0, 6, shortW);
    m_shortTable->setHorizontalHeaderLabels({"会话", "来源", "内容", "场景", "任务", "时间"});
    m_shortTable->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    m_shortTable->verticalHeader()->setVisible(false);
    m_shortTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_shortTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_shortTable->setAlternatingRowColors(true);
    shortLay->addWidget(m_shortTable, 1);
    tabs->addTab(shortW, "短期 · 工作记忆");

    // 中期记忆（情景）
    auto *midW = new QWidget(this);
    auto *midLay = new QVBoxLayout(midW);
    midLay->setContentsMargins(4, 4, 4, 4);
    m_midSummary = new QLabel("加载中…", midW);
    m_midSummary->setStyleSheet("color:#6B7280;");
    midLay->addWidget(m_midSummary);
    m_midTable = new QTableWidget(0, 6, midW);
    m_midTable->setHorizontalHeaderLabels({"情景ID", "内容摘要", "场景", "任务", "结果", "时间"});
    m_midTable->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    m_midTable->verticalHeader()->setVisible(false);
    m_midTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_midTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_midTable->setAlternatingRowColors(true);
    midLay->addWidget(m_midTable, 1);
    tabs->addTab(midW, "中期 · 情景");

    root->addWidget(tabs, 1);

    m_state = new PageStateView(this);
    m_state->hide();
    root->addWidget(m_state);
}

void MemoryTierPage::refresh() { load(); }

void MemoryTierPage::load() {
    const int generation = ++m_generation;
    m_consolidateBtn->setEnabled(true);
    loadShortTerm();
    loadMidTerm();
}

void MemoryTierPage::loadShortTerm() {
    const int generation = m_generation;
    const QString uid = AppContext::instance()->userId();
    Api::client()->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/short-term", {{"user_id", uid}}),
        [this, generation](const api::Result &result) {
            if (generation != m_generation) return;
            m_short = result.ok && result.hasJsonArray() ? result.jsonArray() : QJsonArray();
            m_shortTable->setRowCount(m_short.size());
            for (int row = 0; row < m_short.size(); ++row) populateShort(row, m_short.at(row).toObject());
            m_shortSummary->setText(m_short.isEmpty()
                ? "当前没有短期工作记忆。"
                : QString("共 %1 条短期工作记忆（TTL 24h）").arg(m_short.size()));
        }, this);
}

void MemoryTierPage::loadMidTerm() {
    const int generation = m_generation;
    const QString uid = AppContext::instance()->userId();
    Api::client()->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/mid-term", {{"user_id", uid}}),
        [this, generation](const api::Result &result) {
            if (generation != m_generation) return;
            m_mid = result.ok && result.hasJsonArray() ? result.jsonArray() : QJsonArray();
            m_midTable->setRowCount(m_mid.size());
            for (int row = 0; row < m_mid.size(); ++row) populateMid(row, m_mid.at(row).toObject());
            m_midSummary->setText(m_mid.isEmpty()
                ? "当前没有中期情景。"
                : QString("共 %1 条中期情景").arg(m_mid.size()));
        }, this);
}

void MemoryTierPage::populateShort(int row, const QJsonObject &item) {
    m_shortTable->setItem(row, 0, new QTableWidgetItem(j::str(item, "session_id")));
    m_shortTable->setItem(row, 1, new QTableWidgetItem(j::str(item, "source_type")));
    m_shortTable->setItem(row, 2, new QTableWidgetItem(j::str(item, "text")));
    m_shortTable->setItem(row, 3, new QTableWidgetItem(j::str(item, "scene")));
    m_shortTable->setItem(row, 4, new QTableWidgetItem(j::str(item, "task_type")));
    m_shortTable->setItem(row, 5, new QTableWidgetItem(j::fmtTime(j::str(item, "created_at"))));
}

void MemoryTierPage::populateMid(int row, const QJsonObject &item) {
    m_midTable->setItem(row, 0, new QTableWidgetItem(j::shortId(j::str(item, "episode_id"))));
    m_midTable->setItem(row, 1, new QTableWidgetItem(j::str(item, "trajectory_summary")));
    m_midTable->setItem(row, 2, new QTableWidgetItem(j::str(item, "scene")));
    m_midTable->setItem(row, 3, new QTableWidgetItem(j::str(item, "task_type")));
    m_midTable->setItem(row, 4, new QTableWidgetItem(j::str(item, "outcome")));
    m_midTable->setItem(row, 5, new QTableWidgetItem(j::fmtTime(j::str(item, "occurred_at"))));
}

void MemoryTierPage::runConsolidate() {
    if (!ConfirmDialog::confirm(this, "触发分层流转",
                                "确认执行一轮记忆分层流转（session→mid→long + 降级）？")) return;
    m_consolidateBtn->setEnabled(false);
    const QString uid = AppContext::instance()->userId();
    Api::client()->postAsync("/api/memory/lifecycle/consolidate",
        QJsonObject{{"user_id", uid}},
        [this](const api::Result &result) {
            m_consolidateBtn->setEnabled(true);
            if (result.ok && result.hasJsonObject()) {
                const QJsonObject body = result.jsonObject();
                QMessageBox::information(this, "流转完成",
                    QString("会话汇总 %1 · 情景合并 %2 · 工具偏好 %3 · 工作流偏好 %4 · 降级 %5")
                        .arg(j::integer(body, "sessions_consolidated"))
                        .arg(j::integer(body, "episodes_consolidated"))
                        .arg(j::integer(body, "tool_preferences"))
                        .arg(j::integer(body, "workflow_preferences"))
                        .arg(j::integer(body, "degraded")));
            } else {
                QMessageBox::warning(this, "流转失败", result.errorMessage.isEmpty() ? "请求未完成" : result.errorMessage);
            }
            load();
        }, false, this);
}
