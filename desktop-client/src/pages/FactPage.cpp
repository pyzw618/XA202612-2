#include "FactPage.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QFrame>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPointer>
#include <QPushButton>
#include <QStringList>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/DetailDrawer.h"
#include "../widgets/ProvenancePanel.h"
#include "../widgets/JsonViewer.h"
#include "../widgets/MemoryFilterBar.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"
#include "../widgets/RoundedContainer.h"
#include "../widgets/StatusTag.h"

namespace {
QString tripleText(const QJsonObject &f) {
    // /facts 兼容接口返回 canonical subject/predicate/object_value；同时兼容旧字段。
    QString s = j::str(f, "subject_text");
    QString p = j::str(f, "predicate_text");
    QString o = j::str(f, "object_value");
    if (s.isEmpty()) s = j::str(f, "subject");
    if (p.isEmpty()) p = j::str(f, "predicate");
    if (o.isEmpty()) o = j::str(f, "object_text");
    if (s.isEmpty()) s = j::str(f, "subject_id");
    if (p.isEmpty()) p = j::str(f, "predicate_id");
    if (o.isEmpty()) o = j::str(f, "object_id");
    QStringList parts;
    for (const QString &part : {s, p, o}) {
        if (!part.trimmed().isEmpty()) parts.append(part.trimmed());
    }
    if (parts.size() >= 2) return parts.join(QStringLiteral(" → "));

    // Historical rows may contain only a statement/source_text. Do not render
    // misleading empty arrows for those unstructured records.
    const QString source = j::str(f, "source_text").trimmed();
    return !source.isEmpty() ? source : (parts.isEmpty() ? QStringLiteral("—") : parts.first());
}
} // namespace

