// 遗忘与生命周期 · 7 个子页完整实现

#include "ForgetPages.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPushButton>
#include <QPointer>
#include <QScrollArea>
#include <QTableWidget>
#include <QTabWidget>
#include <QVBoxLayout>

#include <QtCharts/QBarCategoryAxis>
#include <QtCharts/QBarSeries>
#include <QtCharts/QBarSet>
#include <QtCharts/QChart>
#include <QtCharts/QChartView>
#include <QtCharts/QValueAxis>

#include <algorithm>
#include <memory>
#include <QSet>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/EmptyState.h"
#include "../widgets/MemoryFilterBar.h"
#include "../widgets/PageHeader.h"
#include "../widgets/ScoreRing.h"
#include "../widgets/StatusTag.h"

// ============================================================
// P4.1 精准遗忘
// ============================================================
ForgetPrecisePage::ForgetPrecisePage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("精准遗忘");
    header->setSubtitle("自然语言 / 范围 / ID 三种方式定位记忆，预览确认后执行");
    root->addWidget(header);

    m_tabs = new QTabWidget(this);
    root->addWidget(m_tabs);

    // --- Tab1 自然语言 ---
    auto *nlTab = new QWidget();
    auto *nlLay = new QVBoxLayout(nlTab);
    auto *nlHint = new QLabel("输入自然语言遗忘指令，如：“忘掉我关于周报格式的偏好”", nlTab);
    nlHint->setObjectName("pageSubtitle");
    m_nlInput = new QLineEdit(nlTab);
    m_nlInput->setPlaceholderText("例如：忘掉我关于周报格式的偏好");
    m_nlInput->setMinimumHeight(34);
    auto *nlBtn = new QPushButton("解析并预览", nlTab);
    nlBtn->setObjectName("primaryBtn");
    connect(nlBtn, &QPushButton::clicked, this, &ForgetPrecisePage::doPreview);
    auto *nlRow = new QHBoxLayout();
    nlRow->addWidget(m_nlInput, 1);
    nlRow->addWidget(nlBtn);
    nlLay->addWidget(nlHint);
    nlLay->addLayout(nlRow);
    nlLay->addStretch();
    m_tabs->addTab(nlTab, "自然语言");

    // --- Tab2 按范围 ---
    auto *scopeTab = new QWidget();
    auto *scopeForm = new QFormLayout(scopeTab);
    m_scopeScene = new QLineEdit(scopeTab);
    m_scopeScene->setPlaceholderText("如 office");
    m_scopeTask = new QLineEdit(scopeTab);
    m_scopeTask->setPlaceholderText("如 office.weekly_report");
    m_scopeType = new QComboBox(scopeTab);
    m_scopeType->addItem("全部类型", "all");
    m_scopeType->addItem("偏好", "preference");
    m_scopeType->addItem("知识", "knowledge");
    m_scopeType->addItem("事实", "fact");
    auto *scopeBtn = new QPushButton("预览", scopeTab);
    scopeBtn->setObjectName("primaryBtn");
    connect(scopeBtn, &QPushButton::clicked, this, &ForgetPrecisePage::doPreview);
    scopeForm->addRow("场景", m_scopeScene);
    scopeForm->addRow("任务类型", m_scopeTask);
    scopeForm->addRow("类型", m_scopeType);
    scopeForm->addRow("", scopeBtn);
    scopeForm->addRow("", new QLabel("说明：按场景与类型匹配记忆进行预览", scopeTab));
    scopeForm->addItem(new QSpacerItem(0, 40, QSizePolicy::Minimum, QSizePolicy::Expanding));
    m_tabs->addTab(scopeTab, "按范围");

    // --- Tab3 按 ID ---
    auto *idTab = new QWidget();
    auto *idLay = new QVBoxLayout(idTab);
    auto *idRow = new QHBoxLayout();
    m_idType = new QComboBox(idTab);
    m_idType->addItem("全部类型", "");
    m_idType->addItem("偏好", "preference");
    m_idType->addItem("知识", "knowledge");
    m_idType->addItem("事实", "fact");
    m_idSearch = new QLineEdit(idTab);
    m_idSearch->setPlaceholderText("搜索记忆...");
    m_idSearch->setClearButtonEnabled(true);
    auto *idBtn = new QPushButton("加载列表", idTab);
    idBtn->setObjectName("primaryBtn");
    connect(idBtn, &QPushButton::clicked, this, [this]() { renderCandidates(QList<QString>()); });
    idRow->addWidget(m_idType);
    idRow->addWidget(m_idSearch, 1);
    idRow->addWidget(idBtn);
    idLay->addLayout(idRow);
    // 记忆多选列表
    m_idList = new QListWidget(idTab);
    m_idList->setSelectionMode(QAbstractItemView::MultiSelection);
    idLay->addWidget(m_idList, 1);
    m_tabs->addTab(idTab, "按 ID");

    // --- 预览结果区 ---
    m_previewContainer = new QWidget(this);
    m_previewContainer->hide();
    auto *prevLay = new QVBoxLayout(m_previewContainer);
    prevLay->setContentsMargins(0, 12, 0, 0);
    m_previewSummary = new QLabel(m_previewContainer);
    m_previewSummary->setStyleSheet("font-weight:600;color:#1F2430;");
    prevLay->addWidget(m_previewSummary);
    m_previewLayout = new QVBoxLayout();
    prevLay->addLayout(m_previewLayout);

    auto *execRow = new QHBoxLayout();
    m_cascadeCheck = new QCheckBox("级联清理（同步删向量/证据/冲突）", m_previewContainer);
    m_cascadeCheck->setChecked(true);
    m_executeBtn = new QPushButton("确认遗忘", m_previewContainer);
    m_executeBtn->setObjectName("solidDangerBtn");
    m_executeBtn->setEnabled(false);
    connect(m_executeBtn, &QPushButton::clicked, this, &ForgetPrecisePage::doExecute);
    execRow->addWidget(m_cascadeCheck);
    execRow->addStretch();
    execRow->addWidget(m_executeBtn);
    prevLay->addLayout(execRow);
    root->addWidget(m_previewContainer, 1);
}

