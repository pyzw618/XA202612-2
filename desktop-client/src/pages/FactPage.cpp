#include "FactPage.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QFrame>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/DetailDrawer.h"
#include "../widgets/JsonViewer.h"
#include "../widgets/MemoryFilterBar.h"
#include "../widgets/PageHeader.h"
#include "../widgets/StatusTag.h"

namespace {
QString tripleText(const QJsonObject &f) {
    // 后端 fact 返回可能带主语/谓词/宾语文本，或仅 object_value + ids
    QString s = j::str(f, "subject_text");
    QString p = j::str(f, "predicate_text");
    QString o = j::str(f, "object_value");
    if (s.isEmpty()) s = j::str(f, "subject_id");
    if (p.isEmpty()) p = j::str(f, "predicate_id");
    if (o.isEmpty()) o = j::str(f, "object_id");
    return QString("%1 → %2 → %3").arg(s, p, o);
}
} // namespace

FactPage::FactPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("事实记忆");
    header->setSubtitle("知识图谱三元组（主语 → 谓词 → 宾语），支持人工提案与裁决");
    m_proposeBtn = new QPushButton("＋ 手动提交三元组", this);
    m_proposeBtn->setObjectName("primaryBtn");
    connect(m_proposeBtn, &QPushButton::clicked, this, &FactPage::openProposeDialog);
    header->actionLayout()->addWidget(m_proposeBtn);
    root->addWidget(header);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索三元组 / 来源...");
    m_scopeCombo = new QComboBox(this);
    m_scopeCombo->addItem("全部作用域", "");
    m_scopeCombo->addItem("全局 global", "global");
    m_scopeCombo->addItem("项目 project", "project");
    m_statusCombo = new QComboBox(this);
    m_statusCombo->addItem("有效", "active");
    m_statusCombo->addItem("已替代", "superseded");
    m_statusCombo->addItem("存疑", "disputed");
    m_statusCombo->addItem("已删除", "deleted");
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

    // 候选裁决区（折叠卡片容器）
    m_candidateContainer = new QWidget(this);
    m_candidateContainer->hide();
    m_candidateLayout = new QVBoxLayout(m_candidateContainer);
    m_candidateLayout->setContentsMargins(0, 8, 0, 4);
    root->addWidget(m_candidateContainer);

    auto *content = new QWidget(this);
    auto *clay = new QHBoxLayout(content);
    clay->setContentsMargins(0, 8, 0, 0);
    clay->setSpacing(0);

    m_table = new QTableWidget(0, 8, content);
    m_table->setHorizontalHeaderLabels({"", "三元组", "置信度", "作用域", "状态", "来源", "访问", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    m_table->setColumnWidth(0, 34);
    m_table->setColumnWidth(2, 72);
    m_table->setColumnWidth(3, 110);
    m_table->setColumnWidth(4, 80);
    m_table->setColumnWidth(5, 120);
    m_table->setColumnWidth(6, 60);
    m_table->setColumnWidth(7, 170);
    m_table->verticalHeader()->setDefaultSectionSize(44);
    clay->addWidget(m_table, 1);

    m_drawer = new DetailDrawer(content);
    m_drawer->setWidth(560);
    clay->addWidget(m_drawer);

    root->addWidget(content, 1);
}

void FactPage::refresh() { onRefresh(); }

void FactPage::onRefresh() {
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString status = m_statusCombo->currentData().toString();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts",
        {{"user_id", uid}, {"status", status.isEmpty() ? "active" : status}, {"limit", "500"}}));
    m_all = r.jsonArray();
    applyLocalFilter();
}

