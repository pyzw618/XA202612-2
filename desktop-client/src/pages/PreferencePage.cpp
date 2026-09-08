#include "PreferencePage.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QRegularExpression>
#include <QScrollArea>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/DetailDrawer.h"
#include "../widgets/ProvenancePanel.h"
#include "../widgets/EmptyState.h"
#include "../widgets/JsonViewer.h"
#include "../widgets/MemoryFilterBar.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"
#include "../widgets/RoundedContainer.h"
#include "../widgets/ScoreRing.h"
#include "../widgets/StatusTag.h"

namespace {
const QString kTypeKey("type");
const QString kStatusKey("status");
}

PreferencePage::PreferencePage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    // 头部
    auto *header = new PageHeader(this);
    header->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Fixed);
    header->setTitle("偏好记忆");
    header->setSubtitle("记录用户的输出风格、工具偏好、场景习惯等，随检索自动召回");
    m_addBtn = new QPushButton(QIcon(":/icons/plus.svg"), "新增偏好", this);
    m_addBtn->setObjectName("primaryBtn");
    connect(m_addBtn, &QPushButton::clicked, this, [this]() {
        openEditDialog(QJsonObject(), true);
    });
    m_batchDelete = new QPushButton("删除选中", this);
    m_batchDelete->setObjectName("dangerBtn");
    connect(m_batchDelete, &QPushButton::clicked, this, &PreferencePage::deleteSelected);
    header->actionLayout()->addWidget(m_batchDelete);
    header->actionLayout()->addWidget(m_addBtn);
    root->addWidget(header);

    // 筛选栏
    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    m_filterBar->setSearchPlaceholder("搜索内容 / 标签...");

    m_typeCombo = new QComboBox(this);
    m_typeCombo->addItem("全部类型", "");
    const QStringList types = {"output_style", "tool_preference", "workflow_preference",
                               "safety_preference", "scene_preference", "format_preference",
                               "language_preference"};
    for (const QString &t : types) m_typeCombo->addItem(StatusTag::memoryTypeText(t) + " · " + t, t);

    m_statusCombo = new QComboBox(this);
    m_statusCombo->addItem("有效", "active");
    const QStringList statuses = {"active", "archived", "pending", "deleted"};
    for (const QString &s : statuses) m_statusCombo->addItem(StatusTag::statusText(s), s);

    m_sceneEdit = new QLineEdit(this);
    m_sceneEdit->setPlaceholderText("场景");
    m_sceneEdit->setFixedWidth(120);

    m_minConf = new QDoubleSpinBox(this);
    m_minConf->setObjectName("filterSpin");
    m_minConf->setButtonSymbols(QAbstractSpinBox::NoButtons);
    m_minConf->setRange(0.0, 1.0);
    m_minConf->setSingleStep(0.1);
    m_minConf->setValue(0.0);
    m_minConf->setDecimals(1);
    m_minConf->setFixedWidth(76);

    auto *minConfLabel = new QLabel("置信 ≥", this);
    minConfLabel->setObjectName("filterLabel");

    m_filterBar->addWidget(m_typeCombo);
    m_filterBar->addWidget(m_statusCombo);
    m_filterBar->addWidget(m_sceneEdit);
    m_filterBar->addWidget(minConfLabel);
    m_filterBar->addWidget(m_minConf);
    m_filterBar->addStretch();

    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &PreferencePage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            &PreferencePage::applyLocalFilter);
    connect(m_typeCombo, qOverload<int>(&QComboBox::currentIndexChanged), this,
            &PreferencePage::applyLocalFilter);
    connect(m_statusCombo, qOverload<int>(&QComboBox::currentIndexChanged), this,
            &PreferencePage::onRefresh);
    connect(m_sceneEdit, &QLineEdit::textChanged, this, &PreferencePage::applyLocalFilter);
    connect(m_minConf, qOverload<double>(&QDoubleSpinBox::valueChanged), this,
            &PreferencePage::applyLocalFilter);

    root->addWidget(m_filterBar);

    // 表格 + 抽屉
    m_stateView = new PageStateView(this);
    m_stateView->hide();
    // 离线/加载时表格会隐藏；将所有剩余高度明确交给状态视图，
    // 防止标题与筛选栏被 Qt 的默认扩张策略拉开。
    root->addWidget(m_stateView, 1);

    auto *content = new RoundedContainer(this);
    m_content = content;
    content->setObjectName("dataTableContainer");
    auto *contentLay = new QHBoxLayout(content);
    contentLay->setContentsMargins(2, 2, 2, 2);
    contentLay->setSpacing(0);

    m_table = new QTableWidget(0, 9, content);
    m_table->setHorizontalHeaderLabels({"", "内容", "类型", "置信度", "健康度", "状态", "场景", "更新时间", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    m_table->setColumnWidth(0, 34);
    m_table->setColumnWidth(2, 120);
    m_table->setColumnWidth(3, 72);
    m_table->setColumnWidth(4, 72);
    m_table->setColumnWidth(5, 80);
    m_table->setColumnWidth(6, 130);
    m_table->setColumnWidth(7, 130);
    m_table->setColumnWidth(8, 180);
    m_table->verticalHeader()->setDefaultSectionSize(58);
    contentLay->addWidget(m_table, 1);

    m_drawer = new DetailDrawer(content);
    m_drawer->setWidth(560);
    contentLay->addWidget(m_drawer);

    root->addWidget(content, 1);
}

void PreferencePage::refresh() {
    onRefresh();
}

void PreferencePage::onRefresh() {
    m_drawer->closeDrawer();
    m_all = QJsonArray();
    m_table->setRowCount(0);
    const int generation = ++m_generation;
    m_content->hide();
    m_stateView->setState(PageState::Loading, "正在加载偏好记忆", "正在从后端读取真实数据…");
    m_stateView->clearAction();
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString status = m_statusCombo->currentData().toString();

    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/preferences",
        {{"user_id", uid}, {"status", status.isEmpty() ? "active" : status}}),
        [this, generation](const api::Result &r) {
            if (generation != m_generation) return;
            if (!r.ok || !r.hasJsonArray()) {
                m_content->setVisible(!m_all.isEmpty());
                m_stateView->setState(r.networkError ? PageState::Offline : PageState::Error,
                                      r.networkError ? "后端离线" : "偏好记忆加载失败",
                                      r.errorMessage.isEmpty() ? "请稍后重试。" : r.errorMessage);
                m_stateView->setAction("重试", [this]() { onRefresh(); });
                return;
            }
            m_all = r.jsonArray();
            m_content->setVisible(!m_all.isEmpty());
            if (m_all.isEmpty()) {
                m_stateView->setState(PageState::Empty, "暂无偏好记忆", "当前接口返回了空数据。");
                m_stateView->setAction("刷新", [this]() { onRefresh(); });
            } else {
                m_stateView->setState(PageState::Content, QString(), QString());
            }
            applyLocalFilter();
        }, this);
}