void ForgetPrecisePage::refresh() {
    // 加载三类记忆，供 ID 定位与预览展示使用
    const int generation = ++m_generation;
    m_pendingLoads = 3;
    m_prefAll = QJsonArray();
    m_knowAll = QJsonArray();
    m_factAll = QJsonArray();
    m_loadFailures.clear();
    m_candidateIds.clear();
    m_executeInProgress = false;
    while (QLayoutItem *item = m_previewLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) { w->hide(); w->deleteLater(); }
        delete item;
    }
    m_idList->clear();
    m_previewContainer->show();
    m_previewSummary->setText("正在并行读取偏好、知识和事实记忆…");
    m_executeBtn->setEnabled(false);
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    auto finish = [this, generation](const QString &type, const api::Result &r) {
        if (generation != m_generation) return;
        if (r.ok && r.hasJsonArray()) {
            if (type == "偏好") m_prefAll = r.jsonArray();
            else if (type == "知识") m_knowAll = r.jsonArray();
            else m_factAll = r.jsonArray();
        } else {
            m_loadFailures.append(type);
        }
        if (--m_pendingLoads != 0) return;

        auto addMem = [this](const QJsonObject &m, const QString &label) {
            QString content = j::str(m, "text");
            if (content.isEmpty()) content = j::str(m, "name");
            if (content.isEmpty()) content = j::str(m, "content");
            const QString id = j::str(m, "memory_id").isEmpty() ? j::str(m, "fact_id") : j::str(m, "memory_id");
            auto *item = new QListWidgetItem(QString("[%1] %2").arg(label, content));
            item->setData(Qt::UserRole, id);
            item->setToolTip(id);
            m_idList->addItem(item);
        };
        for (const QJsonValue &v : m_prefAll) addMem(v.toObject(), "偏好");
        for (const QJsonValue &v : m_knowAll) addMem(v.toObject(), "知识");
        for (const QJsonValue &v : m_factAll) addMem(v.toObject(), "事实");
        if (m_loadFailures.isEmpty()) {
            m_previewSummary->setText(QString("可选记忆已加载：偏好 %1 · 知识 %2 · 事实 %3")
                                      .arg(m_prefAll.size()).arg(m_knowAll.size()).arg(m_factAll.size()));
        } else {
            m_previewSummary->setText(QString("部分记忆加载失败：%1。已保留成功类型，可稍后刷新重试。")
                                      .arg(m_loadFailures.join("、")));
        }
    };
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/preferences", {{"user_id", uid}}),
        [finish](const api::Result &r) { finish("偏好", r); }, this);
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge", {{"user_id", uid}}),
        [finish](const api::Result &r) { finish("知识", r); }, this);
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}}),
        [finish](const api::Result &r) { finish("事实", r); }, this);
}

QJsonObject ForgetPrecisePage::buildPreviewRequest() {
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    const int tab = m_tabs->currentIndex();
    if (tab == 0) {
        body["instruction"] = m_nlInput->text().trimmed();
    } else if (tab == 1) {
        QJsonObject scope;
        scope["scene"] = m_scopeScene->text().trimmed();
        scope["task_type"] = m_scopeTask->text().trimmed();
        body["target_scope"] = scope;
        body["memory_type"] = m_scopeType->currentData().toString();
    } else {
        QJsonArray ids;
        for (int i = 0; i < m_idList->count(); ++i) {
            QListWidgetItem *it = m_idList->item(i);
            if (it->isSelected()) ids.append(it->data(Qt::UserRole).toString());
        }
        body["target_memory_ids"] = ids;
    }
    body["cascade"] = m_cascadeCheck->isChecked();
    return body;
}

void ForgetPrecisePage::doPreview() {
    // 按 ID 模式：直接用所选 ID 作为候选（无需预览接口）
    if (m_tabs->currentIndex() == 2) {
        QList<QString> ids;
        for (int i = 0; i < m_idList->count(); ++i) {
            QListWidgetItem *it = m_idList->item(i);
            if (it->isSelected()) ids << it->data(Qt::UserRole).toString();
        }
        if (ids.isEmpty()) { QMessageBox::information(this, "提示", "请在列表中勾选要遗忘的记忆"); return; }
        m_candidateIds = ids;
        renderCandidates(ids);
        return;
    }

    const QJsonObject body = buildPreviewRequest();
    api::ApiClient *api = AppContext::instance()->api();
    const int generation = ++m_generation;
    m_executeBtn->setEnabled(false);
    m_previewSummary->setText("正在生成遗忘预览…");
    api->postAsync("/api/memory/forget/preview", body,
        [this, generation](const api::Result &r) {
            if (generation != m_generation) return;
            m_executeBtn->setEnabled(false);
            if (!r.ok || !r.hasJsonObject()) {
                m_previewSummary->setText(r.errorMessage.isEmpty() ? "预览失败" : r.errorMessage);
                return;
            }
            QList<QString> ids;
            for (const QJsonValue &v : j::arr(r.jsonObject(), "candidate_ids")) ids << v.toString();
            m_candidateIds = ids;
            renderCandidates(ids);
            const QString type = j::str(r.jsonObject(), "memory_type");
            const QString topic = j::str(r.jsonObject(), "target_topic");
            m_previewSummary->setText(QString("解析结果：类型=%1 · 主题=%2 · 匹配 %3 条")
                                      .arg(type, topic).arg(ids.size()));
        }, false, this, 10000);
}

void ForgetPrecisePage::renderCandidates(const QList<QString> &ids) {
    // 清空旧候选
    while (QLayoutItem *item = m_previewLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) w->deleteLater();
        delete item;
    }
    m_previewContainer->show();

    // 在预览区显示可勾选的候选列表（非 ID 模式时先全部勾选）
    if (m_tabs->currentIndex() == 2) {
        // 已在 ID 列表勾选，无需再次勾选
        QSet<QString> idSet = QSet<QString>(ids.begin(), ids.end());
        for (int i = 0; i < m_idList->count(); ++i) {
            m_idList->item(i)->setSelected(idSet.contains(m_idList->item(i)->data(Qt::UserRole).toString()));
        }
    }

    QTableWidget *t = new QTableWidget(int(ids.size()), 3);
    t->setHorizontalHeaderLabels({"", "内容", "类型"});
    t->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    t->verticalHeader()->setVisible(false);
    t->setEditTriggers(QAbstractItemView::NoEditTriggers);
    t->setAlternatingRowColors(true);
    t->setSelectionBehavior(QAbstractItemView::SelectRows);
    t->verticalHeader()->setDefaultSectionSize(34);

    QSet<QString> idSet = QSet<QString>(ids.begin(), ids.end());
    for (int i = 0; i < ids.size(); ++i) {
        const QString id = ids[i];
        auto *check = new QCheckBox();
        check->setChecked(true);
        check->setProperty("memoryId", id);
        t->setCellWidget(i, 0, check);
        QString content = id, type = "—";
        for (const QJsonValue &v : m_prefAll) {
            if (j::str(v.toObject(), "memory_id") == id) { content = j::str(v.toObject(), "text"); type = "偏好"; break; }
        }
        if (type == "—")
            for (const QJsonValue &v : m_knowAll) {
                if (j::str(v.toObject(), "memory_id") == id) { content = j::str(v.toObject(), "name"); type = "知识"; break; }
            }
        if (type == "—")
            for (const QJsonValue &v : m_factAll) {
                if (j::str(v.toObject(), "fact_id") == id) { content = j::str(v.toObject(), "object_value"); type = "事实"; break; }
            }
        t->setItem(i, 1, new QTableWidgetItem(content));
        t->setItem(i, 2, new QTableWidgetItem(type));
    }
    m_previewLayout->addWidget(t);
    m_executeBtn->setEnabled(true);
}

