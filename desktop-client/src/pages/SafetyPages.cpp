// 安全中心 · 4 个子页完整实现

#include "SafetyPages.h"

#include <QBrush>
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
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>
#include <QIcon>
#include <QJsonDocument>
#include <QPointer>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/ConfirmDialog.h"
#include "../widgets/EmptyState.h"
#include "../widgets/JsonViewer.h"
#include "../widgets/MemoryFilterBar.h"
#include "../widgets/PageHeader.h"
#include "../widgets/StatusTag.h"

namespace {
// P0-13：按 errorCode / 网络状态区分失败原因，避免笼统显示 "HTTP 503"。
// 注意：后端返回 503 时 Qt 会同时置 networkError，因此必须先判 errorCode 再判 networkError。
QString safetyFailText(const api::Result &r, const QString &what) {
    if (r.errorCode == QLatin1String("safety.gate_unavailable"))
        return QStringLiteral("安全门禁不可用（门禁未装配），请联系管理员部署安全门禁");
    if (r.networkError)
        return QStringLiteral("后端离线或网络错误：")
            + (r.networkErrorText.isEmpty() ? r.errorMessage : r.networkErrorText);
    QString msg = r.errorMessage;
    if (!r.errorCode.isEmpty())
        msg = r.errorCode + (msg.isEmpty() ? QString() : QStringLiteral(" - ") + msg);
    return what + QStringLiteral("加载失败：") + (msg.isEmpty() ? QStringLiteral("未知错误") : msg);
}
} // namespace

// ============================================================
// P6.1 安全总览
// ============================================================
SafetyOverviewPage::SafetyOverviewPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("安全总览");
    header->setSubtitle("敏感信息门禁语义 · 策略概况 · 组件状态");
    root->addWidget(header);

    // 四张语义说明卡
    struct Sem { const char *title; const char *desc; const char *color; };
    const Sem sems[4] = {
        {"ALLOW · 放行", "事件明文进入管线，正常沉淀记忆", "#16A34A"},
        {"MASK · 脱敏", "命中内容被替换为占位符后再进入管线", "#D97706"},
        {"REVIEW · 人工复核", "事件进入加密隔离区，等待人工审查", "#2563EB"},
        {"REJECT · 拒绝", "事件被丢弃，不进入管线并记录审计", "#DC2626"},
    };
    auto *grid = new QGridLayout();
    grid->setSpacing(12);
    for (int i = 0; i < 4; ++i) {
        auto *card = new QFrame(this);
        card->setObjectName("card");
        auto *cl = new QVBoxLayout(card);
        auto *t = new QLabel(sems[i].title, card);
        t->setStyleSheet(QString("color:%1;font-weight:700;font-size:14px;").arg(sems[i].color));
        auto *d = new QLabel(sems[i].desc, card);
        d->setWordWrap(true);
        d->setObjectName("pageSubtitle");
        cl->addWidget(t);
        cl->addWidget(d);
        grid->addWidget(card, i / 2, i % 2);
    }
    root->addLayout(grid);

    auto *policyCard = new QFrame(this);
    policyCard->setObjectName("card");
    auto *pl = new QVBoxLayout(policyCard);
    auto *pt = new QLabel("安全策略", policyCard);
    pt->setObjectName("cardTitle");
    pl->addWidget(pt);
    m_policyLabel = new QLabel(policyCard);
    m_policyLabel->setTextFormat(Qt::RichText);
    m_policyLabel->setWordWrap(true);
    m_policyLabel->setStyleSheet("color:#374151;font-size:13px;line-height:1.8;");
    pl->addWidget(m_policyLabel);
    root->addWidget(policyCard);

    auto *statusCard = new QFrame(this);
    statusCard->setObjectName("card");
    auto *sl = new QVBoxLayout(statusCard);
    auto *st = new QLabel("组件状态", statusCard);
    st->setObjectName("cardTitle");
    sl->addWidget(st);
    m_statusLabel = new QLabel(statusCard);
    m_statusLabel->setTextFormat(Qt::RichText);
    m_statusLabel->setWordWrap(true);
    m_statusLabel->setStyleSheet("color:#374151;font-size:13px;line-height:1.8;");
    sl->addWidget(m_statusLabel);
    root->addWidget(statusCard);
    root->addStretch();
}