void PreferencePage::applyLocalFilter() {
    const QString type = m_typeCombo->currentData().toString();
    const QString scene = m_sceneEdit->text().trimmed();
    const double minConf = m_minConf->value();
    const QString kw = m_filterBar->searchBox()->text().trimmed();

    QList<QJsonObject> filtered;
    for (const QJsonValue &v : m_all) {
        const QJsonObject m = v.toObject();
        if (!type.isEmpty() && j::str(m, "preference_type") != type) continue;
        if (!scene.isEmpty() && !j::str(j::obj(m, "scope"), "scene").contains(scene, Qt::CaseInsensitive)) continue;
        if (j::num(m, "confidence") < minConf - 1e-9) continue;
        if (!kw.isEmpty()) {
            const bool hit = j::str(m, "text").contains(kw, Qt::CaseInsensitive) ||
                             j::strList(m, "tags").join(" ").contains(kw, Qt::CaseInsensitive);
            if (!hit) continue;
        }
        filtered.append(m);
    }

    m_table->setRowCount(0);
    m_table->setRowCount(int(filtered.size()));
    for (int i = 0; i < filtered.size(); ++i) {
        populateRow(i, filtered[i]);
    }
}

void PreferencePage::populateRow(int row, const QJsonObject &m) {
    const QString id = j::str(m, "memory_id");

    auto *check = new QCheckBox();
    check->setProperty("memoryId", id);
    m_table->setCellWidget(row, 0, check);

    // 内容（超长省略 + 悬停全文）
    QString text = j::str(m, "text");
    QLabel *textLabel = new QLabel(text);
    textLabel->setToolTip(text);
    textLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    textLabel->setWordWrap(false);
    auto *textWrap = new QWidget();
    auto *twLay = new QVBoxLayout(textWrap);
    twLay->setContentsMargins(0, 0, 0, 0);
    twLay->addWidget(textLabel);
    textLabel->setStyleSheet("border:none;");
    m_table->setCellWidget(row, 1, textWrap);

    auto *typeTag = new StatusTag();
    typeTag->setMemoryType("preference");
    typeTag->setText(StatusTag::memoryTypeText(j::str(m, "preference_type")) + " · " + j::str(m, "preference_type"));
    m_table->setCellWidget(row, 2, typeTag);

    auto *conf = new ScoreRing();
    conf->setValue(j::num(m, "confidence"));
    conf->setSize(46);
    m_table->setCellWidget(row, 3, conf);

    auto *health = new ScoreRing();
    health->setValue(j::num(m, "health_score", 1.0));
    health->setSize(46);
    m_table->setCellWidget(row, 4, health);

    auto *statusTag = new StatusTag();
    statusTag->setStatus(j::str(m, "status"));
    m_table->setCellWidget(row, 5, statusTag);

    const QJsonObject scope = j::obj(m, "scope");
    m_table->setItem(row, 6, new QTableWidgetItem(
        QString("%1 · %2").arg(j::str(scope, "scene"), j::str(scope, "task_type"))));

    m_table->setItem(row, 7, new QTableWidgetItem(j::timeAgo(j::str(m, "updated_at"))));

    // 操作区
    auto *ops = new QWidget();
    auto *opsLay = new QHBoxLayout(ops);
    opsLay->setContentsMargins(0, 0, 0, 0);
    opsLay->setSpacing(2);
    auto mkBtn = [this, ops](const QString &text) {
        auto *b = new QPushButton(text, ops);
        b->setObjectName("textBtn");
        return b;
    };
    auto *btnDetail = mkBtn("详情");
    auto *btnEdit = mkBtn("编辑");
    auto *btnFeedback = mkBtn("反馈");
    auto *btnForget = mkBtn("遗忘");
    btnForget->setStyleSheet("color:#EF4444;");
    connect(btnDetail, &QPushButton::clicked, this, [this, id]() { openDetail(id); });
    connect(btnEdit, &QPushButton::clicked, this, [this, m]() { openEditDialog(m, false); });
    connect(btnFeedback, &QPushButton::clicked, this, [this, m]() { openFeedbackMenu(m); });
    connect(btnForget, &QPushButton::clicked, this, [this, m]() {
        if (ConfirmDialog::confirm(this, "精准遗忘", "确认遗忘这条偏好记忆？\n将同步清理向量索引与证据。")) {
            api::ApiClient *api = AppContext::instance()->api();
            QJsonObject body;
            body["user_id"] = AppContext::instance()->userId();
            body["target_memory_ids"] = QJsonArray{j::str(m, "memory_id")};
            body["cascade"] = true;
            const api::Result r = api->post("/api/memory/forget", body);
            if (r.ok) {
                QMessageBox::information(this, "完成", "已遗忘");
                onRefresh();
            } else {
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }
    });
    opsLay->addWidget(btnDetail);
    opsLay->addWidget(btnEdit);
    opsLay->addWidget(btnFeedback);
    opsLay->addWidget(btnForget);
    m_table->setCellWidget(row, 8, ops);
}

void PreferencePage::openDetail(const QString &memoryId) {
    const int generation = m_generation;
    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->get(api::ApiClient::urlWithQuery(
        "/api/memory/preferences/" + memoryId,
        {{"user_id", AppContext::instance()->userId()}}));
    if (generation != m_generation) return;
    if (!r.ok || !r.hasJsonObject()) {
        QMessageBox::warning(this, "加载失败", r.errorCode + " " + r.errorMessage);
        return;
    }
    const QJsonObject m = r.jsonObject();

    auto *tabs = new QTabWidget();
    // Tab1 内容
    auto *content = new QWidget();
    auto *clay = new QVBoxLayout(content);
    auto info = new QLabel();
    info->setTextFormat(Qt::RichText);
    info->setWordWrap(true);
    info->setStyleSheet("color:#374151;font-size:13px;line-height:1.7;");
    QString html;
    html += QString("<b>内容</b><br/>%1<br/><br/>").arg(j::str(m, "text").toHtmlEscaped());
    html += QString("<b>类型</b> %1<br/>").arg(j::str(m, "preference_type"));
    html += QString("<b>置信度</b> %1　<b>健康度</b> %2<br/>")
                .arg(QString::number(j::num(m, "confidence"), 'f', 2))
                .arg(QString::number(j::num(m, "health_score", 1.0), 'f', 2));
    html += QString("<b>来源</b> %1　<b>版本</b> %2<br/>")
                .arg(j::str(m, "extract_source"))
                .arg(j::integer(m, "version"));
    html += QString("<b>全局</b> %1<br/>").arg(j::boolean(m, "is_global") ? "是" : "否");
    const QJsonObject scope = j::obj(m, "scope");
    html += QString("<b>场景</b> %1 / %2<br/>").arg(j::str(scope, "scene"), j::str(scope, "task_type"));
    if (!j::strList(m, "tags").isEmpty())
        html += QString("<b>标签</b> %1<br/>").arg(j::strList(m, "tags").join("、"));
    info->setText(html);
    clay->addWidget(info);
    auto *jsonTitle = new QLabel("结构化 payload");
    jsonTitle->setObjectName("cardTitle");
    clay->addWidget(jsonTitle);
    auto *jsonView = new JsonViewer();
    jsonView->setObject(j::obj(m, "payload"));
    clay->addWidget(jsonView, 1);
    tabs->addTab(content, "内容");

    // Tab2 版本链
    auto *verWidget = new QWidget();
    auto *vlay = new QVBoxLayout(verWidget);
    auto *verTable = new QTableWidget(0, 3);
    verTable->setHorizontalHeaderLabels({"版本", "更新时间", "内容"});
    verTable->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    verTable->verticalHeader()->setVisible(false);
    verTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    verTable->setAlternatingRowColors(true);
    const api::Result rv = api->get("/api/memory/preferences/" + memoryId + "/versions");
    if (generation != m_generation) {
        delete verWidget;
        delete tabs;
        return;
    }
    if (rv.hasJsonArray()) {
        const QJsonArray versions = rv.jsonArray();
        verTable->setRowCount(int(versions.size()));
        for (int i = 0; i < versions.size(); ++i) {
            const QJsonObject v = versions[i].toObject();
            verTable->setItem(i, 0, new QTableWidgetItem(QString("v%1").arg(j::integer(v, "version"))));
            verTable->setItem(i, 1, new QTableWidgetItem(j::fmtTime(j::str(v, "updated_at"))));
            verTable->setItem(i, 2, new QTableWidgetItem(j::str(v, "text")));
        }
    }
    vlay->addWidget(verTable);
    tabs->addTab(verWidget, "版本链");

    // Tab3 证据链
    auto *evWidget = new QWidget();
    auto *elay = new QVBoxLayout(evWidget);
    auto *evTable = new QTableWidget(0, 3);
    evTable->setHorizontalHeaderLabels({"来源类型", "权重", "内容摘要"});
    evTable->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    evTable->verticalHeader()->setVisible(false);
    evTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    evTable->setAlternatingRowColors(true);
    const QJsonArray evidences = j::arr(m, "evidences");
    evTable->setRowCount(int(evidences.size()));
    for (int i = 0; i < evidences.size(); ++i) {
        const QJsonObject e = evidences[i].toObject();
        evTable->setItem(i, 0, new QTableWidgetItem(j::str(e, "source_type")));
        evTable->setItem(i, 1, new QTableWidgetItem(QString::number(j::num(e, "weight", 1.0), 'f', 2)));
        evTable->setItem(i, 2, new QTableWidgetItem(j::str(e, "content")));
    }
    elay->addWidget(evTable);
    if (evidences.isEmpty()) {
        auto *empty = new EmptyState();
        empty->setIcon(QIcon(":/icons/preference.svg"));
        empty->setTitle("暂无证据链");
        empty->setHint("该记忆尚未沉淀关联证据");
        elay->addWidget(empty);
    }
    tabs->addTab(evWidget, "证据链");

    // Tab4 健康度
    auto *hWidget = new QWidget();
    auto *hlay = new QVBoxLayout(hWidget);
    auto *healthRing = new ScoreRing();
    healthRing->setValue(j::num(m, "health_score", 1.0));
    healthRing->setSize(96);
    healthRing->setCaption("健康度");
    auto *hInfo = new QLabel();
    hInfo->setTextFormat(Qt::RichText);
    hInfo->setStyleSheet("color:#374151;font-size:13px;line-height:1.7;");
    hInfo->setText(QString("<b>稳定性</b> %1<br/><b>30 天访问</b> %2 次<br/><b>最近访问</b> %3<br/>")
                       .arg(QString::number(j::num(m, "stability", 1.0), 'f', 2))
                       .arg(j::integer(m, "access_count_30d"))
                       .arg(j::str(m, "last_accessed_at").isEmpty() ? "从未"
                                                                    : j::timeAgo(j::str(m, "last_accessed_at"))));
    hInfo->setAlignment(Qt::AlignCenter);
    hlay->addWidget(healthRing, 0, Qt::AlignHCenter);
    hlay->addWidget(hInfo);
    hlay->addStretch();
    tabs->addTab(hWidget, "健康度");

    tabs->addTab(new ProvenancePanel(memoryId, tabs), "统一溯源");

    m_drawer->open(j::str(m, "preference_type") + " · " + j::shortId(memoryId), tabs);
}

void PreferencePage::openEditDialog(const QJsonObject &memory, bool isNew) {
    QDialog dlg(this);
    dlg.setWindowTitle(isNew ? "新增偏好" : "编辑偏好");
    dlg.setMinimumWidth(480);
    auto *form = new QFormLayout(&dlg);

    auto *textEdit = new QPlainTextEdit(&dlg);
    textEdit->setPlaceholderText("偏好内容，如：我习惯用 Markdown 格式写周报");
    textEdit->setPlainText(j::str(memory, "text"));
    textEdit->setFixedHeight(100);
    form->addRow("内容 *", textEdit);

    auto *typeEdit = new QComboBox(&dlg);
    const QStringList types = {"output_style", "tool_preference", "workflow_preference",
                               "safety_preference", "scene_preference", "format_preference",
                               "language_preference"};
    int curIdx = 0;
    for (int i = 0; i < types.size(); ++i) {
        typeEdit->addItem(types[i], types[i]);
        if (types[i] == j::str(memory, "preference_type")) curIdx = i;
    }
    typeEdit->setCurrentIndex(curIdx);
    form->addRow("类型", typeEdit);

    auto *sceneEdit = new QLineEdit(&dlg);
    sceneEdit->setPlaceholderText("如 office");
    sceneEdit->setText(j::str(j::obj(memory, "scope"), "scene"));
    form->addRow("场景", sceneEdit);

    auto *taskEdit = new QLineEdit(&dlg);
    taskEdit->setPlaceholderText("如 office.weekly_report");
    taskEdit->setText(j::str(j::obj(memory, "scope"), "task_type"));
    form->addRow("任务类型", taskEdit);

    auto *confSpin = new QDoubleSpinBox(&dlg);
    confSpin->setRange(0, 1);
    confSpin->setDecimals(2);
    confSpin->setSingleStep(0.05);
    confSpin->setValue(memory.isEmpty() ? 0.7 : j::num(memory, "confidence", 0.7));
    form->addRow("置信度", confSpin);

    auto *globalCheck = new QCheckBox("作为全局偏好（跨场景兜底）", &dlg);
    globalCheck->setChecked(j::boolean(memory, "is_global", false));
    form->addRow("", globalCheck);

    auto *tagsEdit = new QLineEdit(&dlg);
    tagsEdit->setPlaceholderText("逗号分隔，如 周报, markdown");
    tagsEdit->setText(j::strList(memory, "tags").join(", "));
    form->addRow("标签", tagsEdit);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel | QDialogButtonBox::Ok, &dlg);
    buttons->button(QDialogButtonBox::Ok)->setText("保存");
    buttons->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(buttons, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(buttons);

    if (dlg.exec() != QDialog::Accepted) return;
    if (textEdit->toPlainText().trimmed().isEmpty()) {
        QMessageBox::warning(this, "提示", "内容不能为空");
        return;
    }

    // 构造 PreferenceMemory 请求
    QJsonObject scope;
    scope["scene"] = sceneEdit->text().trimmed();
    scope["task_type"] = taskEdit->text().trimmed();
    scope["app"] = j::str(j::obj(memory, "scope"), "app");

    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    if (!isNew) body["transition_action"] = "revise";
    if (isNew) body["memory_type"] = "preference";
    body["preference_type"] = typeEdit->currentData().toString();
    body["text"] = textEdit->toPlainText().trimmed();
    if (isNew) body["payload"] = QJsonObject();
    body["scope"] = scope;
    body["is_global"] = globalCheck->isChecked();
    body["confidence"] = confSpin->value();
    body["tags"] = QJsonArray::fromStringList(
        tagsEdit->text().split(',', Qt::SkipEmptyParts).replaceInStrings(QRegularExpression("^\\s+|\\s+$"), ""));
    if (isNew) {
        body["status"] = "active";
        body["level"] = "mid";
    }

    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = isNew
        ? api->post("/api/memory/memories/preference", body)
        : api->put("/api/memory/preference/" + j::str(memory, "memory_id"), body);
    if (r.ok) {
        QMessageBox::information(this, "完成", isNew ? "偏好已写入" : "偏好已更新");
        onRefresh();
    } else {
        // 安全门禁感知
        if (r.errorCode == "memory.safety.review_required") {
            QMessageBox::warning(this, "需人工复核",
                                 QString("写入被安全门禁拦截：已进入人工复核流程。\naudit_id: %1")
                                     .arg(r.jsonObject().value("audit_id").toString()));
        } else if (r.errorCode == "memory.safety.rejected") {
            QMessageBox::warning(this, "被策略拒绝", "写入被安全策略拒绝，请联系管理员检查规则。");
        } else {
            QMessageBox::warning(this, "写入失败", r.errorCode + " " + r.errorMessage);
        }
    }
}

void PreferencePage::openFeedbackMenu(const QJsonObject &m) {
    QDialog dlg(this);
    dlg.setWindowTitle("记忆反馈");
    dlg.setMinimumWidth(420);
    auto *form = new QFormLayout(&dlg);

    auto *actionCombo = new QComboBox(&dlg);
    actionCombo->addItem("确认（有效）", "confirm");
    actionCombo->addItem("更新内容", "update");
    actionCombo->addItem("拒绝（归档）", "reject");
    form->addRow("动作", actionCombo);

    auto *textEdit = new QPlainTextEdit(&dlg);
    textEdit->setPlaceholderText("反馈内容（action=更新时必填，将替换记忆文本）");
    textEdit->setFixedHeight(90);
    form->addRow("内容", textEdit);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel | QDialogButtonBox::Ok, &dlg);
    buttons->button(QDialogButtonBox::Ok)->setText("提交");
    buttons->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(buttons, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(buttons);

    if (dlg.exec() != QDialog::Accepted) return;

    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["memory_id"] = j::str(m, "memory_id");
    body["action"] = actionCombo->currentData().toString();
    body["feedback_text"] = textEdit->toPlainText();

    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->post("/api/memory/feedback", body);
    if (r.ok) {
        QMessageBox::information(this, "完成", "反馈已提交");
        onRefresh();
    } else {
        if (r.errorCode == "memory.safety.review_required")
            QMessageBox::warning(this, "需人工复核", "更新内容需人工复核。");
        else if (r.errorCode == "memory.safety.rejected")
            QMessageBox::warning(this, "被策略拒绝", "更新被安全策略拒绝。");
        else
            QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
    }
}

QList<QString> PreferencePage::selectedIds() const {
    QList<QString> ids;
    const int rows = m_table->rowCount();
    for (int i = 0; i < rows; ++i) {
        auto *check = qobject_cast<QCheckBox *>(m_table->cellWidget(i, 0));
        if (check && check->isChecked()) ids << check->property("memoryId").toString();
    }
    return ids;
}

void PreferencePage::deleteSelected() {
    const QList<QString> ids = selectedIds();
    if (ids.isEmpty()) {
        QMessageBox::information(this, "提示", "请先勾选要删除的记忆");
        return;
    }
    if (!ConfirmDialog::confirm(this, "批量删除",
                                QString("确认删除选中的 %1 条偏好记忆？\n将级联清理向量/证据/冲突。").arg(ids.size()))) {
        return;
    }
    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    QJsonArray arr;
    for (const QString &id : ids) arr.append(id);
    body["memory_ids"] = arr;
    body["cascade"] = true;

    api::ApiClient *api = AppContext::instance()->api();
    const api::Result r = api->post("/api/memory/memories/delete", body);
    if (r.ok) {
        QMessageBox::information(this, "完成",
                                 QString("已删除 %1 条，记入遗忘历史：%2")
                                     .arg(r.jsonObject().value("deleted_count").toInt())
                                     .arg(r.jsonObject().value("record_id").toString()));
        onRefresh();
    } else {
        QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
    }
}