QList<QString> ForgetPrecisePage::selectedCandidateIds() const {
    // 从预览表中收集勾选项
    QList<QString> out;
    QLayoutItem *item = m_previewLayout->itemAt(0);
    if (!item) return out;
    QTableWidget *t = qobject_cast<QTableWidget *>(item->widget());
    if (!t) return out;
    for (int i = 0; i < t->rowCount(); ++i) {
        auto *check = qobject_cast<QCheckBox *>(t->cellWidget(i, 0));
        if (check && check->isChecked()) out << check->property("memoryId").toString();
    }
    return out;
}

void ForgetPrecisePage::doExecute() {
    if (m_executeInProgress) return;
    QList<QString> ids = selectedCandidateIds();
    if (ids.isEmpty() && m_tabs->currentIndex() == 2) {
        for (int i = 0; i < m_idList->count(); ++i) {
            QListWidgetItem *it = m_idList->item(i);
            if (it->isSelected()) ids << it->data(Qt::UserRole).toString();
        }
    }
    if (ids.isEmpty()) { QMessageBox::information(this, "提示", "未选择任何要遗忘的记忆"); return; }
    if (!ConfirmDialog::confirm(this, "执行遗忘",
                                QString("确认遗忘选中的 %1 条记忆？此操作不可恢复。").arg(ids.size()),
                                "确认")) {
        return;
    }
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["target_memory_ids"] = QJsonArray::fromStringList(ids);
    body["cascade"] = m_cascadeCheck->isChecked();
    api::ApiClient *api = AppContext::instance()->api();
    m_executeInProgress = true;
    m_executeBtn->setEnabled(false);
    m_executeBtn->setText("执行中…");
    api->postAsync("/api/memory/forget", body,
        [this](const api::Result &r) {
            m_executeInProgress = false;
            m_executeBtn->setText("确认遗忘");
            if (r.ok) {
                QMessageBox::information(this, "完成",
                    QString("已遗忘 %1 条，记录 ID：%2")
                        .arg(j::integer(r.jsonObject(), "deleted_count"))
                        .arg(j::str(r.jsonObject(), "record_id")));
                m_previewContainer->hide();
                m_executeBtn->setEnabled(false);
            } else {
                m_executeBtn->setEnabled(true);
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }, false, this, 15000);
}

// ============================================================
// P4.2 待审查队列
// ============================================================
namespace {
struct AsyncListState {
    int pending = 0;
    QStringList failures;
    QJsonArray preference;
    QJsonArray knowledge;
    QJsonArray fact;
};

void buildStatusTable(QTableWidget *t) {
    t->setColumnCount(6);
    t->setHorizontalHeaderLabels({"", "内容", "类型", "健康度", "状态", "操作"});
    t->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    t->verticalHeader()->setVisible(false);
    t->setEditTriggers(QAbstractItemView::NoEditTriggers);
    t->setSelectionBehavior(QAbstractItemView::SelectRows);
    t->setAlternatingRowColors(true);
    t->setColumnWidth(0, 34);
    t->setColumnWidth(2, 70);
    t->setColumnWidth(3, 90);
    t->setColumnWidth(4, 80);
    t->setColumnWidth(5, 150);
    t->verticalHeader()->setDefaultSectionSize(44);
}

QString memContent(const QJsonObject &m, const QString &type) {
    if (type == "preference") return j::str(m, "text");
    if (type == "knowledge") return j::str(m, "name");
    return j::str(m, "object_value");
}
QString memId(const QJsonObject &m, const QString &type) {
    if (type == "fact") return j::str(m, "fact_id");
    return j::str(m, "memory_id");
}
} // namespace

ForgetPendingPage::ForgetPendingPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("待审查队列");
    header->setSubtitle("健康度低于阈值待审查的记忆，可保持 / 归档 / 删除");
    m_allActive = new QPushButton("全部保持", this);
    m_allArchive = new QPushButton("全部归档", this);
    connect(m_allActive, &QPushButton::clicked, this, [this]() { batchSetStatus("active", m_allActive); });
    connect(m_allArchive, &QPushButton::clicked, this, [this]() { batchSetStatus("archived", m_allArchive); });
    header->actionLayout()->addWidget(m_allActive);
    header->actionLayout()->addWidget(m_allArchive);
    root->addWidget(header);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索待审查记忆...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &ForgetPendingPage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { /* 本地过滤 */ });
    root->addWidget(m_filterBar);

    m_table = new QTableWidget(this);
    buildStatusTable(m_table);
    root->addWidget(m_table, 1);
}

void ForgetPendingPage::refresh() { onRefresh(); }

void ForgetPendingPage::onRefresh() { loadTable(); }