FactPage::FactPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Fixed);
    header->setTitle("事实记忆");
    header->setSubtitle("知识图谱三元组（主语 → 谓词 → 宾语），支持人工提案与裁决");
    m_proposeBtn = new QPushButton(QIcon(":/icons/plus.svg"), "手动提交三元组", this);
    m_proposeBtn->setObjectName("primaryBtn");
    connect(m_proposeBtn, &QPushButton::clicked, this, &FactPage::openProposeDialog);
    header->actionLayout()->addWidget(m_proposeBtn);
    root->addWidget(header);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    m_filterBar->setSearchPlaceholder("搜索三元组 / 来源...");
    m_scopeCombo = new QComboBox(this);
    m_scopeCombo->addItem("全部作用域", "");
    m_scopeCombo->addItem("全局 global", "global");
    m_scopeCombo->addItem("项目 project", "project");
    m_statusCombo = new QComboBox(this);
    // 后端合法状态：active/pending/archived/deleted（database.py 按状态等值查询）；
    // "全部"对应 /facts 的 status=all
    m_statusCombo->addItem("全部", "all");
    m_statusCombo->addItem(StatusTag::statusText("active"), "active");
    m_statusCombo->addItem(StatusTag::statusText("pending"), "pending");
    m_statusCombo->addItem(StatusTag::statusText("archived"), "archived");
    m_statusCombo->addItem(StatusTag::statusText("deleted"), "deleted");
    m_filterBar->addWidget(m_scopeCombo);
    m_filterBar->addWidget(m_statusCombo);
    m_filterBar->addStretch();
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &FactPage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this, &FactPage::applyLocalFilter);
    connect(m_scopeCombo, qOverload<int>(&QComboBox::currentIndexChanged), this,
            &FactPage::applyLocalFilter);
    connect(m_statusCombo, qOverload<int>(&QComboBox::currentIndexChanged), this,
            &FactPage::onRefresh);
    root->addWidget(m_filterBar);

    m_stateView = new PageStateView(this);
    m_stateView->hide();
    // 表格隐藏时，由状态视图独占剩余高度，避免头部与筛选栏被拉伸。
    root->addWidget(m_stateView, 1);
    auto *content = new RoundedContainer(this);
    m_content = content;
    content->setObjectName("dataTableContainer");
    auto *clay = new QHBoxLayout(content);
    clay->setContentsMargins(2, 2, 2, 2);
    clay->setSpacing(0);

    m_table = new QTableWidget(0, 6, content);
    m_table->setHorizontalHeaderLabels({"三元组", "置信度", "作用域", "状态", "访问", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setColumnWidth(1, 72);
    m_table->setColumnWidth(2, 110);
    m_table->setColumnWidth(3, 80);
    m_table->setColumnWidth(4, 60);
    m_table->setColumnWidth(5, 170);
    m_table->verticalHeader()->setDefaultSectionSize(44);
    clay->addWidget(m_table, 1);

    m_drawer = new DetailDrawer(content);
    m_drawer->setWidth(560);
    clay->addWidget(m_drawer);

    root->addWidget(content, 1);
}

void FactPage::refresh() { onRefresh(); }

void FactPage::onRefresh() {
    ++m_detailGeneration;
    m_proposeBtn->setEnabled(true);
    m_drawer->closeDrawer();
    m_all = QJsonArray();
    m_table->setRowCount(0);
    const int generation = ++m_generation;
    m_content->hide();
    m_stateView->setState(PageState::Loading, "正在加载事实记忆", "正在从后端读取真实数据…");
    m_stateView->clearAction();
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString status = m_statusCombo->currentData().toString();
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/facts",
        {{"user_id", uid}, {"status", status.isEmpty() ? "active" : status}, {"limit", "500"}}),
        [this, generation](const api::Result &r) {
            if (generation != m_generation) return;
            if (!r.ok || !r.hasJsonArray()) {
                m_content->setVisible(!m_all.isEmpty());
                m_stateView->setState(r.networkError ? PageState::Offline : PageState::Error,
                                      r.networkError ? "后端离线" : "事实记忆加载失败",
                                      r.errorMessage.isEmpty() ? "请稍后重试。" : r.errorMessage);
                m_stateView->setAction("重试", [this]() { onRefresh(); });
                return;
            }
            m_all = r.jsonArray();
            m_content->setVisible(!m_all.isEmpty());
            if (m_all.isEmpty()) {
                m_stateView->setState(PageState::Empty, "暂无事实记忆", "当前接口返回了空数据。");
                m_stateView->setAction("刷新", [this]() { onRefresh(); });
            } else if (m_all.size() >= 500) {
                // /facts 上限 500：达到上限时如实提示可能截断
                m_stateView->setState(PageState::Content,
                                      "已达单次加载上限（500 条）", "可能存在未展示的事实，请缩小筛选范围。");
            } else {
                m_stateView->setState(PageState::Content, QString(), QString());
            }
            applyLocalFilter();
        }, this);
}

void FactPage::applyLocalFilter() {
    const QString scope = m_scopeCombo->currentData().toString();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    QList<QJsonObject> filtered;
    for (const QJsonValue &v : m_all) {
        const QJsonObject f = v.toObject();
        if (!scope.isEmpty() && j::str(f, "scope") != scope) continue;
        if (!kw.isEmpty() && !tripleText(f).contains(kw, Qt::CaseInsensitive) &&
            !j::str(f, "source_text").contains(kw, Qt::CaseInsensitive))
            continue;
        filtered.append(f);
    }
    m_table->setRowCount(0);
    m_table->setRowCount(int(filtered.size()));
    for (int i = 0; i < filtered.size(); ++i) populateRow(i, filtered[i]);
}