void FactPage::applyLocalFilter() {
    const QString scope = m_scopeCombo->currentData().toString();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    QList<QJsonObject> filtered;
    for (const QJsonValue &v : m_all) {
        const QJsonObject f = v.toObject();
        if (!scope.isEmpty() && j::str(f, "scope") != scope) continue;
        if (!kw.isEmpty() && !tripleText(f).contains(kw, Qt::CaseInsensitive) &&
            !j::str(f, "source_id").contains(kw, Qt::CaseInsensitive))
            continue;
        filtered.append(f);
    }
    m_table->setRowCount(0);
    m_table->setRowCount(int(filtered.size()));
    for (int i = 0; i < filtered.size(); ++i) populateRow(i, filtered[i]);
}

void FactPage::populateRow(int row, const QJsonObject &f) {
    const QString id = j::str(f, "fact_id");
    m_table->setItem(row, 0, new QTableWidgetItem(""));
    auto *triple = new QLabel(tripleText(f));
    triple->setToolTip(j::str(f, "source_text"));
    triple->setTextInteractionFlags(Qt::TextSelectableByMouse);
    triple->setStyleSheet("border:none;");
    m_table->setCellWidget(row, 1, triple);

    auto *conf = new QLabel(QString::number(j::num(f, "confidence"), 'f', 2));
    conf->setAlignment(Qt::AlignCenter);
    conf->setStyleSheet(QString("color:%1;font-weight:600;")
                            .arg(j::num(f, "confidence") >= 0.6 ? "#16A34A"
                                 : j::num(f, "confidence") >= 0.4 ? "#D97706" : "#DC2626"));
    m_table->setCellWidget(row, 2, conf);

    m_table->setItem(row, 3, new QTableWidgetItem(
        j::str(f, "scope") + (j::str(f, "project_id").isEmpty() ? "" : " · " + j::str(f, "project_id"))));

    auto *statusTag = new StatusTag();
    statusTag->setStatus(j::str(f, "status"));
    m_table->setCellWidget(row, 4, statusTag);

    m_table->setItem(row, 5, new QTableWidgetItem(j::shortId(j::str(f, "source_id"))));
    m_table->setItem(row, 6, new QTableWidgetItem(QString::number(j::integer(f, "access_count_30d"))));

    auto *ops = new QWidget();
    auto *ol = new QHBoxLayout(ops);
    ol->setContentsMargins(0, 0, 0, 0);
    ol->setSpacing(2);
    auto mk = [ops](const QString &t) { auto *b = new QPushButton(t, ops); b->setObjectName("textBtn"); return b; };
    auto *bDetail = mk("详情");
    auto *bEvidence = mk("证据");
    auto *bDelete = mk("删除");
    bDelete->setStyleSheet("color:#EF4444;");
    connect(bDetail, &QPushButton::clicked, this, [this, id]() { openDetail(id); });
    connect(bEvidence, &QPushButton::clicked, this, [this, id]() { openDetail(id); });
    connect(bDelete, &QPushButton::clicked, this, [this, f]() {
        if (!ConfirmDialog::confirm(this, "删除事实", "确认删除这条事实三元组？")) return;
        const api::Result r = AppContext::instance()->api()->del(
            api::ApiClient::urlWithQuery("/api/memory/facts/" + j::str(f, "fact_id"),
                                         {{"user_id", AppContext::instance()->userId()}}));
        if (r.ok) { QMessageBox::information(this, "完成", "已删除"); onRefresh(); }
        else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
    });
    ol->addWidget(bDetail);
    ol->addWidget(bEvidence);
    ol->addWidget(bDelete);
    m_table->setCellWidget(row, 7, ops);
}