void ForgetPendingPage::loadTable() {
    const int generation = ++m_generation;
    m_allActive->setEnabled(true);
    m_allArchive->setEnabled(true);
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    m_table->setRowCount(0);
    auto append = [this, kw](const QString &type, const QJsonArray &arr) {
        for (const QJsonValue &v : arr) {
            const QJsonObject m = v.toObject();
            if (!kw.isEmpty() && !memContent(m, type).contains(kw, Qt::CaseInsensitive)) continue;
            const int row = m_table->rowCount();
            m_table->insertRow(row);
            auto *check = new QCheckBox();
            check->setProperty("memoryId", memId(m, type));
            m_table->setCellWidget(row, 0, check);
            m_table->setItem(row, 1, new QTableWidgetItem(memContent(m, type)));
            m_table->setItem(row, 2, new QTableWidgetItem(type == "preference" ? "偏好"
                                                       : type == "knowledge" ? "知识" : "事实"));
            auto *health = new QLabel(QString::number(j::num(m, "health_score", 1.0), 'f', 2));
            health->setAlignment(Qt::AlignCenter);
            m_table->setCellWidget(row, 3, health);
            auto *tag = new StatusTag();
            tag->setStatus("pending");
            m_table->setCellWidget(row, 4, tag);
            auto *ops = new QWidget();
            auto *ol = new QHBoxLayout(ops);
            ol->setContentsMargins(0, 0, 0, 0);
            ol->setSpacing(2);
            auto *b1 = new QPushButton("保持", ops); b1->setObjectName("textBtn");
            auto *b2 = new QPushButton("归档", ops); b2->setObjectName("textBtn");
            auto *b3 = new QPushButton("删除", ops); b3->setStyleSheet("color:#EF4444;");
            const QString id = memId(m, type);
            connect(b1, &QPushButton::clicked, this, [this, type, id, b1]() { setSingleStatus(type, id, "active", b1); });
            connect(b2, &QPushButton::clicked, this, [this, type, id, b2]() { setSingleStatus(type, id, "archived", b2); });
            connect(b3, &QPushButton::clicked, this, [this, type, id, b3]() {
                if (ConfirmDialog::confirm(this, "删除", "确认删除该记忆?")) setSingleStatus(type, id, "deleted", b3);
            });
            ol->addWidget(b1); ol->addWidget(b2); ol->addWidget(b3);
            m_table->setCellWidget(row, 5, ops);
        }
    };

    auto state = std::make_shared<AsyncListState>();
    state->pending = 3;
    auto finish = [this, generation, state, append]() {
        if (generation != m_generation) return;
        if (--state->pending != 0) return;
        append("preference", state->preference);
        append("knowledge", state->knowledge);
        append("fact", state->fact);
        if (!state->failures.isEmpty()) {
            const int row = m_table->rowCount();
            m_table->insertRow(row);
            m_table->setItem(row, 1, new QTableWidgetItem("部分列表加载失败：" + state->failures.join("；")));
        }
    };
    auto handle = [state, finish](const QString &type, const api::Result &r) {
        if (r.ok && r.hasJsonArray()) {
            if (type == "preference") state->preference = r.jsonArray();
            else if (type == "knowledge") state->knowledge = r.jsonArray();
            else state->fact = r.jsonArray();
        } else {
            state->failures.append(type + "：" + r.errorMessage);
        }
        finish();
    };
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/preferences", {{"user_id", uid}, {"status", "pending"}}),
        [handle](const api::Result &r) { handle("preference", r); }, this);
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge", {{"user_id", uid}, {"status", "pending"}}),
        [handle](const api::Result &r) { handle("knowledge", r); }, this);
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "pending"}}),
        [handle](const api::Result &r) { handle("fact", r); }, this);
}

void ForgetPendingPage::setSingleStatus(const QString &type, const QString &id,
                                        const QString &status, QPushButton *caller) {
    if (caller) caller->setEnabled(false);
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["status"] = status;
    AppContext::instance()->api()->putAsync(
        "/api/memory/" + (type == "fact" ? QString("knowledge") : type) + "/" + id, body,
        [this, guard = QPointer<QPushButton>(caller)](const api::Result &r) {
            if (guard) guard->setEnabled(true);
            if (r.ok) {
                onRefresh();
            } else {
                QMessageBox::warning(this, "操作失败", r.errorCode + " " + r.errorMessage);
            }
        }, false, this);
}

QList<QString> ForgetPendingPage::selectedIds() const {
    QList<QString> ids;
    for (int i = 0; i < m_table->rowCount(); ++i) {
        auto *c = qobject_cast<QCheckBox *>(m_table->cellWidget(i, 0));
        if (c && c->isChecked()) ids << c->property("memoryId").toString();
    }
    return ids;
}

void ForgetPendingPage::batchSetStatus(const QString &status, QPushButton *caller) {
    const QList<QString> ids = selectedIds();
    if (ids.isEmpty()) { QMessageBox::information(this, "提示", "请先勾选记忆"); return; }
    if (caller) caller->setEnabled(false);
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["memory_ids"] = QJsonArray::fromStringList(ids);
    body["status"] = status;
    AppContext::instance()->api()->postAsync(
        "/api/memory/memories/status", body,
        [this, caller, ids](const api::Result &r) {
            if (caller) caller->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", QString("已处理 %1 / %2 条")
                    .arg(j::integer(r.jsonObject(), "applied")).arg(j::integer(r.jsonObject(), "total")));
                onRefresh();
            } else {
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }, false, this);
}

// ============================================================
// P4.3 归档仓库
// ============================================================
ForgetArchivedPage::ForgetArchivedPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("归档仓库");
    header->setSubtitle("已归档的记忆，可解除归档恢复为有效，或彻底删除");
    root->addWidget(header);
    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索已归档记忆...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &ForgetArchivedPage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { onRefresh(); });
    root->addWidget(m_filterBar);
    m_table = new QTableWidget(this);
    buildStatusTable(m_table);
    root->addWidget(m_table, 1);
}
void ForgetArchivedPage::refresh() { onRefresh(); }
void ForgetArchivedPage::onRefresh() {
    const int generation = ++m_generation;
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    m_table->setRowCount(0);
    QStringList failures;
    auto append = [&](const QString &type, const api::Result &result) {
        if (generation != m_generation) return;
        if (!result.ok || !result.hasJsonArray()) {
            failures.append(type + "：" + result.errorMessage);
            return;
        }
        const QJsonArray arr = result.jsonArray();
        for (const QJsonValue &v : arr) {
            const QJsonObject m = v.toObject();
            if (!kw.isEmpty() && !memContent(m, type).contains(kw, Qt::CaseInsensitive)) continue;
            const int row = m_table->rowCount();
            m_table->insertRow(row);
            m_table->setItem(row, 1, new QTableWidgetItem(memContent(m, type)));
            m_table->setItem(row, 2, new QTableWidgetItem(type == "preference" ? "偏好"
                                                       : type == "knowledge" ? "知识" : "事实"));
            auto *health = new QLabel(QString::number(j::num(m, "health_score", 1.0), 'f', 2));
            health->setAlignment(Qt::AlignCenter);
            m_table->setCellWidget(row, 3, health);
            auto *tag = new StatusTag();
            tag->setStatus("archived");
            m_table->setCellWidget(row, 4, tag);
            auto *ops = new QWidget();
            auto *ol = new QHBoxLayout(ops);
            ol->setContentsMargins(0, 0, 0, 0);
            ol->setSpacing(2);
            auto *b1 = new QPushButton("解除归档", ops); b1->setObjectName("textBtn");
            auto *b2 = new QPushButton("删除", ops); b2->setStyleSheet("color:#EF4444;");
            const QString id = memId(m, type);
            connect(b1, &QPushButton::clicked, this, [this, type, id]() { unarchive(type, id); });
            connect(b2, &QPushButton::clicked, this, [this, type, id]() { deleteMemory(type, id); });
            ol->addWidget(b1); ol->addWidget(b2);
            m_table->setCellWidget(row, 5, ops);
        }
    };
    append("preference", api->get(api::ApiClient::urlWithQuery(
        "/api/memory/preferences", {{"user_id", uid}, {"status", "archived"}})));
    if (generation != m_generation) return;
    append("knowledge", api->get(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge", {{"user_id", uid}, {"status", "archived"}})));
    if (generation != m_generation) return;
    append("fact", api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "archived"}})));
    if (generation != m_generation) return;
    if (!failures.isEmpty()) {
        const int row = m_table->rowCount();
        m_table->insertRow(row);
        m_table->setItem(row, 1, new QTableWidgetItem("部分列表加载失败：" + failures.join("；")));
    }
}
void ForgetArchivedPage::unarchive(const QString &type, const QString &id, QPushButton *caller) {
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["status"] = "active";
    const api::Result r = AppContext::instance()->api()->put("/api/memory/" + (type == "fact" ? QString("knowledge") : type) + "/" + id, body);
    if (r.ok) onRefresh();
    else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}