void SafetyOverviewPage::refresh() {
    const int generation = ++m_generation;
    m_statusLabel->setText("正在加载组件状态…");
    m_policyLabel->setText("正在加载策略…");
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync("/api/memory/system/status", [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    if (r.ok && r.hasJsonObject()) {
        const QJsonObject s = r.jsonObject();
        const QJsonObject safety = j::obj(s, "safety");
        m_statusLabel->setText(QString(
            "<b>安全门禁</b> %1<br/><b>用户规则服务</b> %2<br/><b>审计</b> %3　<b>隔离区</b> %4<br/>"
            "<b>规则集</b> %5 · v%6")
            .arg(j::boolean(safety, "gate_available") ? "可用" : "不可用")
            .arg(j::boolean(safety, "user_rule_service_available") ? "可用" : "不可用")
            .arg(j::boolean(safety, "audit_enabled") ? "已开启" : "未开启")
            .arg(j::boolean(safety, "quarantine_enabled") ? "已开启" : "未开启")
            .arg(j::str(safety, "rule_set_id"), j::str(safety, "rule_set_version")));
    } else {
        m_statusLabel->setText("组件状态加载失败：" + r.errorMessage.toHtmlEscaped());
    }
    }, this);
    api->getAsync("/api/memory/system/config", [this, generation](const api::Result &rc) {
    if (generation != m_generation) return;
    if (rc.ok && rc.hasJsonObject()) {
        const QJsonObject cfg = rc.jsonObject();
        const QJsonObject safety = j::obj(cfg, "safety");
        const QJsonObject policy = j::obj(safety, "policy");
        m_policyLabel->setText(QString(
            "<b>策略 ID</b> %1 · <b>版本</b> %2<br/><b>fallback_action</b> %3　<b>fail_closed</b> %4<br/>"
            "<b>auto_mask</b> %5")
            .arg(j::str(policy, "policy_id"), j::str(policy, "version"))
            .arg(j::str(policy, "fallback_action"))
            .arg(j::boolean(policy, "fail_closed") ? "是" : "否")
            .arg(j::boolean(safety, "auto_mask") ? "是" : "否"));
    } else {
        m_policyLabel->setText("策略加载失败：" + rc.errorMessage.toHtmlEscaped());
    }
    }, this);
}