void FactPage::populateRow(int row, const QJsonObject &f) {
    const QString id = j::str(f, "fact_id");
    auto *triple = new QLabel(tripleText(f));
    triple->setToolTip(j::str(f, "source_text"));
    triple->setTextInteractionFlags(Qt::TextSelectableByMouse);
    triple->setStyleSheet("border:none;");
    m_table->setCellWidget(row, 0, triple);

    auto *conf = new QLabel(QString::number(j::num(f, "confidence"), 'f', 2));
    conf->setAlignment(Qt::AlignCenter);
    conf->setStyleSheet(QString("color:%1;font-weight:600;")
                            .arg(j::num(f, "confidence") >= 0.6 ? "#16A34A"
                                 : j::num(f, "confidence") >= 0.4 ? "#D97706" : "#DC2626"));
    m_table->setCellWidget(row, 1, conf);

    m_table->setItem(row, 2, new QTableWidgetItem(j::str(f, "scope", "—")));

    auto *statusTag = new StatusTag();
    statusTag->setStatus(j::str(f, "status"));
    m_table->setCellWidget(row, 3, statusTag);

    m_table->setItem(row, 4, new QTableWidgetItem(QString::number(j::integer(f, "access_count_30d"))));

    auto *ops = new QWidget();
    auto *ol = new QHBoxLayout(ops);
    ol->setContentsMargins(0, 0, 0, 0);
    ol->setSpacing(2);
    auto mk = [ops](const QString &t) { auto *b = new QPushButton(t, ops); b->setObjectName("textBtn"); return b; };
    auto *bDetail = mk("详情");
    auto *bEdit = mk("编辑");
    auto *bDelete = mk("删除");
    bDelete->setStyleSheet("color:#EF4444;");
    connect(bDetail, &QPushButton::clicked, this, [this, id]() { openDetail(id); });
    connect(bEdit, &QPushButton::clicked, this, [this, f]() { openEditDialog(f); });
    connect(bDelete, &QPushButton::clicked, this, [this, f, bDelete]() {
        if (!ConfirmDialog::confirm(this, "删除事实", "确认删除这条事实三元组？")) return;
        QPointer<QPushButton> guard(bDelete);
        bDelete->setEnabled(false);
        const QString factId = j::str(f, "fact_id");
        const QString uid = AppContext::instance()->userId();
        AppContext::instance()->api()->deleteAsync(
            api::ApiClient::urlWithQuery("/api/memory/facts/" + factId,
                                         {{"user_id", uid}}),
            [this, guard](const api::Result &r) {
                if (guard) guard->setEnabled(true);
                if (r.ok) {
                    QMessageBox::information(this, "完成", "已删除");
                    onRefresh();
                } else if (r.errorCode == "memory.safety.review_required") {
                    QMessageBox::warning(this, "需人工复核", "删除需人工复核。");
                } else if (r.errorCode == "memory.safety.rejected") {
                    QMessageBox::warning(this, "被策略拒绝", "删除被安全策略拒绝。");
                } else {
                    QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
                }
            }, false, this);
    });
    ol->addWidget(bDetail);
    ol->addWidget(bEdit);
    ol->addWidget(bDelete);
    m_table->setCellWidget(row, 5, ops);
}