void FactPage::openDetail(const QString &id) {
    api::ApiClient *api = AppContext::instance()->api();
    const QString uid = AppContext::instance()->userId();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts/" + id, {{"user_id", uid}}));
    if (!r.hasJsonObject()) { QMessageBox::warning(this, "加载失败", r.errorCode); return; }
    const QJsonObject f = r.jsonObject();

    auto *tabs = new QTabWidget();
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
    auto *evW = new QWidget();
    auto *el = new QVBoxLayout(evW);
    auto *evT = new QTableWidget(0, 3);
    evT->setHorizontalHeaderLabels({"时间", "事件", "内容"});
    evT->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    evT->verticalHeader()->setVisible(false);
    evT->setEditTriggers(QAbstractItemView::NoEditTriggers);
    const api::Result rev = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/facts/" + id + "/evidence", {{"user_id", uid}}));
    if (rev.hasJsonArray()) {
        const QJsonArray evs = rev.jsonArray();
        evT->setRowCount(int(evs.size()));
        for (int i = 0; i < evs.size(); ++i) {
            const QJsonObject e = evs[i].toObject();
            evT->setItem(i, 0, new QTableWidgetItem(j::timeAgo(j::str(e, "timestamp"))));
            evT->setItem(i, 1, new QTableWidgetItem(j::str(e, "event_id")));
            evT->setItem(i, 2, new QTableWidgetItem(j::str(e, "content")));
        }
    }
    el->addWidget(evT);
    tabs->addTab(evW, "证据");

    m_drawer->open(j::shortId(id), tabs);
}

void FactPage::openProposeDialog() {
    QDialog dlg(this);
    dlg.setWindowTitle("手动提交三元组");
    dlg.setMinimumWidth(520);
    auto *form = new QFormLayout(&dlg);

    auto *sEdit = new QLineEdit(&dlg);
    sEdit->setPlaceholderText("如：张三");
    form->addRow("主语 *", sEdit);
    auto *pEdit = new QLineEdit(&dlg);
    pEdit->setPlaceholderText("如：就职于");
    form->addRow("谓词 *", pEdit);
    auto *oEdit = new QLineEdit(&dlg);
    oEdit->setPlaceholderText("如：银河麒麟软件有限公司");
    form->addRow("宾语 *", oEdit);
    auto *evEdit = new QLineEdit(&dlg);
    evEdit->setPlaceholderText("支撑该事实的原文证据（可选）");
    form->addRow("证据", evEdit);
    auto *scopeCombo = new QComboBox(&dlg);
    scopeCombo->addItem("全局", "global");
    scopeCombo->addItem("项目", "project");
    form->addRow("作用域", scopeCombo);
    auto *projEdit = new QLineEdit(&dlg);
    projEdit->setPlaceholderText("project 作用域的项目 ID（可选）");
    form->addRow("项目 ID", projEdit);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel | QDialogButtonBox::Ok, &dlg);
    buttons->button(QDialogButtonBox::Ok)->setText("提交提案");
    buttons->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(buttons, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(buttons);

    if (dlg.exec() != QDialog::Accepted) return;
    if (sEdit->text().trimmed().isEmpty() || pEdit->text().trimmed().isEmpty() ||
        oEdit->text().trimmed().isEmpty()) {
        QMessageBox::warning(this, "提示", "主语/谓词/宾语均不能为空");
        return;
    }

    QJsonObject triple;
    triple["subject_text"] = sEdit->text().trimmed();
    triple["predicate_text"] = pEdit->text().trimmed();
    triple["object_text"] = oEdit->text().trimmed();
    triple["evidence"] = evEdit->text().trimmed();
    triple["confidence"] = 1.0;

    QJsonObject body;
    body["scope_hint"] = scopeCombo->currentData().toString();
    body["project_id"] = projEdit->text().trimmed().isEmpty() ? QJsonValue() : QJsonValue(projEdit->text().trimmed());
    body["triples"] = QJsonArray{triple};

    const api::Result r = AppContext::instance()->api()->post("/api/memory/facts/propose", body);
    if (r.hasJsonArray()) {
        const QJsonArray proposals = r.jsonArray();
        for (const QJsonValue &p : proposals) m_candidates.append(p.toObject());
        QMessageBox::information(this, "完成", QString("已生成 %1 条事实候选，请到上方裁决区处理").arg(proposals.size()));
        renderCandidates();
    } else {
        QMessageBox::warning(this, "提交失败", r.errorCode + " " + r.errorMessage);
    }
}

