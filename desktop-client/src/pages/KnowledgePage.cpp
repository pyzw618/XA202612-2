#include "KnowledgePage.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QProgressBar>
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
#include "../widgets/ScoreRing.h"
#include "../widgets/StatusTag.h"

KnowledgePage::KnowledgePage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("知识记忆");
    header->setSubtitle("沉淀的工作流 / 案例 / 模板，可被检索复用");
    m_addBtn = new QPushButton("＋ 新增知识", this);
    m_addBtn->setObjectName("primaryBtn");
    connect(m_addBtn, &QPushButton::clicked, this, [this]() { openEditDialog(QJsonObject(), true); });
    m_batchDelete = new QPushButton("删除选中", this);
    m_batchDelete->setObjectName("dangerBtn");
    connect(m_batchDelete, &QPushButton::clicked, this, [this]() {
        const QList<QString> ids = selectedIds();
        if (ids.isEmpty()) { QMessageBox::information(this, "提示", "请先勾选"); return; }
        if (!ConfirmDialog::confirm(this, "批量删除",
                                    QString("确认删除选中的 %1 条知识记忆？").arg(ids.size()))) return;
        QJsonObject body;
        body["user_id"] = AppContext::instance()->userId();
        QJsonArray arr;
        for (const QString &id : ids) arr.append(id);
        body["memory_ids"] = arr;
        body["cascade"] = true;
        const api::Result r = AppContext::instance()->api()->post("/api/memory/memories/delete", body);
        if (r.ok) { QMessageBox::information(this, "完成", "已删除"); onRefresh(); }
        else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
    });
    header->actionLayout()->addWidget(m_batchDelete);
    header->actionLayout()->addWidget(m_addBtn);
    root->addWidget(header);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索名称 / 内容...");
    m_typeCombo = new QComboBox(this);
    m_typeCombo->addItem("全部类型", "");
    const QStringList types = {"workflow", "case", "template"};
    for (const QString &t : types) m_typeCombo->addItem(t, t);
    m_statusCombo = new QComboBox(this);
    m_statusCombo->addItem("全部状态", "");
    for (const QString &s : QStringList{"active", "archived", "pending", "deleted"})
        m_statusCombo->addItem(StatusTag::statusText(s), s);
    m_filterBar->addWidget(m_typeCombo);
    m_filterBar->addWidget(m_statusCombo);
    m_filterBar->addStretch();
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &KnowledgePage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this, &KnowledgePage::applyLocalFilter);
    connect(m_typeCombo, qOverload<int>(&QComboBox::currentIndexChanged), this, &KnowledgePage::applyLocalFilter);
    connect(m_statusCombo, qOverload<int>(&QComboBox::currentIndexChanged), this, &KnowledgePage::onRefresh);
    root->addWidget(m_filterBar);

    auto *content = new QWidget(this);
    auto *clay = new QHBoxLayout(content);
    clay->setContentsMargins(0, 8, 0, 0);
    clay->setSpacing(0);

    m_table = new QTableWidget(0, 8, content);
    m_table->setHorizontalHeaderLabels({"", "名称", "类型", "置信度", "成功率", "状态", "更新时间", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    m_table->setColumnWidth(0, 34);
    m_table->setColumnWidth(2, 90);
    m_table->setColumnWidth(3, 72);
    m_table->setColumnWidth(4, 120);
    m_table->setColumnWidth(5, 80);
    m_table->setColumnWidth(6, 130);
    m_table->setColumnWidth(7, 200);
    m_table->verticalHeader()->setDefaultSectionSize(52);
    clay->addWidget(m_table, 1);

    m_drawer = new DetailDrawer(content);
    m_drawer->setWidth(560);
    clay->addWidget(m_drawer);

    root->addWidget(content, 1);
}

void KnowledgePage::refresh() { onRefresh(); }

void KnowledgePage::onRefresh() {
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString status = m_statusCombo->currentData().toString();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge",
        {{"user_id", uid}, {"status", status.isEmpty() ? "active" : status}}));
    m_all = r.jsonArray();
    applyLocalFilter();
}