void FactPage::openDetail(const QString &id) {
    api::ApiClient *api = AppContext::instance()->api();
    const QString uid = AppContext::instance()->userId();
    const int generation = ++m_detailGeneration;

    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/facts/" + id, {{"user_id", uid}}),
        [this, generation, id, uid, api](const api::Result &r) {
            if (generation != m_detailGeneration) return;
            if (!r.ok || !r.hasJsonObject()) {
                QMessageBox::warning(this, "加载失败", r.errorCode + " " + r.errorMessage);
                return;
            }
            const QJsonObject f = r.jsonObject();

            auto *tabs = new QTabWidget(m_drawer);
            connect(AppContext::instance(), &AppContext::userIdChanged, tabs, &QObject::deleteLater);
            auto *info = new QWidget();
            auto *il = new QVBoxLayout(info);
            auto *label = new QLabel();
            label->setTextFormat(Qt::RichText);
            label->setWordWrap(true);
            label->setStyleSheet("color:#374151;font-size:13px;line-height:1.7;");
            QString html;
            html += QString("<b>三元组</b><br/><div style='font-size:15px;color:#1F2430;'>%1</div><br/>")
                        .arg(tripleText(f).toHtmlEscaped());
            html += QString("<b>置信度</b> %1　<b>版本</b> %2<br/>")
                        .arg(QString::number(j::num(f, "confidence"), 'f', 2))
                        .arg(j::integer(f, "version"));
            html += QString("<b>作用域</b> %1　<b>项目</b> %2<br/>")
                        .arg(j::str(f, "scope"), j::str(f, "project_id").isEmpty() ? "—" : j::str(f, "project_id"));
            html += QString("<b>来源文本</b><br/>%1<br/><br/>").arg(j::str(f, "source_text").toHtmlEscaped());
            html += QString("<b>观察时间</b> %1<br/>").arg(j::fmtTime(j::str(f, "observed_at")));
            label->setText(html);
            il->addWidget(label);
            il->addStretch();
            tabs->addTab(info, "事实");

            // 证据
            api->getAsync(api::ApiClient::urlWithQuery(
                "/api/memory/facts/" + id + "/evidence", {{"user_id", uid}}),
                [this, generation, id, tabs, api](const api::Result &rev) {
                    if (generation != m_detailGeneration) {
                        tabs->deleteLater();
                        return;
                    }
                    auto *evW = new QWidget();
                    auto *el = new QVBoxLayout(evW);
                    auto *evT = new QTableWidget(0, 3);
                    evT->setHorizontalHeaderLabels({"时间", "事件", "内容"});
                    evT->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
                    evT->verticalHeader()->setVisible(false);
                    evT->setEditTriggers(QAbstractItemView::NoEditTriggers);
                    if (rev.ok && rev.hasJsonArray()) {
                        const QJsonArray evs = rev.jsonArray();
                        evT->setRowCount(int(evs.size()));
                        for (int i = 0; i < evs.size(); ++i) {
                            const QJsonObject e = evs[i].toObject();
                            evT->setItem(i, 0, new QTableWidgetItem(j::timeAgo(j::str(e, "timestamp"))));
                            evT->setItem(i, 1, new QTableWidgetItem(j::str(e, "event_id")));
                            evT->setItem(i, 2, new QTableWidgetItem(j::str(e, "content")));
                        }
                    } else {
                        el->addWidget(new QLabel("证据加载失败：" + rev.errorMessage, evW));
                    }
                    el->addWidget(evT);
                    tabs->addTab(evW, "证据");
                    tabs->addTab(new ProvenancePanel(id, tabs), "统一溯源");
                    m_drawer->open(j::shortId(id), tabs);
                }, tabs);
        }, this);
}

void FactPage::openEditDialog(const QJsonObject &fact) {
    QDialog dlg(this);
    dlg.setWindowTitle("编辑事实元数据（三元组内容不可修改）");
    auto *form = new QFormLayout(&dlg);
    auto *confidence = new QDoubleSpinBox(&dlg);
    confidence->setRange(0.0, 1.0);
    confidence->setDecimals(2);
    confidence->setSingleStep(0.05);
    confidence->setValue(j::num(fact, "confidence", 0.7));
    form->addRow("置信度", confidence);
    auto *status = new QComboBox(&dlg);
    for (const auto &entry : {qMakePair(QStringLiteral("active"), QStringLiteral("active")),
                              qMakePair(QStringLiteral("pending"), QStringLiteral("pending")),
                              qMakePair(QStringLiteral("archived"), QStringLiteral("archived")),
                              qMakePair(QStringLiteral("deleted"), QStringLiteral("deleted"))})
        status->addItem(StatusTag::statusText(entry.second), entry.second);
    const int index = status->findData(j::str(fact, "status", "active"));
    status->setCurrentIndex(index >= 0 ? index : 0);
    form->addRow("状态", status);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel | QDialogButtonBox::Ok, &dlg);
    buttons->button(QDialogButtonBox::Ok)->setText("保存");
    connect(buttons, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(buttons);
    if (dlg.exec() != QDialog::Accepted) return;
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["confidence"] = confidence->value();
    body["status"] = status->currentData().toString();
    const QString id = j::str(fact, "fact_id", j::str(fact, "memory_id"));
    m_proposeBtn->setEnabled(false);
    AppContext::instance()->api()->putAsync("/api/memory/knowledge/" + id, body,
        [this](const api::Result &r) {
            m_proposeBtn->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", "事实元数据已更新（三元组内容保持不变）");
                onRefresh();
            } else {
                QMessageBox::warning(this, "保存失败", r.errorCode + " " + r.errorMessage);
            }
        }, false, this);
}