// ============================================================
// P6.2 用户规则
// ============================================================
SafetyUserRulesPage::SafetyUserRulesPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("用户规则");
    header->setSubtitle("自定义敏感信息规则 · matcher 密文写入，保存后不可回显");
    m_addBtn = new QPushButton(QIcon(":/icons/plus.svg"), "新增规则", this);
    m_addBtn->setObjectName("primaryBtn");
    connect(m_addBtn, &QPushButton::clicked, this, &SafetyUserRulesPage::openCreateDialog);
    header->actionLayout()->addWidget(m_addBtn);
    root->addWidget(header);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索规则标签...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &SafetyUserRulesPage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { if (m_rulesLoaded) renderRows(); });
    root->addWidget(m_filterBar);

    m_table = new QTableWidget(this);
    m_table->setColumnCount(8);
    m_table->setHorizontalHeaderLabels({"标签", "类型", "效果", "大小写敏感", "版本", "启用", "更新时间", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    m_table->setColumnWidth(1, 110);
    m_table->setColumnWidth(2, 110);
    m_table->setColumnWidth(3, 90);
    m_table->setColumnWidth(4, 60);
    m_table->setColumnWidth(5, 70);
    m_table->setColumnWidth(6, 130);
    m_table->setColumnWidth(7, 200);
    root->addWidget(m_table, 1);
}

void SafetyUserRulesPage::refresh() { onRefresh(); }

void SafetyUserRulesPage::onRefresh() { loadTable(); }

void SafetyUserRulesPage::loadTable() {
    m_rulesLoaded = false;
    m_all = QJsonArray();
    m_table->clearSpans();
    m_table->setRowCount(0);
    const int generation = ++m_generation;
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync("/api/memory/safety/user-rules", [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    m_table->setRowCount(0);
    if (!r.ok || !r.hasJsonArray()) {
        m_table->setRowCount(1);
        auto *empty = new EmptyState();
        empty->setIcon(QIcon(":/icons/shield.svg"));
        empty->setTitle("用户规则加载失败");
        empty->setHint(r.errorMessage.isEmpty() ? r.errorCode : r.errorMessage);
        m_table->setCellWidget(0, 0, empty);
        m_table->setSpan(0, 0, 1, 8);
        return;
    }
    m_all = r.jsonArray();
    m_rulesLoaded = true;
    renderRows();
    }, true, this);
}

void SafetyUserRulesPage::renderRows() {
    // 数据已全量在手，搜索词本地过滤，不重新请求
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    m_table->clearSpans();
    m_table->setRowCount(0);
    int row = 0;
    for (const QJsonValue &v : m_all) {
        const QJsonObject rule = v.toObject();
        if (!kw.isEmpty() && !j::str(rule, "label").contains(kw, Qt::CaseInsensitive)) continue;
        m_table->insertRow(row);
        m_table->setItem(row, 0, new QTableWidgetItem(j::str(rule, "label")));
        m_table->setItem(row, 1, new QTableWidgetItem(j::str(rule, "kind")));
        m_table->setItem(row, 2, new QTableWidgetItem(j::str(rule, "effect")));
        m_table->setItem(row, 3, new QTableWidgetItem(j::boolean(rule, "case_sensitive") ? "是" : "否"));
        m_table->setItem(row, 4, new QTableWidgetItem(QString("v%1").arg(j::integer(rule, "revision"))));
        auto *enabledCheck = new QCheckBox();
        enabledCheck->setChecked(j::boolean(rule, "enabled"));
        const QString rid = j::str(rule, "rule_id");
        const int revision = j::integer(rule, "revision");
        connect(enabledCheck, &QCheckBox::toggled, this, [this, rid, revision](bool on) {
            toggleEnabled(rid, revision, on);
        });
        m_table->setCellWidget(row, 5, enabledCheck);
        m_table->setItem(row, 6, new QTableWidgetItem(j::timeAgo(j::str(rule, "updated_at"))));
        auto *ops = new QWidget();
        auto *ol = new QHBoxLayout(ops);
        ol->setContentsMargins(0, 0, 0, 0);
        ol->setSpacing(2);
        auto mk = [ops](const QString &t) { auto *b = new QPushButton(t, ops); b->setObjectName("textBtn"); return b; };
        auto *bEdit = mk("编辑");
        auto *bDel = mk("删除");
        bDel->setStyleSheet("color:#EF4444;");
        connect(bEdit, &QPushButton::clicked, this, [this, rule]() { openEditDialog(rule); });
        connect(bDel, &QPushButton::clicked, this, [this, rid, revision]() { removeRule(rid, revision); });
        ol->addWidget(bEdit);
        ol->addWidget(bDel);
        m_table->setCellWidget(row, 7, ops);
        ++row;
    }
}

void SafetyUserRulesPage::openCreateDialog() {
    QDialog dlg(this);
    dlg.setWindowTitle("新增敏感信息规则");
    dlg.setMinimumWidth(460);
    auto *form = new QFormLayout(&dlg);
    auto *labelEdit = new QLineEdit(&dlg);
    form->addRow("标签 *", labelEdit);
    auto *kindCombo = new QComboBox(&dlg);
    kindCombo->addItem("literal（字面匹配）", "literal");
    kindCombo->addItem("advanced_regex（正则）", "advanced_regex");
    form->addRow("类型", kindCombo);
    auto *effectCombo = new QComboBox(&dlg);
    effectCombo->addItem("mask_match（脱敏）", "mask_match");
    effectCombo->addItem("drop_event（丢弃事件）", "drop_event");
    form->addRow("效果", effectCombo);
    auto *matcherEdit = new QPlainTextEdit(&dlg);
    matcherEdit->setPlaceholderText("要匹配的敏感信息（密文写入，保存后不可回显）");
    matcherEdit->setFixedHeight(70);
    form->addRow("匹配串 *", matcherEdit);
    auto *caseCheck = new QCheckBox("区分大小写", &dlg);
    form->addRow("", caseCheck);
    auto *enabledCheck = new QCheckBox("启用", &dlg);
    enabledCheck->setChecked(true);
    form->addRow("", enabledCheck);
    auto *bb = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dlg);
    bb->button(QDialogButtonBox::Ok)->setText("创建");
    bb->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(bb, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(bb, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(bb);
    if (dlg.exec() != QDialog::Accepted) return;
    if (labelEdit->text().trimmed().isEmpty() || matcherEdit->toPlainText().trimmed().isEmpty()) {
        QMessageBox::warning(this, "提示", "标签与匹配串不能为空");
        return;
    }
    QJsonObject body;
    body["label"] = labelEdit->text().trimmed();
    body["kind"] = kindCombo->currentData().toString();
    body["effect"] = effectCombo->currentData().toString();
    body["matcher"] = matcherEdit->toPlainText().trimmed();
    body["case_sensitive"] = caseCheck->isChecked();
    body["enabled"] = enabledCheck->isChecked();
    QPointer<QPushButton> btn = qobject_cast<QPushButton *>(sender());
    if (btn) btn->setEnabled(false);
    AppContext::instance()->api()->postAsync(
        "/api/memory/safety/user-rules", body,
        [this, btn](const api::Result &r) {
            if (btn) btn->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", "规则已创建");
                onRefresh();
            } else {
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }, /*useUserHeader=*/true, this);
}

void SafetyUserRulesPage::openEditDialog(const QJsonObject &rule) {
    QDialog dlg(this);
    dlg.setWindowTitle("编辑规则 · " + j::str(rule, "label"));
    dlg.setMinimumWidth(460);
    auto *form = new QFormLayout(&dlg);
    auto *labelEdit = new QLineEdit(&dlg);
    labelEdit->setText(j::str(rule, "label"));
    form->addRow("标签", labelEdit);
    auto *effectCombo = new QComboBox(&dlg);
    effectCombo->addItem("mask_match（脱敏）", "mask_match");
    effectCombo->addItem("drop_event（丢弃事件）", "drop_event");
    effectCombo->setCurrentIndex(effectCombo->findData(j::str(rule, "effect")));
    form->addRow("效果", effectCombo);
    auto *matcherEdit = new QPlainTextEdit(&dlg);
    matcherEdit->setPlaceholderText("留空则不修改匹配串（原串不回显）");
    matcherEdit->setFixedHeight(60);
    form->addRow("匹配串", matcherEdit);
    auto *enabledCheck = new QCheckBox("启用", &dlg);
    enabledCheck->setChecked(j::boolean(rule, "enabled"));
    form->addRow("", enabledCheck);
    auto *revLabel = new QLabel(QString("当前版本 v%1（乐观并发，冲突会提示刷新）").arg(j::integer(rule, "revision")));
    revLabel->setObjectName("pageSubtitle");
    form->addRow("", revLabel);
    auto *bb = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dlg);
    bb->button(QDialogButtonBox::Ok)->setText("保存");
    bb->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(bb, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(bb, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(bb);
    if (dlg.exec() != QDialog::Accepted) return;

    QJsonObject body;
    body["expected_revision"] = j::integer(rule, "revision");
    if (labelEdit->text().trimmed() != j::str(rule, "label"))
        body["label"] = labelEdit->text().trimmed();
    if (effectCombo->currentData().toString() != j::str(rule, "effect"))
        body["effect"] = effectCombo->currentData().toString();
    if (!matcherEdit->toPlainText().trimmed().isEmpty())
        body["matcher"] = matcherEdit->toPlainText().trimmed();
    if (enabledCheck->isChecked() != j::boolean(rule, "enabled"))
        body["enabled"] = enabledCheck->isChecked();
    if (body.size() <= 1) { QMessageBox::information(this, "提示", "没有需要修改的内容"); return; }

    QPointer<QPushButton> btn = qobject_cast<QPushButton *>(sender());
    if (btn) btn->setEnabled(false);
    AppContext::instance()->api()->patchAsync(
        "/api/memory/safety/user-rules/" + j::str(rule, "rule_id"), body,
        [this, btn](const api::Result &r) {
            if (btn) btn->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", "规则已更新");
                onRefresh();
            } else if (r.errorCode == "user_rule.conflict") {
                QMessageBox::warning(this, "并发冲突", "该规则已被他人修改，请刷新后重试。");
            } else {
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }, /*useUserHeader=*/true, this);
}

void SafetyUserRulesPage::toggleEnabled(const QString &ruleId, int revision, bool on) {
    QPointer<QCheckBox> check = qobject_cast<QCheckBox *>(sender());
    if (check) check->setEnabled(false);
    QJsonObject body;
    body["expected_revision"] = revision;
    body["enabled"] = on;
    AppContext::instance()->api()->patchAsync(
        "/api/memory/safety/user-rules/" + ruleId, body,
        [this, check, on](const api::Result &r) {
            if (check) check->setEnabled(true);
            if (r.ok) {
                // 静默成功：避免每次切换都弹模态打断
                onRefresh();
            } else {
                // 失败回滚复选框，避免界面显示与后端状态不一致
                if (check) {
                    check->blockSignals(true);
                    check->setChecked(!on);
                    check->blockSignals(false);
                }
                QMessageBox::warning(this, "切换失败", r.errorCode + " " + r.errorMessage);
            }
        }, /*useUserHeader=*/true, this);
}

void SafetyUserRulesPage::removeRule(const QString &ruleId, int revision) {
    if (!ConfirmDialog::confirm(this, "删除规则", "确认删除该规则？")) return;
    QPointer<QPushButton> btn = qobject_cast<QPushButton *>(sender());
    if (btn) btn->setEnabled(false);
    AppContext::instance()->api()->deleteAsync(
        api::ApiClient::urlWithQuery("/api/memory/safety/user-rules/" + ruleId,
                                     {{"expected_revision", QString::number(revision)}}),
        [this, btn](const api::Result &r) {
            if (btn) btn->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", "规则已删除");
                onRefresh();
            } else {
                QMessageBox::warning(this, "删除失败", r.errorCode + " " + r.errorMessage);
            }
        }, /*useUserHeader=*/true, this);
}

// ============================================================
// P6.3 审计日志
// ============================================================
SafetyAuditPage::SafetyAuditPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("审计日志");
    header->setSubtitle("安全处置审计记录（HMAC 哈希链）");
    m_verifyBtn = new QPushButton("验链", this);
    m_verifyBtn->setObjectName("primaryBtn");
    connect(m_verifyBtn, &QPushButton::clicked, this, &SafetyAuditPage::verifyChain);
    header->actionLayout()->addWidget(m_verifyBtn);
    root->addWidget(header);

    m_stateLabel = new QLabel(this);
    m_stateLabel->setStyleSheet("padding:8px;border-radius:6px;");
    m_stateLabel->hide();
    root->addWidget(m_stateLabel);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索 audit_id / event_ref...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &SafetyAuditPage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { renderRows(); });
    root->addWidget(m_filterBar);

    m_table = new QTableWidget(this);
    m_table->setColumnCount(6);
    m_table->setHorizontalHeaderLabels({"audit_id", "event_ref", "决策", "规则集", "原因码", "时间"});
    m_table->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    root->addWidget(m_table, 1);
}