void ForgetArchivedPage::deleteMemory(const QString &type, const QString &id, QPushButton *caller) {
    if (!ConfirmDialog::confirm(this, "删除", "确认删除该归档记忆？")) return;
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["status"] = "deleted";
    const api::Result r = AppContext::instance()->api()->put("/api/memory/" + (type == "fact" ? QString("knowledge") : type) + "/" + id, body);
    if (r.ok) onRefresh();
    else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}

// ============================================================
// P4.4 回收站
// ============================================================
ForgetRecyclePage::ForgetRecyclePage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("回收站");
    header->setSubtitle("已删除（软删）的记忆，可恢复或彻底删除（物理清理）");
    root->addWidget(header);
    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索已删除记忆...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &ForgetRecyclePage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { onRefresh(); });
    root->addWidget(m_filterBar);
    m_table = new QTableWidget(this);
    buildStatusTable(m_table);
    root->addWidget(m_table, 1);
}
void ForgetRecyclePage::refresh() { onRefresh(); }
void ForgetRecyclePage::onRefresh() {
    const int generation = ++m_generation;
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    m_table->setRowCount(0);
    QStringList failures;
    auto append = [&](const QString &type, const api::Result &result) {
        if (generation != m_generation) return;
        if (!result.ok || !result.hasJsonArray()) {
            failures.append(type + "：" + result.errorMessage);
            return;
        }
        const QJsonArray arr = result.jsonArray();
        for (const QJsonValue &v : arr) {
            const QJsonObject m = v.toObject();
            if (!kw.isEmpty() && !memContent(m, type).contains(kw, Qt::CaseInsensitive)) continue;
            const int row = m_table->rowCount();
            m_table->insertRow(row);
            m_table->setItem(row, 1, new QTableWidgetItem(memContent(m, type)));
            m_table->setItem(row, 2, new QTableWidgetItem(type == "preference" ? "偏好"
                                                       : type == "knowledge" ? "知识" : "事实"));
            m_table->setItem(row, 3, new QTableWidgetItem("—"));
            auto *tag = new StatusTag();
            tag->setStatus("deleted");
            m_table->setCellWidget(row, 4, tag);
            auto *ops = new QWidget();
            auto *ol = new QHBoxLayout(ops);
            ol->setContentsMargins(0, 0, 0, 0);
            ol->setSpacing(2);
            auto *b1 = new QPushButton("恢复", ops); b1->setObjectName("textBtn");
            auto *b2 = new QPushButton("彻底删除", ops); b2->setStyleSheet("color:#EF4444;");
            const QString id = memId(m, type);
            connect(b1, &QPushButton::clicked, this, [this, type, id]() { restore(type, id); });
            connect(b2, &QPushButton::clicked, this, [this, id]() { hardDelete(id); });
            ol->addWidget(b1); ol->addWidget(b2);
            m_table->setCellWidget(row, 5, ops);
        }
    };
    append("preference", api->get(api::ApiClient::urlWithQuery(
        "/api/memory/preferences", {{"user_id", uid}, {"status", "deleted"}})));
    if (generation != m_generation) return;
    append("knowledge", api->get(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge", {{"user_id", uid}, {"status", "deleted"}})));
    if (generation != m_generation) return;
    append("fact", api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts", {{"user_id", uid}, {"status", "deleted"}})));
    if (generation != m_generation) return;
    if (!failures.isEmpty()) {
        const int row = m_table->rowCount();
        m_table->insertRow(row);
        m_table->setItem(row, 1, new QTableWidgetItem("部分列表加载失败：" + failures.join("；")));
    }
}
void ForgetRecyclePage::restore(const QString &type, const QString &id, QPushButton *caller) {
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["status"] = "active";
    const api::Result r = AppContext::instance()->api()->put("/api/memory/" + (type == "fact" ? QString("knowledge") : type) + "/" + id, body);
    if (r.ok) onRefresh();
    else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}
void ForgetRecyclePage::hardDelete(const QString &id, QPushButton *caller) {
    if (!ConfirmDialog::confirm(this, "彻底删除", "物理删除该记忆？将无法恢复。", "彻底删除")) return;
    const api::Result r = AppContext::instance()->api()->del(
        api::ApiClient::urlWithQuery("/api/memory/memories/" + id,
                                     {{"hard", "true"},
                                      {"user_id", AppContext::instance()->userId()}}));
    if (r.ok) onRefresh();
    else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}

// ============================================================
// P4.5 健康度看板
// ============================================================
ForgetHealthPage::ForgetHealthPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("健康度看板");
    header->setSubtitle("健康度 = 0.6×时间衰减 + 0.4×使用频率");
    root->addWidget(header);

    m_warningLabel = new QLabel(this);
    m_warningLabel->setObjectName("healthWarning");
    m_warningLabel->hide();
    root->addWidget(m_warningLabel);

    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto *body = new QWidget();
    auto *bl = new QVBoxLayout(body);
    bl->setContentsMargins(0, 4, 0, 4);
    scroll->setWidget(body);
    root->addWidget(scroll, 1);

    // 直方图占位
    m_listContainer = new QWidget(body);
    m_listLayout = new QVBoxLayout(m_listContainer);
    m_listLayout->setContentsMargins(0, 0, 0, 0);
    m_listLayout->setSpacing(14);
    bl->addWidget(m_listContainer);
}

void ForgetHealthPage::refresh() { loadData(); }

void ForgetHealthPage::loadData() {
    const int generation = ++m_generation;
    m_items = QJsonArray();
    m_warningLabel->hide();
    while (QLayoutItem *item = m_listLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) w->deleteLater();
        delete item;
    }
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/memories/health", {{"user_id", uid}, {"status", "active"}}));
    if (generation != m_generation) return;
    if (!r.ok || !r.hasJsonObject()) {
        m_warningLabel->setText("健康度加载失败：" + r.errorMessage);
        m_warningLabel->show();
        return;
    }
    m_items = j::arr(r.jsonObject(), "items");

    // 摘要指标
    int low = 0;
    int healthy = 0;
    double healthSum = 0.0;
    for (const QJsonValue &v : m_items) {
        const double health = j::num(v.toObject(), "health_score");
        healthSum += health;
        if (health < 0.4) ++low;
        if (health >= 0.6) ++healthy;
    }
    const double average = m_items.isEmpty() ? 0.0 : healthSum / m_items.size();

    auto *metrics = new QWidget(m_listContainer);
    auto *metricsLayout = new QGridLayout(metrics);
    metricsLayout->setContentsMargins(0, 0, 0, 0);
    metricsLayout->setHorizontalSpacing(12);
    metricsLayout->setVerticalSpacing(12);
    auto addMetric = [&](int column, const QString &caption, const QString &value,
                         const QString &hint, const QString &tone) {
        auto *card = new QFrame(metrics);
        card->setObjectName("healthMetricCard");
        auto *layout = new QVBoxLayout(card);
        layout->setContentsMargins(18, 14, 18, 14);
        layout->setSpacing(3);
        auto *captionLabel = new QLabel(caption, card);
        captionLabel->setObjectName("healthMetricCaption");
        auto *valueLabel = new QLabel(value, card);
        valueLabel->setObjectName("healthMetricValue");
        valueLabel->setProperty("tone", tone);
        auto *hintLabel = new QLabel(hint, card);
        hintLabel->setObjectName("healthMetricHint");
        layout->addWidget(captionLabel);
        layout->addWidget(valueLabel);
        layout->addWidget(hintLabel);
        metricsLayout->addWidget(card, 0, column);
    };
    addMetric(0, "活跃记忆", QString::number(m_items.size()), "纳入健康度计算", "primary");
    addMetric(1, "平均健康度", QString::number(average, 'f', 2),
              average >= 0.6 ? "整体状态良好" : average >= 0.4 ? "建议持续关注" : "需要及时处理",
              average >= 0.6 ? "good" : average >= 0.4 ? "warning" : "danger");
    addMetric(2, "健康记忆", QString::number(healthy), "健康度 ≥ 0.6", "good");
    addMetric(3, "风险记忆", QString::number(low), "健康度 < 0.4", low > 0 ? "danger" : "muted");
    for (int column = 0; column < 4; ++column) metricsLayout->setColumnStretch(column, 1);
    m_listLayout->addWidget(metrics);

    // 低健康度预警
    if (low > 0) {
        m_warningLabel->setText(QString("有 %1 条记忆进入风险区间，建议检查长期未访问或持续衰减的内容。").arg(low));
        m_warningLabel->show();
    } else m_warningLabel->hide();

    if (m_items.isEmpty()) {
        auto *emptyCard = new QFrame(m_listContainer);
        emptyCard->setObjectName("healthPanel");
        auto *emptyLayout = new QVBoxLayout(emptyCard);
        emptyLayout->setContentsMargins(24, 36, 24, 36);
        auto *empty = new EmptyState(emptyCard);
        empty->setIcon(QIcon(":/icons/activity.svg"));
        empty->setTitle(r.ok ? "暂无健康度数据" : "暂时无法读取健康度数据");
        empty->setHint(r.ok ? "产生并使用记忆后，这里会展示健康分布与衰减风险。"
                            : "请确认后端服务已启动，然后刷新页面重试。");
        emptyLayout->addWidget(empty);
        m_listLayout->addWidget(emptyCard);
        m_listLayout->addStretch();
        return;
    }

    // 直方图：四档
    int b0 = 0, b1 = 0, b2 = 0, b3 = 0;
    for (const QJsonValue &v : m_items) {
        const double h = j::num(v.toObject(), "health_score");
        if (h < 0.2) ++b0;
        else if (h < 0.4) ++b1;
        else if (h < 0.6) ++b2;
        else ++b3;
    }
    auto *chartCard = new QFrame(m_listContainer);
    chartCard->setObjectName("healthPanel");
    auto *chartLayout = new QVBoxLayout(chartCard);
    chartLayout->setContentsMargins(18, 16, 18, 14);
    chartLayout->setSpacing(2);
    auto *hist = new QLabel("健康度分布", chartCard);
    hist->setObjectName("cardTitle");
    auto *histHint = new QLabel("按健康度区间查看活跃记忆数量", chartCard);
    histHint->setObjectName("cardHint");
    chartLayout->addWidget(hist);
    chartLayout->addWidget(histHint);
    auto *set = new QtCharts::QBarSet("记忆数");
    set->setColor(QColor("#3790FA"));
    *set << b0 << b1 << b2 << b3;
    auto *series = new QtCharts::QBarSeries();
    series->append(set);
    auto *chart = new QtCharts::QChart();
    chart->addSeries(series);
    chart->setBackgroundVisible(false);
    chart->legend()->hide();
    chart->setMargins(QMargins(2, 8, 8, 2));
    series->setBarWidth(0.48);
    series->setLabelsVisible(true);
    series->setLabelsFormat("@value");
    series->setLabelsPosition(QtCharts::QAbstractBarSeries::LabelsOutsideEnd);
    auto *axisX = new QtCharts::QBarCategoryAxis();
    axisX->append({"<0.2", "0.2~0.4", "0.4~0.6", "≥0.6"});
    chart->addAxis(axisX, Qt::AlignBottom);
    series->attachAxis(axisX);
    axisX->setGridLineVisible(false);
    axisX->setLinePenColor(QColor("#DCE2EA"));
    axisX->setLabelsColor(QColor("#697180"));
    auto *axisY = new QtCharts::QValueAxis();
    axisY->setRange(0, qMax(4, qMax(qMax(b0, b1), qMax(b2, b3)) + 1));
    axisY->setTickCount(5);
    axisY->setLabelFormat("%d");
    axisY->setLabelsColor(QColor("#8B93A2"));
    axisY->setLinePenColor(Qt::transparent);
    axisY->setGridLinePen(QPen(QColor("#E9EDF3"), 1));
    chart->addAxis(axisY, Qt::AlignLeft);
    series->attachAxis(axisY);
    auto *view = new QtCharts::QChartView(chart);
    view->setRenderHint(QPainter::Antialiasing);
    view->setFrameShape(QFrame::NoFrame);
    view->setStyleSheet("background:transparent;");
    view->setFixedHeight(280);
    chartLayout->addWidget(view);
    m_listLayout->addWidget(chartCard);

    // TopN 衰减最快列表（健康度升序取前 10）
    auto *tableCard = new QFrame(m_listContainer);
    tableCard->setObjectName("healthPanel");
    auto *tableLayout = new QVBoxLayout(tableCard);
    tableLayout->setContentsMargins(18, 16, 18, 16);
    tableLayout->setSpacing(10);
    auto *topTitle = new QLabel("重点关注", tableCard);
    topTitle->setObjectName("cardTitle");
    auto *topHint = new QLabel("按健康度从低到高排列，最多展示 10 条", tableCard);
    topHint->setObjectName("cardHint");
    tableLayout->addWidget(topTitle);
    tableLayout->addWidget(topHint);
    QList<QJsonObject> sorted;
    for (const QJsonValue &v : m_items) sorted.append(v.toObject());
    std::sort(sorted.begin(), sorted.end(), [](const QJsonObject &a, const QJsonObject &b) {
        return j::num(a, "health_score") < j::num(b, "health_score");
    });
    auto *topTable = new QTableWidget(qMin(10, int(sorted.size())), 6);
    topTable->setObjectName("healthRiskTable");
    topTable->setHorizontalHeaderLabels({"内容", "类型", "健康度", "时间衰减", "使用频率", "访问"});
    topTable->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    topTable->verticalHeader()->setVisible(false);
    topTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    topTable->setSelectionBehavior(QAbstractItemView::SelectRows);
    topTable->setShowGrid(false);
    topTable->setAlternatingRowColors(true);
    topTable->verticalHeader()->setDefaultSectionSize(44);
    topTable->setColumnWidth(1, 100);
    topTable->setColumnWidth(2, 90);
    topTable->setColumnWidth(3, 110);
    topTable->setColumnWidth(4, 110);
    topTable->setColumnWidth(5, 80);
    for (int i = 0; i < topTable->rowCount(); ++i) {
        const QJsonObject m = sorted[i];
        QString content = j::str(m, "content");
        if (content.isEmpty()) content = j::str(m, "memory_id");
        topTable->setItem(i, 0, new QTableWidgetItem(content));
        auto *typeTag = new StatusTag(topTable);
        typeTag->setMemoryType(j::str(m, "memory_type"));
        topTable->setCellWidget(i, 1, typeTag);
        auto *health = new QLabel(QString::number(j::num(m, "health_score"), 'f', 2), topTable);
        health->setAlignment(Qt::AlignCenter);
        health->setProperty("healthLevel", j::num(m, "health_score") < 0.4 ? "risk"
                                           : j::num(m, "health_score") < 0.6 ? "warning" : "good");
        topTable->setCellWidget(i, 2, health);
        topTable->setItem(i, 3, new QTableWidgetItem(QString::number(j::num(m, "time_decay"), 'f', 2)));
        topTable->setItem(i, 4, new QTableWidgetItem(QString::number(j::num(m, "usage_frequency"), 'f', 2)));
        topTable->setItem(i, 5, new QTableWidgetItem(QString::number(j::integer(m, "access_count_30d"))));
        for (int column = 3; column < 6; ++column)
            topTable->item(i, column)->setTextAlignment(Qt::AlignCenter);
    }
    topTable->setFixedHeight(43 + topTable->rowCount() * 44 + 2);
    tableLayout->addWidget(topTable);
    m_listLayout->addWidget(tableCard);
    m_listLayout->addStretch();
}

// ============================================================
// P4.6 遗忘历史
// ============================================================
ForgetHistoryPage::ForgetHistoryPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("遗忘历史");
    header->setSubtitle("遗忘操作记录及其目标记忆 ID");
    root->addWidget(header);
    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索指令...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &ForgetHistoryPage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { onRefresh(); });
    root->addWidget(m_filterBar);
    m_table = new QTableWidget(this);
    m_table->setColumnCount(4);
    m_table->setHorizontalHeaderLabels({"指令", "删除数", "时间", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    m_table->setColumnWidth(3, 100);
    root->addWidget(m_table, 1);
}
void ForgetHistoryPage::refresh() { onRefresh(); }
void ForgetHistoryPage::onRefresh() {
    const int generation = ++m_generation;
    m_table->setRowCount(0);
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/forget/history", {{"user_id", uid}}));
    if (generation != m_generation) return;
    if (!r.ok || !r.hasJsonArray()) {
        m_table->setRowCount(1);
        m_table->setItem(0, 0, new QTableWidgetItem("遗忘历史加载失败：" + r.errorMessage));
        return;
    }
    int row = 0;
    for (const QJsonValue &v : r.jsonArray()) {
        const QJsonObject rec = v.toObject();
        const QString instr = j::str(rec, "instruction");
        if (!kw.isEmpty() && !instr.contains(kw, Qt::CaseInsensitive)) continue;
        m_table->insertRow(row);
        m_table->setItem(row, 0, new QTableWidgetItem(instr.isEmpty() ? "[批量删除]" : instr));
        m_table->setItem(row, 1, new QTableWidgetItem(QString::number(j::integer(rec, "deleted_count"))));
        m_table->setItem(row, 2, new QTableWidgetItem(j::fmtTime(j::str(rec, "created_at"))));
        auto *b = new QPushButton("详情");
        b->setObjectName("textBtn");
        connect(b, &QPushButton::clicked, this, [this, rec]() { openDetail(rec); });
        m_table->setCellWidget(row, 3, b);
        ++row;
    }
}
void ForgetHistoryPage::openDetail(const QJsonObject &rec) {
    const QString recordId = j::str(rec, "record_id");
    QDialog dlg(this);
    dlg.setWindowTitle("遗忘详情 · " + j::shortId(recordId));
    dlg.resize(560, 420);
    auto *lay = new QVBoxLayout(&dlg);
    auto *info = new QLabel();
    info->setTextFormat(Qt::RichText);
    info->setWordWrap(true);
    info->setStyleSheet("color:#374151;font-size:13px;line-height:1.7;");
    info->setText(QString("<b>指令</b> %1<br/><b>删除数</b> %2　<b>时间</b> %3<br/><b>记录 ID</b> %4<br/>")
                      .arg(j::str(rec, "instruction").toHtmlEscaped())
                      .arg(j::integer(rec, "deleted_count"))
                      .arg(j::fmtTime(j::str(rec, "created_at")))
                      .arg(recordId.toHtmlEscaped()));
    lay->addWidget(info);
    auto *hint = new QLabel("仅展示记录中保存的目标 ID；接口未提供目标记忆的内容或当前状态。", &dlg);
    hint->setWordWrap(true);
    lay->addWidget(hint);
    auto *memTable = new QTableWidget(0, 1);
    memTable->setHorizontalHeaderLabels({"目标记忆 ID"});
    memTable->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    memTable->verticalHeader()->setVisible(false);
    memTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    for (const QJsonValue &id : j::arr(rec, "target_memory_ids")) {
        const int row = memTable->rowCount();
        memTable->insertRow(row);
        memTable->setItem(row, 0, new QTableWidgetItem(id.toString()));
    }
    lay->addWidget(memTable, 1);
    dlg.exec();
}

// ============================================================
// P4.7 遗忘设置
// ============================================================
ForgetSettingsPage::ForgetSettingsPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("遗忘设置");
    header->setSubtitle("健康度权重 / 自动遗忘阈值 / 生命周期阈值（只读，修改需重启后端）");
    root->addWidget(header);

    auto *card = new QFrame(this);
    card->setObjectName("card");
    auto *lay = new QVBoxLayout(card);
    m_weightsLabel = new QLabel(card);
    m_autoForgetLabel = new QLabel(card);
    m_lifecycleLabel = new QLabel(card);
    for (QLabel *l : {m_weightsLabel, m_autoForgetLabel, m_lifecycleLabel}) {
        l->setTextFormat(Qt::RichText);
        l->setWordWrap(true);
        l->setStyleSheet("color:#374151;font-size:13px;line-height:1.8;");
        lay->addWidget(l);
    }
    auto *runRow = new QHBoxLayout();
    auto *autoBtn = new QPushButton("立即执行自动遗忘扫描", card);
    autoBtn->setObjectName("primaryBtn");
    auto *checkBtn = new QPushButton("执行生命周期检查", card);
    connect(autoBtn, &QPushButton::clicked, this, [this, autoBtn]() { runAutoForget(autoBtn); });
    connect(checkBtn, &QPushButton::clicked, this, [this, checkBtn]() { runLifecycleCheck(checkBtn); });
    runRow->addWidget(autoBtn);
    runRow->addWidget(checkBtn);
    runRow->addStretch();
    lay->addLayout(runRow);
    m_resultLabel = new QLabel(card);
    m_resultLabel->setWordWrap(true);
    m_resultLabel->setStyleSheet("color:#16A34A;font-size:13px;");
    lay->addWidget(m_resultLabel);
    root->addWidget(card);
    root->addStretch();
}
void ForgetSettingsPage::refresh() {
    const int generation = ++m_generation;
    m_resultLabel->clear();
    m_weightsLabel->clear();
    m_autoForgetLabel->clear();
    m_lifecycleLabel->clear();
    const api::Result r = AppContext::instance()->api()->get("/api/memory/lifecycle/settings");
    if (generation != m_generation) return;
    if (!r.ok || !r.hasJsonObject()) {
        m_resultLabel->setText("遗忘设置加载失败：" + r.errorMessage);
        return;
    }
    const QJsonObject s = r.jsonObject();
    const QJsonObject hw = j::obj(s, "health_weights");
    const QJsonObject af = j::obj(s, "auto_forget");
    const QJsonObject lc = j::obj(s, "lifecycle");
    m_weightsLabel->setText(QString("<b>健康度权重</b>：时间衰减 %1 · 使用频率 %2（代码常量）")
                                .arg(j::num(hw, "time_decay"), 0, 'f', 1)
                                .arg(j::num(hw, "usage_frequency"), 0, 'f', 1));
    m_autoForgetLabel->setText(QString("<b>自动遗忘阈值</b>：归档 <b>%1</b> · 降级 <b>%2</b> · 待审 <b>%3</b>")
                                   .arg(j::num(af, "archive_threshold"), 0, 'f', 1)
                                   .arg(j::num(af, "demote_threshold"), 0, 'f', 1)
                                   .arg(j::num(af, "review_threshold"), 0, 'f', 1));
    const QJsonObject stm = j::obj(lc, "promote_thresholds");
    const QJsonObject stm2m = j::obj(stm, "short_to_mid");
    const QJsonObject m2l = j::obj(stm, "mid_to_long");
    m_lifecycleLabel->setText(QString(
        "<b>生命周期晋升</b>：short→mid 需 %1 次且质量≥%2；mid→long 需 %3 次、置信度≥%4 且≥%5 天")
        .arg(j::integer(stm2m, "min_occurrences"))
        .arg(j::num(stm2m, "min_quality_score"), 0, 'f', 1)
        .arg(j::integer(m2l, "min_occurrences"))
        .arg(j::num(m2l, "min_confidence"), 0, 'f', 1)
        .arg(j::integer(m2l, "min_days")));
}
void ForgetSettingsPage::runAutoForget(QPushButton *caller) {
    Q_UNUSED(caller)
    const api::Result r = AppContext::instance()->api()->post("/api/memory/lifecycle/auto-forget", QJsonObject());
    if (r.ok) {
        const QJsonObject o = r.jsonObject();
        m_resultLabel->setText(QString("自动遗忘完成：归档 %1 · 降级 %2 · 待审 %3 · 保留 %4")
            .arg(j::integer(o, "archived")).arg(j::integer(o, "demoted"))
            .arg(j::integer(o, "reviewed")).arg(j::integer(o, "kept")));
    } else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}
void ForgetSettingsPage::runLifecycleCheck(QPushButton *caller) {
    Q_UNUSED(caller)
    const api::Result r = AppContext::instance()->api()->post("/api/memory/lifecycle/check", QJsonObject());
    if (r.ok) {
        const QJsonObject o = r.jsonObject();
        m_resultLabel->setText(QString("生命周期检查完成：晋升 %1 · 过期 %2 · 保留 %3")
            .arg(j::integer(o, "promoted")).arg(j::integer(o, "expired")).arg(j::integer(o, "kept")));
    } else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}