void FactPage::openProposeDialog() {
    // Evidence and project scope are part of the persisted fact contract.
    QDialog dlg(this);
    auto *scope = new QComboBox(&dlg);
    scope->addItem("global", "global");
    scope->addItem("project", "project");
    auto *project = new QLineEdit(&dlg);
    auto *evidence = new QPlainTextEdit(&dlg);
    project->setEnabled(false);
    connect(scope, qOverload<int>(&QComboBox::currentIndexChanged), &dlg,
            [project](int index) { project->setEnabled(index == 1); });
    dlg.setWindowTitle("手动提交三元组");
    dlg.setMinimumWidth(520);
    auto *form = new QFormLayout(&dlg);

    form->addRow("作用域", scope);
    form->addRow("项目 ID", project);
    form->addRow("证据 *", evidence);
    auto *sEdit = new QLineEdit(&dlg);
    sEdit->setPlaceholderText("如：张三");
    form->addRow("主语 *", sEdit);
    auto *pEdit = new QLineEdit(&dlg);
    pEdit->setPlaceholderText("如：就职于");
    form->addRow("谓词 *", pEdit);
    auto *oEdit = new QLineEdit(&dlg);
    oEdit->setPlaceholderText("如：银河麒麟软件有限公司");
    form->addRow("宾语 *", oEdit);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel | QDialogButtonBox::Ok, &dlg);
    buttons->button(QDialogButtonBox::Ok)->setText("提交提案");
    buttons->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(buttons, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(buttons);

    if (dlg.exec() != QDialog::Accepted) return;
    if (sEdit->text().trimmed().isEmpty() || pEdit->text().trimmed().isEmpty() ||
        oEdit->text().trimmed().isEmpty() || evidence->toPlainText().trimmed().isEmpty() ||
        (scope->currentData().toString() == "project" && project->text().trimmed().isEmpty())) {
        QMessageBox::warning(this, "提示", "主语、谓词、宾语和证据均不能为空；项目作用域还必须提供项目 ID。");
        return;
    }

    QJsonObject triple;
    triple["subject_text"] = sEdit->text().trimmed();
    triple["predicate_text"] = pEdit->text().trimmed();
    triple["object_text"] = oEdit->text().trimmed();
    triple["confidence"] = 1.0;
    triple["evidence"] = evidence->toPlainText().trimmed();

    QJsonObject body;
    // 列表与总览都按当前用户查询；提交必须使用同一 user_id，不能落入后端默认用户。
    body["user_id"] = AppContext::instance()->userId();
    body["scope_hint"] = scope->currentData().toString();
    if (scope->currentData().toString() == "project") body["project_id"] = project->text().trimmed();
    body["triples"] = QJsonArray{triple};

    m_proposeBtn->setEnabled(false);
    AppContext::instance()->api()->postAsync("/api/memory/facts/propose", body,
        [this](const api::Result &r) {
            m_proposeBtn->setEnabled(true);
            if (r.ok && r.hasJsonObject() && r.jsonObject().value("created").isArray()
                    && r.jsonObject().value("failed").isArray()) {
                const QJsonArray created = j::arr(r.jsonObject(), "created");
                const QJsonArray failed = j::arr(r.jsonObject(), "failed");
                if (!created.isEmpty()) onRefresh();
                QString message = QString("写入成功 %1 条，失败 %2 条。").arg(created.size()).arg(failed.size());
                for (const QJsonValue &value : failed)
                    message += "\n" + j::str(value.toObject(), "reason", "未知失败原因");
                if (failed.isEmpty() && !created.isEmpty()) QMessageBox::information(this, "完成", message);
                else QMessageBox::warning(this, "提交结果", message);
            } else if (r.errorCode == "memory.safety.review_required") {
                QMessageBox::warning(this, "需人工复核", "提案需人工复核。");
            } else if (r.errorCode == "memory.safety.rejected") {
                QMessageBox::warning(this, "被策略拒绝", "提案被安全策略拒绝。");
            } else {
                QMessageBox::warning(this, "提交失败", r.errorCode + " " + r.errorMessage);
            }
        }, false, this);
}
