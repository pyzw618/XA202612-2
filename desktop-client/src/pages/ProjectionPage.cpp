#include "ProjectionPage.h"

#include <QComboBox>
#include <QAbstractItemView>
#include <QItemSelectionModel>
#include <QHeaderView>
#include <QJsonObject>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"

ProjectionPage::ProjectionPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("投影恢复");
    header->setSubtitle("查看记忆索引投影队列；重放只重新入队失败项，不会重复写入业务记忆。");
    auto *refresh = new QPushButton("刷新", header);
    refresh->setObjectName("primaryBtn");
    connect(refresh, &QPushButton::clicked, this, &ProjectionPage::load);
    header->actionLayout()->addWidget(refresh);
    root->addWidget(header);

    auto *body = new QWidget(this);
    auto *layout = new QVBoxLayout(body);
    layout->setContentsMargins(24, 18, 24, 24);
    layout->setSpacing(12);

    auto *toolbar = new QHBoxLayout();
    toolbar->addWidget(new QLabel("队列状态", body));
    m_status = new QComboBox(body);
    m_status->addItem("待投影", "pending");
    m_status->addItem("投影失败", "failed");
    toolbar->addWidget(m_status);
    m_summary = new QLabel(body);
    m_summary->setStyleSheet("color:#6B7280;");
    toolbar->addWidget(m_summary, 1);
    m_replaySelected = new QPushButton("重放选中失败项", body);
    m_replayAll = new QPushButton("重放全部失败项", body);
    m_replaySelected->setObjectName("primaryBtn");
    m_replayAll->setObjectName("primaryBtn");
    m_replaySelected->setEnabled(false);
    m_replayAll->setEnabled(false);
    toolbar->addWidget(m_replaySelected);
    toolbar->addWidget(m_replayAll);
    layout->addLayout(toolbar);

    m_table = new QTableWidget(0, 8, body);
    m_table->setHorizontalHeaderLabels({"状态", "记忆", "类型", "操作", "尝试", "下次重试", "错误码", "更新时间"});
    m_table->horizontalHeader()->setStretchLastSection(true);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_table->setAlternatingRowColors(true);
    layout->addWidget(m_table, 1);

    m_state = new PageStateView(body);
    layout->addWidget(m_state);
    root->addWidget(body, 1);

    connect(m_status, qOverload<int>(&QComboBox::currentIndexChanged), this, &ProjectionPage::load);
    connect(m_replaySelected, &QPushButton::clicked, this, &ProjectionPage::replaySelected);
    connect(m_replayAll, &QPushButton::clicked, this, &ProjectionPage::replayAllFailed);
}

void ProjectionPage::refresh() { load(); }

void ProjectionPage::load() {
    const int generation = ++m_generation;
    const QString status = m_status->currentData().toString();
    m_state->setState(PageState::Loading, "正在加载投影队列", QString());
    m_replaySelected->setEnabled(false);
    m_replayAll->setEnabled(false);
    m_table->setRowCount(0);
    Api::client()->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/v2/projections",
        {{"user_id", AppContext::instance()->userId()}, {"status", status}, {"limit", "200"}}),
        [this, generation, status](const api::Result &result) {
            if (generation != m_generation) return;
            if (!result.ok || !result.hasJsonObject()) {
                m_summary->setText("加载失败");
                m_state->setState(result.networkError ? PageState::Offline : PageState::Error,
                                  result.networkError ? "后端离线" : "投影队列加载失败",
                                  result.errorMessage.isEmpty() ? "请稍后重试。" : result.errorMessage);
                return;
            }
            m_items = j::arr(result.jsonObject(), "items");
            m_table->setRowCount(m_items.size());
            for (int row = 0; row < m_items.size(); ++row) {
                const QJsonObject item = m_items.at(row).toObject();
                auto *statusItem = new QTableWidgetItem(j::str(item, "status"));
                statusItem->setData(Qt::UserRole, j::str(item, "outbox_id"));
                m_table->setItem(row, 0, statusItem);
                m_table->setItem(row, 1, new QTableWidgetItem(j::shortId(j::str(item, "memory_id"))));
                m_table->setItem(row, 2, new QTableWidgetItem(j::str(item, "memory_type")));
                m_table->setItem(row, 3, new QTableWidgetItem(j::str(item, "operation")));
                m_table->setItem(row, 4, new QTableWidgetItem(QString::number(j::integer(item, "attempts"))));
                m_table->setItem(row, 5, new QTableWidgetItem(j::fmtTime(j::str(item, "next_retry_at"))));
                m_table->setItem(row, 6, new QTableWidgetItem(j::str(item, "error_code")));
                m_table->setItem(row, 7, new QTableWidgetItem(j::fmtTime(j::str(item, "updated_at"))));
            }
            const bool failed = status == "failed";
            m_replaySelected->setEnabled(failed && !m_items.isEmpty());
            m_replayAll->setEnabled(failed && !m_items.isEmpty());
            m_summary->setText(m_items.isEmpty() ? "当前没有符合条件的投影任务。"
                                                  : QString("共 %1 条 %2 任务").arg(m_items.size()).arg(failed ? "失败" : "待处理"));
            m_state->setState(PageState::Content, QString(), QString());
        }, this);
}

QJsonArray ProjectionPage::selectedOutboxIds() const {
    QJsonArray ids;
    for (const QModelIndex &index : m_table->selectionModel()->selectedRows()) {
        if (auto *item = m_table->item(index.row(), 0)) ids.append(item->data(Qt::UserRole).toString());
    }
    return ids;
}

void ProjectionPage::replaySelected() {
    const QJsonArray ids = selectedOutboxIds();
    if (ids.isEmpty()) {
        QMessageBox::information(this, "提示", "请先选择至少一条失败投影任务。");
        return;
    }
    replay(ids, false);
}

void ProjectionPage::replayAllFailed() { replay(QJsonArray(), true); }

void ProjectionPage::replay(const QJsonArray &outboxIds, bool allFailed) {
    const QString target = allFailed ? "当前用户的全部失败投影任务"
                                     : QString("选中的 %1 条失败投影任务").arg(outboxIds.size());
    if (!ConfirmDialog::confirm(this, "确认重放", "确认重新入队" + target + "？\n不会重复写入记忆记录。")) return;
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    if (!allFailed) body["outbox_ids"] = outboxIds;
    m_replaySelected->setEnabled(false);
    m_replayAll->setEnabled(false);
    Api::client()->postAsync("/api/memory/v2/projections/replay", body,
        [this](const api::Result &result) {
            if (!result.ok || !result.hasJsonObject()) {
                QMessageBox::warning(this, "重放失败", result.errorMessage.isEmpty() ? "请求未完成" : result.errorMessage);
            } else {
                QMessageBox::information(this, "已重新入队",
                                         QString("已重放 %1 条投影任务。").arg(j::integer(result.jsonObject(), "requeued")));
            }
            load();
        }, false, this);
}