void KnowledgePage::applyLocalFilter() {
    const QString type = m_typeCombo->currentData().toString();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    QList<QJsonObject> filtered;
    for (const QJsonValue &v : m_all) {
        const QJsonObject m = v.toObject();
        if (!type.isEmpty() && j::str(m, "knowledge_type") != type) continue;
        if (!kw.isEmpty() &&
            !(j::str(m, "name").contains(kw, Qt::CaseInsensitive) ||
              j::str(m, "content").contains(kw, Qt::CaseInsensitive)))
            continue;
        filtered.append(m);
    }
    m_table->setRowCount(0);
    m_table->setRowCount(int(filtered.size()));
    for (int i = 0; i < filtered.size(); ++i) populateRow(i, filtered[i]);
}

void KnowledgePage::populateRow(int row, const QJsonObject &m) {
    const QString id = j::str(m, "memory_id");
    auto *check = new QCheckBox();
    check->setProperty("memoryId", id);
    m_table->setCellWidget(row, 0, check);

    QString name = j::str(m, "name");
    QLabel *nameLabel = new QLabel(name);
    nameLabel->setToolTip(name);
    nameLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    auto *wrap = new QWidget();
    auto *wl = new QVBoxLayout(wrap);
    wl->setContentsMargins(0, 0, 0, 0);
    nameLabel->setStyleSheet("border:none;");
    wl->addWidget(nameLabel);
    m_table->setCellWidget(row, 1, wrap);

    auto *typeTag = new StatusTag();
    typeTag->setMemoryType("knowledge");
    typeTag->setText(j::str(m, "knowledge_type"));
    m_table->setCellWidget(row, 2, typeTag);

    auto *conf = new ScoreRing();
    conf->setValue(j::num(m, "confidence"));
    conf->setSize(44);
    m_table->setCellWidget(row, 3, conf);

    const int sc = j::integer(m, "success_count");
    const int tc = j::integer(m, "total_count");
    auto *rate = new QWidget();
    auto *rl = new QVBoxLayout(rate);
    rl->setContentsMargins(4, 4, 4, 4);
    rl->setSpacing(2);
    auto *bar = new QProgressBar(rate);
    bar->setRange(0, tc > 0 ? tc : 1);
    bar->setValue(sc);
    bar->setFormat(QString("%1/%2").arg(sc).arg(tc));
    rl->addWidget(bar);
    m_table->setCellWidget(row, 4, rate);

    auto *statusTag = new StatusTag();
    statusTag->setStatus(j::str(m, "status"));
    m_table->setCellWidget(row, 5, statusTag);

    m_table->setItem(row, 6, new QTableWidgetItem(j::timeAgo(j::str(m, "updated_at"))));

    auto *ops = new QWidget();
    auto *ol = new QHBoxLayout(ops);
    ol->setContentsMargins(0, 0, 0, 0);
    ol->setSpacing(2);
    auto mk = [ops](const QString &t) { auto *b = new QPushButton(t, ops); b->setObjectName("textBtn"); return b; };
    auto *bDetail = mk("详情");
    auto *bEdit = mk("编辑");
    auto *bConfirm = mk("确认复用");
    auto *bForget = mk("遗忘");
    bForget->setStyleSheet("color:#EF4444;");
    connect(bDetail, &QPushButton::clicked, this, [this, id]() { openDetail(id); });
    connect(bEdit, &QPushButton::clicked, this, [this, m]() { openEditDialog(m, false); });
    connect(bConfirm, &QPushButton::clicked, this, [this, m]() {
        QJsonObject body;
        body["user_id"] = AppContext::instance()->userId();
        body["memory_id"] = j::str(m, "memory_id");
        body["action"] = "confirm";
        body["feedback_text"] = "";
        const api::Result r = AppContext::instance()->api()->post("/api/memory/feedback", body);
        if (r.ok) { QMessageBox::information(this, "完成", "复用计数 +1"); onRefresh(); }
        else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
    });
    connect(bForget, &QPushButton::clicked, this, [this, m]() {
        if (!ConfirmDialog::confirm(this, "精准遗忘", "确认遗忘这条知识记忆？")) return;
        QJsonObject body;
        body["user_id"] = AppContext::instance()->userId();
        body["target_memory_ids"] = QJsonArray{j::str(m, "memory_id")};
        body["cascade"] = true;
        const api::Result r = AppContext::instance()->api()->post("/api/memory/forget", body);
        if (r.ok) { QMessageBox::information(this, "完成", "已遗忘"); onRefresh(); }
        else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
    });
    ol->addWidget(bDetail);
    ol->addWidget(bEdit);
    ol->addWidget(bConfirm);
    ol->addWidget(bForget);
    m_table->setCellWidget(row, 7, ops);
}

