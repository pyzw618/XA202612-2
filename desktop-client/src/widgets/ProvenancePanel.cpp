#include "ProvenancePanel.h"

#include <QHeaderView>
#include <QAbstractItemView>
#include <QJsonArray>
#include <QJsonObject>
#include <QLabel>
#include <QTableWidget>
#include <QVBoxLayout>
#include <QWidget>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"

namespace {
QTableWidget *makeTable(const QStringList &headers, QWidget *parent) {
    auto *table = new QTableWidget(0, headers.size(), parent);
    table->setHorizontalHeaderLabels(headers);
    table->horizontalHeader()->setStretchLastSection(true);
    table->verticalHeader()->setVisible(false);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setAlternatingRowColors(true);
    return table;
}

QWidget *makeTab(QLabel **state, QTableWidget **table, const QStringList &headers,
                 QWidget *parent) {
    auto *page = new QWidget(parent);
    auto *layout = new QVBoxLayout(page);
    layout->setContentsMargins(8, 8, 8, 8);
    *state = new QLabel("正在加载…", page);
    (*state)->setWordWrap(true);
    (*state)->setStyleSheet("color:#6B7280;font-size:12px;");
    *table = makeTable(headers, page);
    layout->addWidget(*state);
    layout->addWidget(*table, 1);
    return page;
}

void setFailure(QLabel *label, const api::Result &result, const QString &fallback) {
    const QString message = result.errorMessage.isEmpty() ? fallback : result.errorMessage;
    label->setText("不可用：" + message);
    label->setStyleSheet("color:#B45309;font-size:12px;");
}
} // namespace

ProvenancePanel::ProvenancePanel(const QString &memoryId, QWidget *parent)
    : QTabWidget(parent), m_memoryId(memoryId) {
    addTab(makeTab(&m_lineageState, &m_lineageTable,
                   {"动作", "语义版本", "证据修订", "父记忆", "根记忆", "时间"}, this),
           "谱系");
    addTab(makeTab(&m_evidenceState, &m_evidenceTable,
                   {"来源", "脱敏摘要", "质量", "事件", "审计", "发生时间"}, this),
           "证据");
    addTab(makeTab(&m_auditState, &m_auditTable,
                   {"审计 ID", "决策", "原因码", "发现", "脱敏", "时间"}, this),
           "审计");
    loadLineage();
    loadEvidence();
    loadAudit();
}

QString ProvenancePanel::endpoint(const QString &suffix) const {
    return api::ApiClient::urlWithQuery(
        "/api/memory/v2/memories/" + m_memoryId + "/" + suffix,
        {{"user_id", AppContext::instance()->userId()}});
}

void ProvenancePanel::loadLineage() {
    Api::client()->getAsync(endpoint("lineage"), [this](const api::Result &result) {
        if (!result.ok || !result.hasJsonObject()) {
            setFailure(m_lineageState, result, "谱系服务不可用");
            return;
        }
        const QJsonArray items = j::arr(result.jsonObject(), "items");
        m_lineageTable->setRowCount(items.size());
        for (int row = 0; row < items.size(); ++row) {
            const QJsonObject item = items.at(row).toObject();
            m_lineageTable->setItem(row, 0, new QTableWidgetItem(j::str(item, "transition_action")));
            m_lineageTable->setItem(row, 1, new QTableWidgetItem(QString::number(j::integer(item, "semantic_version"))));
            m_lineageTable->setItem(row, 2, new QTableWidgetItem(QString::number(j::integer(item, "evidence_revision"))));
            m_lineageTable->setItem(row, 3, new QTableWidgetItem(j::shortId(j::str(item, "parent_memory_id"))));
            m_lineageTable->setItem(row, 4, new QTableWidgetItem(j::shortId(j::str(item, "root_memory_id"))));
            m_lineageTable->setItem(row, 5, new QTableWidgetItem(j::fmtTime(j::str(item, "created_at"))));
        }
        m_lineageState->setText(items.isEmpty() ? "暂无谱系记录（事实记忆当前不维护版本谱系）。"
                                                 : QString("共 %1 条谱系记录").arg(items.size()));
        m_lineageState->setStyleSheet("color:#6B7280;font-size:12px;");
    }, this);
}

void ProvenancePanel::loadEvidence() {
    Api::client()->getAsync(endpoint("evidence"), [this](const api::Result &result) {
        if (!result.ok || !result.hasJsonObject()) {
            setFailure(m_evidenceState, result, "证据服务不可用");
            return;
        }
        const QJsonArray items = j::arr(result.jsonObject(), "items");
        m_evidenceTable->setRowCount(items.size());
        for (int row = 0; row < items.size(); ++row) {
            const QJsonObject item = items.at(row).toObject();
            const QString quality = j::contains(item, "quality_score")
                                        ? QString::number(j::num(item, "quality_score"), 'f', 2)
                                        : "—";
            m_evidenceTable->setItem(row, 0, new QTableWidgetItem(j::str(item, "source_type")));
            m_evidenceTable->setItem(row, 1, new QTableWidgetItem(j::str(item, "excerpt")));
            m_evidenceTable->setItem(row, 2, new QTableWidgetItem(quality));
            m_evidenceTable->setItem(row, 3, new QTableWidgetItem(j::shortId(j::str(item, "event_id"))));
            m_evidenceTable->setItem(row, 4, new QTableWidgetItem(j::shortId(j::str(item, "safety_audit_id"))));
            m_evidenceTable->setItem(row, 5, new QTableWidgetItem(j::fmtTime(j::str(item, "occurred_at"))));
        }
        m_evidenceState->setText(items.isEmpty() ? "暂无统一证据记录。" : QString("共 %1 条脱敏证据").arg(items.size()));
        m_evidenceState->setStyleSheet("color:#6B7280;font-size:12px;");
    }, this);
}

void ProvenancePanel::loadAudit() {
    Api::client()->getAsync(endpoint("audit"), [this](const api::Result &result) {
        if (!result.ok || !result.hasJsonObject()) {
            setFailure(m_auditState, result,
                       result.errorCode == "safety.audit_disabled" ? "审计功能未启用" : "审计服务不可用");
            return;
        }
        const QJsonArray items = j::arr(result.jsonObject(), "items");
        m_auditTable->setRowCount(items.size());
        for (int row = 0; row < items.size(); ++row) {
            const QJsonObject item = items.at(row).toObject();
            m_auditTable->setItem(row, 0, new QTableWidgetItem(j::shortId(j::str(item, "audit_id"))));
            m_auditTable->setItem(row, 1, new QTableWidgetItem(j::str(item, "decision")));
            m_auditTable->setItem(row, 2, new QTableWidgetItem(j::strList(item, "reason_codes").join(", ")));
            m_auditTable->setItem(row, 3, new QTableWidgetItem(QString::number(j::integer(item, "finding_count"))));
            m_auditTable->setItem(row, 4, new QTableWidgetItem(QString::number(j::integer(item, "redaction_count"))));
            m_auditTable->setItem(row, 5, new QTableWidgetItem(j::fmtTime(j::str(item, "created_at"))));
        }
        m_auditState->setText(items.isEmpty() ? "该记忆没有关联审计记录。" : QString("共 %1 条关联审计记录").arg(items.size()));
        m_auditState->setStyleSheet("color:#6B7280;font-size:12px;");
    }, this);
}