void SafetyAuditPage::refresh() { onRefresh(); }

void SafetyAuditPage::onRefresh() { loadTable(); }

void SafetyAuditPage::loadTable() {
    const int generation = ++m_generation;
    m_all = QJsonArray();
    m_total = 0;
    m_table->setRowCount(0);
    m_stateLabel->setText("正在加载…");
    m_stateLabel->show();
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/safety/audit-logs", {{"limit", "200"}, {"offset", "0"}}),
        [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    m_table->setRowCount(0);
    if (!r.ok || !r.hasJsonObject()) {
        m_loadFailed = true;
        m_failText = r.errorCode == "safety.audit_disabled"
            ? QStringLiteral("审计功能未开启（safety.audit_disabled）")
            : safetyFailText(r, QStringLiteral("审计日志"));
        renderRows();
        return;
    }
    m_stateLabel->hide();
    m_loadFailed = false;
    m_all = j::arr(r.jsonObject(), "items");
    m_total = j::integer(r.jsonObject(), "total", m_all.size());
    renderRows();
    }, this);
}

void SafetyAuditPage::renderRows() {
    m_table->setRowCount(0);
    if (m_loadFailed) {
        m_stateLabel->show();
        m_stateLabel->setStyleSheet("background:#FFFBEB;border:1px solid #FDE68A;border-radius:6px;"
                                    "color:#92400E;padding:8px;");
        m_stateLabel->setText(m_failText);
        return;
    }
    m_stateLabel->hide();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    int row = 0;
    for (const QJsonValue &v : m_all) {
        const QJsonObject rec = v.toObject();
        const QString aid = j::str(rec, "audit_id");
        if (!kw.isEmpty() && !aid.contains(kw, Qt::CaseInsensitive) &&
            !j::str(rec, "event_ref").contains(kw, Qt::CaseInsensitive)) continue;
        m_table->insertRow(row);
        m_table->setItem(row, 0, new QTableWidgetItem(aid));
        m_table->setItem(row, 1, new QTableWidgetItem(j::str(rec, "event_ref")));
        auto *tag = new StatusTag();
        tag->setStatus(j::str(rec, "decision"));
        m_table->setCellWidget(row, 2, tag);
        m_table->setItem(row, 3, new QTableWidgetItem(j::str(rec, "rule_set_version")));
        m_table->setItem(row, 4, new QTableWidgetItem(j::strList(rec, "reason_codes").join(", ")));
        auto *timeItem = new QTableWidgetItem(j::timeAgo(j::str(rec, "created_at")));
        timeItem->setToolTip(j::fmtTime(j::str(rec, "created_at")));
        m_table->setItem(row, 5, timeItem);
        ++row;
    }
    // 接口固定 limit=200：超出部分不可见时必须如实提示，避免"审计完整"的错觉
    if (m_total > m_all.size()) {
        const int row2 = m_table->rowCount();
        m_table->insertRow(row2);
        auto *hint = new QTableWidgetItem(
            QString("仅显示最近 %1 条（共 %2 条）；更早记录请缩小时间范围或调大后端 limit。")
                .arg(m_all.size()).arg(m_total));
        hint->setForeground(QBrush(QColor("#92400E")));
        m_table->setItem(row2, 0, hint);
        m_table->setSpan(row2, 0, 1, 6);
    }
}