void KnowledgePage::openDetail(const QString &id) {
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge/" + id, {{"user_id", AppContext::instance()->userId()}}));
    if (!r.hasJsonObject()) { QMessageBox::warning(this, "加载失败", r.errorCode); return; }
    const QJsonObject m = r.jsonObject();

    auto *tabs = new QTabWidget();

    auto *content = new QWidget();
    auto *clay = new QVBoxLayout(content);
    auto *info = new QLabel();
    info->setTextFormat(Qt::RichText);
    info->setWordWrap(true);
    info->setStyleSheet("color:#374151;font-size:13px;line-height:1.7;");
    QString html = QString("<b>%1</b><br/><br/>%2<br/><br/>")
                       .arg(j::str(m, "name").toHtmlEscaped(), j::str(m, "content").toHtmlEscaped());
    html += QString("<b>类型</b> %1　<b>置信度</b> %2<br/>")
                .arg(j::str(m, "knowledge_type"))
                .arg(QString::number(j::num(m, "confidence"), 'f', 2));
    // 步骤
    const QJsonArray steps = j::arr(m, "steps");
    if (!steps.isEmpty()) {
        html += "<b>步骤</b><ol>";
        for (const QJsonValue &s : steps) html += QString("<li>%1</li>").arg(s.toString().toHtmlEscaped());
        html += "</ol>";
    }
    // 工具链
    const QStringList tools = j::strList(m, "tools");
    if (!tools.isEmpty()) html += QString("<b>工具链</b> %1<br/>").arg(tools.join(" → "));
    info->setText(html);
    clay->addWidget(info);
    if (!j::str(m, "template_body").isEmpty()) {
        auto *tTitle = new QLabel("模板正文");
        tTitle->setObjectName("cardTitle");
        clay->addWidget(tTitle);
        auto *tpl = new QPlainTextEdit();
        tpl->setPlainText(j::str(m, "template_body"));
        tpl->setReadOnly(true);
        tpl->setStyleSheet("font-family:Consolas,monospace;font-size:12px;");
        clay->addWidget(tpl, 1);
    } else {
        clay->addStretch();
    }
    tabs->addTab(content, "内容");

    // 版本历史
    auto *verW = new QWidget();
    auto *vl = new QVBoxLayout(verW);
    auto *verT = new QTableWidget(0, 3);
    verT->setHorizontalHeaderLabels({"版本", "更新时间", "名称"});
    verT->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    verT->verticalHeader()->setVisible(false);
    verT->setEditTriggers(QAbstractItemView::NoEditTriggers);
    verT->setAlternatingRowColors(true);
    const api::Result rv = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/knowledge/" + id + "/versions",
        {{"user_id", AppContext::instance()->userId()}}));
    if (rv.hasJsonArray()) {
        const QJsonArray versions = rv.jsonArray();
        verT->setRowCount(int(versions.size()));
        for (int i = 0; i < versions.size(); ++i) {
            const QJsonObject v = versions[i].toObject();
            verT->setItem(i, 0, new QTableWidgetItem(QString("v%1").arg(j::integer(v, "version"))));
            verT->setItem(i, 1, new QTableWidgetItem(j::fmtTime(j::str(v, "updated_at"))));
            verT->setItem(i, 2, new QTableWidgetItem(j::str(v, "name")));
        }
    }
    vl->addWidget(verT);
    tabs->addTab(verW, "版本历史");

    // 复用统计
    auto *stW = new QWidget();
    auto *sl = new QVBoxLayout(stW);
    auto *stInfo = new QLabel();
    stInfo->setTextFormat(Qt::RichText);
    stInfo->setStyleSheet("color:#374151;font-size:14px;line-height:1.8;");
    const int sc = j::integer(m, "success_count");
    const int tc = j::integer(m, "total_count");
    const double rate = tc > 0 ? double(sc) / tc : 0.0;
    stInfo->setText(QString("<b>成功复用</b> %1 次<br/><b>总调用</b> %2 次<br/><b>成功率</b> %3<br/>")
                        .arg(sc).arg(tc).arg(j::pct(rate, 1)));
    sl->addWidget(stInfo);
    sl->addStretch();
    tabs->addTab(stW, "复用统计");

    m_drawer->open(j::str(m, "name"), tabs);
}

