#include "VNextDashboardPages.h"

#include <QFormLayout>
#include <QHeaderView>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"

namespace {
struct ViewSpec { const char *title; const char *subtitle; const char *endpoint; };
ViewSpec spec(VNextDashboardPage::View view) {
    switch (view) {
    case VNextDashboardPage::View::Explorer: return {"Memory Explorer", "Evidence · Lineage · Activation", "explorer"};
    case VNextDashboardPage::View::Evolution: return {"Evolution", "Formation · Evolution · Forget", "evolution"};
    case VNextDashboardPage::View::RetrievalDebugger: return {"Retrieval Debugger", "Intent · Score · Scope · Budget", "retrieval_debugger"};
    case VNextDashboardPage::View::Benchmark: return {"Benchmark", "Reproducible metric summary", "benchmark"};
    }
    return {"Dashboard", "", "explorer"};
}
QString compact(const QJsonValue &value) {
    if (value.isString()) return value.toString();
    if (value.isObject()) return QString::fromUtf8(QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact));
    if (value.isArray()) return QString::fromUtf8(QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact));
    return QString();
}

QJsonArray benchmarkItems(const QJsonObject &data) {
    QJsonArray rows;
    const QJsonObject layers = data.value("layers").toObject();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        rows.append(QJsonObject{{"trace_id", it.key()}, {"category", "evaluation layer"},
                                {"metrics", it.value()}});
    }
    const QJsonObject infrastructure = data.value("infrastructure_metrics").toObject();
    if (!infrastructure.isEmpty()) {
        rows.append(QJsonObject{{"trace_id", "infrastructure"}, {"category", "runtime metrics"},
                                {"metrics", infrastructure}});
    }
    return rows;
}
}

VNextDashboardPage::VNextDashboardPage(View view, QWidget *parent) : BasePage(parent), m_view(view) {
    const ViewSpec current = spec(view);
    auto *layout = new QVBoxLayout(this);
    auto *header = new PageHeader(this);
    header->setTitle(current.title);
    header->setSubtitle(current.subtitle);
    auto *refreshButton = new QPushButton("Refresh", header);
    refreshButton->setObjectName("primaryButton");
    header->actionLayout()->addWidget(refreshButton);
    connect(refreshButton, &QPushButton::clicked, this, &VNextDashboardPage::refresh);
    layout->addWidget(header);
    auto *credentials = new QFormLayout();
    m_tenant = new QLineEdit(this);
    m_tenant->setPlaceholderText("Tenant ID");
    m_adminToken = new QLineEdit(this);
    m_adminToken->setPlaceholderText("Administrator authorization for this session");
    m_adminToken->setEchoMode(QLineEdit::Password);
    credentials->addRow("Tenant", m_tenant);
    credentials->addRow("Admin authorization", m_adminToken);
    layout->addLayout(credentials);
    m_summary = new QLabel(this);
    m_summary->setWordWrap(true);
    layout->addWidget(m_summary);
    m_state = new PageStateView(this);
    layout->addWidget(m_state);
    m_table = new QTableWidget(0, 3, this);
    m_table->setHorizontalHeaderLabels({"Trace", "Category / status", "Links / metrics"});
    m_table->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    layout->addWidget(m_table, 1);
    m_state->setState(PageState::Empty, "Credentials required", "Enter tenant and administrator authorization, then refresh.");
}

void VNextDashboardPage::refresh() {
    const QString tenant = m_tenant->text().trimmed();
    const QString token = m_adminToken->text().trimmed();
    if (tenant.isEmpty() || token.isEmpty()) {
        m_table->setRowCount(0);
        m_state->setState(PageState::Empty, "Credentials required", "This management view never guesses credentials.");
        return;
    }
    const int generation = ++m_generation;
    m_state->setState(PageState::Loading, "Loading redacted projection", "No management write is performed.");
    m_table->setRowCount(0);
    api::ApiClient *client = AppContext::instance()->api();
    client->setVNextManagementCredentials(tenant, token);
    const QJsonObject body{{"api_version", "vnext/v1"}, {"request_id", QString("desktop-%1-%2").arg(spec(m_view).endpoint).arg(generation)},
                           {"tenant_id", tenant}, {"user_id", AppContext::instance()->userId()}};
    client->postAsync(QString("/api/memory/vnext/dashboard/%1").arg(spec(m_view).endpoint), body,
        [this, generation](const api::Result &result) {
            if (generation != m_generation) return;
            if (!result.ok || !result.hasJsonObject()) {
                m_state->setState(result.networkError ? PageState::Offline : PageState::Error,
                                  result.networkError ? "Backend offline" : "Projection unavailable",
                                  result.errorMessage.isEmpty() ? "Check authorization and service state." : result.errorMessage);
                m_state->setAction("Retry", [this]() { refresh(); });
                return;
            }
            const QJsonObject data = result.jsonObject().value("data").toObject();
            const QJsonArray items = m_view == View::Benchmark
                ? benchmarkItems(data) : data.value("items").toArray();
            const QString runner = m_view == View::Benchmark
                ? QString(" · runner %1").arg(j::str(data, "runner_version", "unavailable")) : QString();
            m_summary->setText(QString("Redacted projection · %1 item(s)%2").arg(items.size()).arg(runner));
            m_table->setRowCount(items.size());
            for (int row = 0; row < items.size(); ++row) {
                const QJsonObject item = items[row].toObject();
                m_table->setItem(row, 0, new QTableWidgetItem(j::str(item, "trace_id")));
                const QString category = j::str(item, "category", j::str(item.value("classification").toObject(), "intent"));
                m_table->setItem(row, 1, new QTableWidgetItem(category));
                const QJsonValue details = item.contains("scores") ? item.value("scores")
                    : item.contains("links") ? item.value("links")
                    : item.contains("metrics") ? item.value("metrics") : item.value("ids");
                m_table->setItem(row, 2, new QTableWidgetItem(compact(details)));
            }
            if (items.isEmpty()) m_state->setState(PageState::Empty, "No visible records", "The authorized tenant/user has no redacted projection data.");
            else m_state->setState(PageState::Content, QString(), QString());
        }, true, this);
}

QString VNextDashboardPage::pageKey() const {
    switch (m_view) {
    case View::Explorer: return "dashboard/explorer";
    case View::Evolution: return "dashboard/evolution";
    case View::RetrievalDebugger: return "dashboard/retrieval";
    case View::Benchmark: return "dashboard/benchmark";
    }
    return "dashboard";
}