void SafetyAuditPage::verifyChain() {
    m_verifyBtn->setEnabled(false);
    AppContext::instance()->api()->getAsync("/api/memory/safety/audit-logs/verify",
        [this](const api::Result &r) {
            m_verifyBtn->setEnabled(true);
            if (r.ok && r.hasJsonObject()) {
                const bool valid = j::boolean(r.jsonObject(), "valid");
                QMessageBox::information(this, "验链结果", valid ? "哈希链校验通过" : "校验失败：" + j::str(r.jsonObject(), "code"));
            } else QMessageBox::warning(this, "验链失败", r.errorCode + " " + r.errorMessage);
        }, this);
}

// ============================================================
// P6.4 隔离区
// ============================================================
SafetyQuarantinePage::SafetyQuarantinePage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);
    auto *header = new PageHeader(this);
    header->setTitle("隔离区");
    header->setSubtitle("REVIEW 事件人工审查：查看原文（解密）→ 放行 / 驳回 / 删除");
    root->addWidget(header);

    m_stateLabel = new QLabel(this);
    m_stateLabel->setStyleSheet("padding:8px;border-radius:6px;");
    m_stateLabel->hide();
    root->addWidget(m_stateLabel);

    m_filterBar = new MemoryFilterBar(this);
    m_filterBar->setSearchPlaceholder("搜索 review_id...");
    connect(m_filterBar, &MemoryFilterBar::refreshRequested, this, &SafetyQuarantinePage::onRefresh);
    connect(m_filterBar, &MemoryFilterBar::searchTextChanged, this,
            [this](const QString &) { renderRows(); });
    root->addWidget(m_filterBar);

    m_table = new QTableWidget(this);
    m_table->setColumnCount(5);
    m_table->setHorizontalHeaderLabels({"review_id", "event_ref", "创建时间", "过期时间", "操作"});
    m_table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setAlternatingRowColors(true);
    m_table->setColumnWidth(1, 160);
    m_table->setColumnWidth(4, 220);
    root->addWidget(m_table, 1);
}