void KnowledgePage::openEditDialog(const QJsonObject &memory, bool isNew) {
    QDialog dlg(this);
    dlg.setWindowTitle(isNew ? "新增知识" : "编辑知识");
    dlg.setMinimumWidth(500);
    auto *form = new QFormLayout(&dlg);

    auto *nameEdit = new QLineEdit(&dlg);
    nameEdit->setText(j::str(memory, "name"));
    form->addRow("名称 *", nameEdit);

    auto *typeEdit = new QComboBox(&dlg);
    for (const QString &t : QStringList{"workflow", "case", "template"}) typeEdit->addItem(t, t);
    typeEdit->setCurrentIndex(qMax(0, typeEdit->findData(j::str(memory, "knowledge_type"))));
    form->addRow("类型", typeEdit);

    auto *contentEdit = new QPlainTextEdit(&dlg);
    contentEdit->setPlainText(j::str(memory, "content"));
    contentEdit->setFixedHeight(90);
    form->addRow("内容 *", contentEdit);

    auto *stepsEdit = new QPlainTextEdit(&dlg);
    stepsEdit->setPlainText(j::strList(memory, "steps").join("\n"));
    stepsEdit->setFixedHeight(80);
    form->addRow("步骤（每行一步）", stepsEdit);

    auto *toolsEdit = new QLineEdit(&dlg);
    toolsEdit->setText(j::strList(memory, "tools").join(", "));
    form->addRow("工具链（逗号分隔）", toolsEdit);

    auto *confSpin = new QDoubleSpinBox(&dlg);
    confSpin->setRange(0, 1);
    confSpin->setDecimals(2);
    confSpin->setValue(memory.isEmpty() ? 0.7 : j::num(memory, "confidence", 0.7));
    form->addRow("置信度", confSpin);

    auto *scopeEdit = new QLineEdit(&dlg);
    scopeEdit->setText(j::str(j::obj(memory, "scope"), "scene"));
    form->addRow("场景", scopeEdit);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel | QDialogButtonBox::Ok, &dlg);
    buttons->button(QDialogButtonBox::Ok)->setText("保存");
    buttons->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(buttons, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(buttons);

    if (dlg.exec() != QDialog::Accepted) return;
    if (nameEdit->text().trimmed().isEmpty()) {
        QMessageBox::warning(this, "提示", "名称不能为空");
        return;
    }

    QJsonObject scope;
    scope["scene"] = scopeEdit->text().trimmed();
    scope["task_type"] = j::str(j::obj(memory, "scope"), "task_type");
    scope["app"] = j::str(j::obj(memory, "scope"), "app");

    QJsonObject body;
    if (!isNew) body["memory_id"] = j::str(memory, "memory_id");
    body["user_id"] = AppContext::instance()->userId();
    body["memory_type"] = "knowledge";
    body["knowledge_type"] = typeEdit->currentData().toString();
    body["name"] = nameEdit->text().trimmed();
    body["content"] = contentEdit->toPlainText().trimmed();
    body["steps"] = QJsonArray::fromStringList(
        stepsEdit->toPlainText().split('\n', Qt::SkipEmptyParts));
    body["tools"] = QJsonArray::fromStringList(
        toolsEdit->text().split(',', Qt::SkipEmptyParts).replaceInStrings(
            QRegularExpression("^\\s+|\\s+$"), ""));
    body["scope"] = scope;
    body["confidence"] = confSpin->value();
    body["status"] = "active";

    const api::Result r = AppContext::instance()->api()->post("/api/memory/memories/knowledge", body);
    if (r.ok) { QMessageBox::information(this, "完成", isNew ? "知识已写入" : "知识已更新"); onRefresh(); }
    else if (r.errorCode == "memory.safety.review_required")
        QMessageBox::warning(this, "需人工复核", "写入需人工复核。");
    else if (r.errorCode == "memory.safety.rejected")
        QMessageBox::warning(this, "被策略拒绝", "写入被安全策略拒绝。");
    else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
}

QList<QString> KnowledgePage::selectedIds() const {
    QList<QString> ids;
    for (int i = 0; i < m_table->rowCount(); ++i) {
        auto *c = qobject_cast<QCheckBox *>(m_table->cellWidget(i, 0));
        if (c && c->isChecked()) ids << c->property("memoryId").toString();
    }
    return ids;
}