void FactPage::renderCandidates() {
    // 清空旧卡片
    while (QLayoutItem *item = m_candidateLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) w->deleteLater();
        delete item;
    }
    if (m_candidates.isEmpty()) {
        m_candidateContainer->hide();
        return;
    }
    m_candidateContainer->show();

    auto *title = new QLabel(QString("待裁决事实候选（%1）").arg(m_candidates.size()));
    title->setObjectName("cardTitle");
    m_candidateLayout->addWidget(title);

    for (int i = 0; i < m_candidates.size(); ++i) {
        const QJsonObject p = m_candidates[i].toObject();
        auto *card = new QFrame();
        card->setObjectName("card");
        auto *cl = new QVBoxLayout(card);
        auto *head = new QLabel();
        head->setTextFormat(Qt::RichText);
        head->setText(QString("<span style='font-size:14px;font-weight:600;color:#1F2430;'>%1</span>")
                          .arg(QString("%1 → %2 → %3")
                                   .arg(j::str(p, "subject"), j::str(p, "predicate"), j::str(p, "object"))
                                   .toHtmlEscaped()));
        cl->addWidget(head);
        if (!j::str(p, "admission_reason").isEmpty())
            cl->addWidget(new QLabel("准入理由：" + j::str(p, "admission_reason")));
        cl->addWidget(new QLabel("建议作用域：" + j::str(p, "suggested_scope") +
                                 "　置信度：" + QString::number(j::num(p, "confidence"), 'f', 2)));
        auto *row = new QHBoxLayout();
        row->addStretch();
        auto *accept = new QPushButton("采纳");
        accept->setObjectName("primaryBtn");
        auto *reject = new QPushButton("驳回");
        reject->setObjectName("dangerBtn");
        const QString pid = j::str(p, "proposal_id");
        connect(accept, &QPushButton::clicked, this, [this, pid]() {
            QDialog dlg(this);
            dlg.setWindowTitle("采纳事实候选");
            auto *form = new QFormLayout(&dlg);
            auto *scope = new QComboBox(&dlg);
            scope->addItem("全局", "global");
            scope->addItem("项目", "project");
            form->addRow("作用域", scope);
            auto *proj = new QLineEdit(&dlg);
            proj->setPlaceholderText("project 作用域的项目 ID");
            form->addRow("项目 ID", proj);
            auto *bb = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dlg);
            bb->button(QDialogButtonBox::Ok)->setText("确认采纳");
            connect(bb, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
            connect(bb, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
            form->addRow(bb);
            if (dlg.exec() != QDialog::Accepted) return;
            QJsonObject payload;
            payload["scope"] = scope->currentData().toString();
            if (!proj->text().trimmed().isEmpty()) payload["project_id"] = proj->text().trimmed();
            QJsonObject body;
            body["action_type"] = "fact_commit";
            body["decision"] = "commit";
            body["payload"] = payload;
            const api::Result r = AppContext::instance()->api()->post(
                "/api/agent/actions/" + pid + "/decision", body);
            if (r.ok) {
                QMessageBox::information(this, "完成", "事实已入库");
                removeCandidate(pid);
                onRefresh();
            } else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
        });
        connect(reject, &QPushButton::clicked, this, [this, pid]() {
            QJsonObject body;
            body["action_type"] = "fact_reject";
            body["decision"] = "reject";
            body["payload"] = QJsonObject();
            const api::Result r = AppContext::instance()->api()->post(
                "/api/agent/actions/" + pid + "/decision", body);
            if (r.ok) { QMessageBox::information(this, "完成", "已驳回"); removeCandidate(pid); }
            else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
        });
        row->addWidget(accept);
        row->addWidget(reject);
        cl->addLayout(row);
        m_candidateLayout->addWidget(card);
    }
}

void FactPage::removeCandidate(const QString &proposalId) {
    QJsonArray kept;
    for (const QJsonValue &v : m_candidates) {
        if (j::str(v.toObject(), "proposal_id") != proposalId) kept.append(v);
    }
    m_candidates = kept;
    renderCandidates();
}