void SafetyQuarantinePage::refresh() { onRefresh(); }

void SafetyQuarantinePage::onRefresh() { loadTable(); }

void SafetyQuarantinePage::loadTable() {
    const int generation = ++m_generation;
    m_all = QJsonArray();
    m_table->setRowCount(0);
    m_stateLabel->setText("正在加载…");
    m_stateLabel->show();
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync("/api/memory/safety/quarantine", [this, generation](const api::Result &r) {
    if (generation != m_generation) return;
    m_table->setRowCount(0);
    if (!r.ok || !r.hasJsonObject()) {
        m_loadFailed = true;
        m_failText = r.errorCode == "safety.quarantine_disabled"
            ? QStringLiteral("隔离区未开启（safety.quarantine_disabled）")
            : safetyFailText(r, QStringLiteral("隔离区"));
        renderRows();
        return;
    }
    m_stateLabel->hide();
    m_loadFailed = false;
    m_all = j::arr(r.jsonObject(), "items");
    renderRows();
    }, this);
}

void SafetyQuarantinePage::renderRows() {
    m_table->setRowCount(0);
    if (m_loadFailed) {
        m_stateLabel->show();
        m_stateLabel->setStyleSheet("background:#FFFBEB;border:1px solid #FDE68A;border-radius:6px;"
                                    "color:#92400E;padding:8px;");
        m_stateLabel->setText(m_failText);
        return;
    }
    m_stateLabel->hide();
    const QString kw = m_filterBar->searchBox()->text().trimmed();
    int row = 0;
    for (const QJsonValue &v : m_all) {
        const QJsonObject rec = v.toObject();
        const QString rid = j::str(rec, "review_id");
        if (!kw.isEmpty() && !rid.contains(kw, Qt::CaseInsensitive) &&
            !j::str(rec, "event_ref").contains(kw, Qt::CaseInsensitive)) continue;
        m_table->insertRow(row);
        m_table->setItem(row, 0, new QTableWidgetItem(rid));
        m_table->setItem(row, 1, new QTableWidgetItem(j::str(rec, "event_ref")));
        m_table->setItem(row, 2, new QTableWidgetItem(j::timeAgo(j::str(rec, "created_at"))));
        m_table->setItem(row, 3, new QTableWidgetItem(j::timeAgo(j::str(rec, "expires_at"))));
        auto *ops = new QWidget();
        auto *ol = new QHBoxLayout(ops);
        ol->setContentsMargins(0, 0, 0, 0);
        ol->setSpacing(2);
        auto mk = [ops](const QString &t) { auto *b = new QPushButton(t, ops); b->setObjectName("textBtn"); return b; };
        auto *bView = mk("查看原文");
        auto *bAllow = mk("放行");
        auto *bReject = mk("驳回");
        auto *bDel = mk("删除");
        bDel->setStyleSheet("color:#EF4444;");
        connect(bView, &QPushButton::clicked, this, [this, rid]() { viewRecord(rid); });
        connect(bAllow, &QPushButton::clicked, this, [this, rid]() { releaseRecord(rid, "allow"); });
        connect(bReject, &QPushButton::clicked, this, [this, rid]() { releaseRecord(rid, "reject"); });
        connect(bDel, &QPushButton::clicked, this, [this, rid]() { deleteRecord(rid); });
        ol->addWidget(bView);
        ol->addWidget(bAllow);
        ol->addWidget(bReject);
        ol->addWidget(bDel);
        m_table->setCellWidget(row, 4, ops);
        ++row;
    }
}

void SafetyQuarantinePage::viewRecord(const QString &reviewId) {
    if (!ConfirmDialog::confirm(this, "特权审查",
                                "查看原文将解密隔离事件内容。确认继续？")) return;
    const int token = ++m_viewGeneration;
    api::ApiClient *api = AppContext::instance()->api();
    api->getAsync("/api/memory/safety/quarantine/" + reviewId,
        [this, token, reviewId](const api::Result &r) {
            if (token != m_viewGeneration) return;
            if (!r.ok || !r.hasJsonObject()) {
                const QString message = r.errorCode == "safety.quarantine_disabled"
                    ? "隔离区未开启（safety.quarantine_disabled）"
                    : safetyFailText(r, "隔离事件详情");
                QMessageBox::warning(this, "读取失败", message);
                return;
            }
            QDialog dlg(this);
            dlg.setWindowTitle("隔离事件原文 · " + j::shortId(reviewId));
            dlg.resize(620, 480);
            auto *lay = new QVBoxLayout(&dlg);
            auto *view = new JsonViewer(&dlg);
            view->setObject(r.jsonObject());
            lay->addWidget(view, 1);
            dlg.exec();
        }, this);
}

void SafetyQuarantinePage::releaseRecord(const QString &reviewId, const QString &decision) {
    // 放行/驳回都是不可逆处置，必须二次确认（与同页"删除"一致）
    if (decision == "allow") {
        if (!ConfirmDialog::confirm(this, "放行事件",
                                    "放行后事件将重新进入处理管线并生成记忆。确认放行？")) return;
    } else {
        if (!ConfirmDialog::confirm(this, "驳回事件",
                                    "驳回将直接删除该隔离记录（不可恢复），事件不会进入管线。确认驳回？",
                                    "驳回")) return;
    }
    QPointer<QPushButton> btn = qobject_cast<QPushButton *>(sender());
    if (btn) btn->setEnabled(false);
    QJsonObject body;
    body["decision"] = decision;
    body["user_id"] = AppContext::instance()->userId();
    AppContext::instance()->api()->postAsync(
        "/api/memory/safety/quarantine/" + reviewId + "/release", body,
        [this, btn, decision](const api::Result &r) {
            if (btn) btn->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", decision == "allow" ? "已放行，事件重新进入管线" : "已驳回，隔离记录已删除");
                onRefresh();
            } else {
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }, this);
}

void SafetyQuarantinePage::deleteRecord(const QString &reviewId) {
    if (!ConfirmDialog::confirm(this, "删除隔离记录", "确认删除该隔离记录？")) return;
    QPointer<QPushButton> btn = qobject_cast<QPushButton *>(sender());
    if (btn) btn->setEnabled(false);
    AppContext::instance()->api()->deleteAsync(
        "/api/memory/safety/quarantine/" + reviewId,
        [this, btn](const api::Result &r) {
            if (btn) btn->setEnabled(true);
            if (r.ok) {
                QMessageBox::information(this, "完成", "隔离记录已删除");
                onRefresh();
            } else {
                QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
            }
        }, this);
}
