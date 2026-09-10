#include "ConflictPage.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../api/ApiClient.h"
#include "../api/Json.h"
#include "../widgets/EmptyState.h"
#include "../widgets/PageHeader.h"
#include "../widgets/PageStateView.h"
#include "../widgets/StatusTag.h"

ConflictPage::ConflictPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("冲突中心");
    header->setSubtitle("新旧记忆内容对比 · 裁决仅记录结论，不自动覆盖/合并记忆");
    root->addWidget(header);

    // 统计条
    auto *statRow = new QHBoxLayout();
    statRow->setSpacing(16);
    m_statPending = new QLabel("待处理：—");
    m_statPending->setStyleSheet("color:#B45309;font-weight:600;font-size:14px;");
    m_statResolved = new QLabel("已解决：—");
    m_statResolved->setStyleSheet("color:#16A34A;font-weight:600;font-size:14px;");
    statRow->addWidget(m_statPending);
    statRow->addWidget(m_statResolved);
    statRow->addStretch();
    root->addLayout(statRow);

    // 筛选 + 分页
    auto *filterRow = new QHBoxLayout();
    m_statusCombo = new QComboBox(this);
    m_statusCombo->addItem("待确认", "pending");
    m_statusCombo->addItem("已解决", "resolved");
    m_statusCombo->addItem("全部", "");
    m_typeCombo = new QComboBox(this);
    m_typeCombo->addItem("全部类型", "");
    m_typeCombo->addItem("偏好", "preference");
    // 事实冲突已并入知识冲突链（后端 /facts/conflicts 亦然），
    // 不存在 memory_type="fact" 的冲突记录，故不提供该筛选项。
    m_typeCombo->addItem("知识", "knowledge");
    m_prevBtn = new QPushButton("上一页", this);
    m_prevBtn->setEnabled(false);
    m_nextBtn = new QPushButton("下一页", this);
    m_pageInfo = new QLabel("第 1 页", this);
    connect(m_prevBtn, &QPushButton::clicked, this, [this]() { loadPage(m_currentPage - 1); });
    connect(m_nextBtn, &QPushButton::clicked, this, [this]() { loadPage(m_currentPage + 1); });
    connect(m_statusCombo, qOverload<int>(&QComboBox::currentIndexChanged), this, &ConflictPage::onFilterChanged);
    // 类型过滤同样由服务端完成，切换后重新请求
    connect(m_typeCombo, qOverload<int>(&QComboBox::currentIndexChanged), this, &ConflictPage::onFilterChanged);
    filterRow->addWidget(m_statusCombo);
    filterRow->addWidget(m_typeCombo);
    filterRow->addStretch();
    filterRow->addWidget(m_prevBtn);
    filterRow->addWidget(m_pageInfo);
    filterRow->addWidget(m_nextBtn);
    root->addLayout(filterRow);

    // 卡片流
    m_scroll = new QScrollArea(this);
    m_scroll->setWidgetResizable(true);
    m_scroll->setFrameShape(QFrame::NoFrame);
    m_cardsContainer = new QWidget();
    m_cardsLayout = new QVBoxLayout(m_cardsContainer);
    m_cardsLayout->setContentsMargins(0, 8, 0, 0);
    m_cardsLayout->setSpacing(12);
    m_scroll->setWidget(m_cardsContainer);
    root->addWidget(m_scroll, 1);
    m_stateView = new PageStateView(this);
    m_stateView->hide();
    root->addWidget(m_stateView);
}

void ConflictPage::refresh() { loadPage(1); }

void ConflictPage::onFilterChanged() { loadPage(1); }

void ConflictPage::loadPage(int page) {
    while (QLayoutItem *item = m_cardsLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) { w->hide(); w->deleteLater(); }
        delete item;
    }
    m_statPending->setText("待处理：—");
    m_statResolved->setText("已解决：—");
    m_pageInfo->clear();
    m_prevBtn->setEnabled(false);
    m_nextBtn->setEnabled(false);
    m_currentPage = qMax(1, page);
    const int generation = ++m_generation;
    m_scroll->setEnabled(false);
    m_stateView->setState(PageState::Loading, "正在加载冲突", "正在读取统计与分页数据…");
    m_stateView->clearAction();
    const QString uid = AppContext::instance()->userId();
    api::ApiClient *api = AppContext::instance()->api();
    const QString status = m_statusCombo->currentData().toString();
    const QString type = m_typeCombo->currentData().toString();

    api->getAsync(api::ApiClient::urlWithQuery(
        "/api/memory/conflicts", {{"user_id", uid}, {"status", ""}}),
        [this, generation](const api::Result &rAll) {
            if (generation != m_generation) return;
            if (rAll.ok && rAll.hasJsonArray()) {
                int pending = 0, resolved = 0;
                for (const QJsonValue &v : rAll.jsonArray())
                    j::str(v.toObject(), "decision") == "pending" ? ++pending : ++resolved;
                m_statPending->setText(QString("待处理：%1").arg(pending));
                m_statResolved->setText(QString("已解决：%1").arg(resolved));
            } else {
                m_statPending->setText("待处理：加载失败");
                m_statResolved->setText("已解决：加载失败");
            }
        }, this);

    // 列表：过滤与分页全部交给服务端（status=resolved 表示"已裁决"，即 decision != pending）
    QList<QPair<QString, QString>> params{{"user_id", uid}, {"status", status}};
    if (!type.isEmpty()) params.append({"memory_type", type});
    params.append({"page", QString::number(m_currentPage)});
    params.append({"size", QString::number(m_size)});
    api->getAsync(api::ApiClient::urlWithQuery("/api/memory/conflicts", params),
        [this, generation](const api::Result &r) {
            if (generation != m_generation) return;
            m_scroll->setEnabled(true);
            if (!r.ok || !r.hasJsonObject()) {
                m_stateView->setState(r.networkError ? PageState::Offline : PageState::Error,
                                      r.networkError ? "后端离线" : "冲突加载失败",
                                      r.errorMessage.isEmpty() ? "请稍后重试。" : r.errorMessage);
                m_stateView->setAction("重试", [this]() { loadPage(m_currentPage); });
                return;
            }
            const QJsonArray items = j::arr(r.jsonObject(), "items");
            const int total = j::integer(r.jsonObject(), "total");
            m_total = total;
            m_stateView->setState(items.isEmpty() ? PageState::Empty : PageState::Content,
                                  "暂无冲突",
                                  "有偏好或知识写入冲突时会出现在这里；vNext 链路的冲突以 "
                                  "REVIEW 状态呈现在偏好/知识页的待审队列中。");
            if (items.isEmpty()) m_stateView->setAction("刷新", [this]() { loadPage(m_currentPage); });
            renderCards(items);
            const int maxPage = qMax(1, (total + m_size - 1) / m_size);
            m_pageInfo->setText(QString("第 %1 / %2 页 · 共 %3 条")
                                    .arg(m_currentPage).arg(maxPage).arg(total));
            m_prevBtn->setEnabled(m_currentPage > 1);
            m_nextBtn->setEnabled(m_currentPage < maxPage);
        }, this);
}

void ConflictPage::renderCards(const QJsonArray &items) {
    while (QLayoutItem *item = m_cardsLayout->takeAt(0)) {
        if (QWidget *w = item->widget()) w->deleteLater();
        delete item;
    }
    for (const QJsonValue &v : items) buildCard(m_cardsContainer, v.toObject());
    m_cardsLayout->addStretch();
}

void ConflictPage::buildCard(QWidget *parent, const QJsonObject &c) {
    auto *card = new QFrame(parent);
    card->setObjectName("card");
    auto *lay = new QVBoxLayout(card);
    lay->setContentsMargins(14, 12, 14, 12);
    lay->setSpacing(10);

    // 顶行：类型 + 决策 + 时间
    auto *top = new QHBoxLayout();
    auto *typeTag = new StatusTag();
    typeTag->setMemoryType(j::str(c, "memory_type"));
    top->addWidget(typeTag);
    const QString decision = j::str(c, "decision");
    auto *decTag = new StatusTag();
    decTag->setDecision(decision);
    top->addWidget(decTag);
    top->addStretch();
    auto *timeLabel = new QLabel(j::timeAgo(j::str(c, "created_at")));
    timeLabel->setObjectName("pageSubtitle");
    top->addWidget(timeLabel);
    lay->addLayout(top);

    // 新旧对比
    auto *cmp = new QGridLayout();
    cmp->setHorizontalSpacing(10);
    auto *oldTitle = new QLabel("旧内容");
    oldTitle->setStyleSheet("color:#DC2626;font-weight:600;font-size:12px;");
    auto *newTitle = new QLabel("新内容");
    newTitle->setStyleSheet("color:#16A34A;font-weight:600;font-size:12px;");
    auto *oldBox = new QLabel(j::str(c, "old_content"));
    oldBox->setWordWrap(true);
    oldBox->setTextFormat(Qt::PlainText);
    oldBox->setTextInteractionFlags(Qt::TextSelectableByMouse);
    oldBox->setStyleSheet("background:#FEF2F2;border:1px solid #FECACA;border-radius:6px;padding:8px;color:#7F1D1D;");
    auto *newBox = new QLabel(j::str(c, "new_content"));
    newBox->setWordWrap(true);
    newBox->setTextFormat(Qt::PlainText);
    newBox->setTextInteractionFlags(Qt::TextSelectableByMouse);
    newBox->setStyleSheet("background:#ECFDF5;border:1px solid #A7F3D0;border-radius:6px;padding:8px;color:#065F46;");
    cmp->addWidget(oldTitle, 0, 0);
    cmp->addWidget(newTitle, 0, 1);
    cmp->addWidget(oldBox, 1, 0);
    cmp->addWidget(newBox, 1, 1);
    lay->addLayout(cmp);

    // 冲突字段与原因（记忆内容源自用户/Agent 写入，必须转义防止富文本注入）
    auto *meta = new QLabel();
    meta->setWordWrap(true);
    meta->setTextFormat(Qt::RichText);
    meta->setStyleSheet("color:#6B7280;font-size:12px;");
    meta->setText(QString("冲突字段：<b>%1</b>　原因：%2")
                      .arg(j::str(c, "conflict_field").toHtmlEscaped(),
                           j::str(c, "reason").toHtmlEscaped()));
    lay->addWidget(meta);

    // 记忆 ID（只读、可选中）：便于到偏好/知识页核对同一条记忆
    const QString oldId = j::str(c, "old_memory_id");
    const QString newId = j::str(c, "new_memory_id");
    if (!oldId.isEmpty() || !newId.isEmpty()) {
        auto *ids = new QLabel(QString("旧记忆 %1 · 新记忆 %2")
                                   .arg(oldId.isEmpty() ? QStringLiteral("—") : oldId,
                                        newId.isEmpty() ? QStringLiteral("—") : newId));
        ids->setObjectName("pageSubtitle");
        ids->setWordWrap(true);
        ids->setTextFormat(Qt::PlainText);
        ids->setTextInteractionFlags(Qt::TextSelectableByMouse);
        lay->addWidget(ids);
    }

    // 底部操作区
    if (decision == "pending") {
        auto *row = new QHBoxLayout();
        row->addStretch();
        auto mkDecision = [this, &c](const QString &label, const QString &val, const QString &objName) {
            auto *b = new QPushButton(label);
            b->setObjectName(objName);
            connect(b, &QPushButton::clicked, this, [this, c, val]() { resolveConflict(c, val); });
            return b;
        };
        row->addWidget(mkDecision("覆盖 override", "override", "dangerBtn"));
        row->addWidget(mkDecision("合并 merge", "merge", ""));
        row->addWidget(mkDecision("并存 coexist", "coexist", "primaryBtn"));
        lay->addLayout(row);
    } else {
        auto *resolvedLabel = new QLabel(QString("已于 %1 解决").arg(j::fmtTime(j::str(c, "resolved_at"))));
        resolvedLabel->setObjectName("pageSubtitle");
        lay->addWidget(resolvedLabel);
    }
    m_cardsLayout->addWidget(card);
}

void ConflictPage::resolveConflict(const QJsonObject &c, const QString &decision) {
    if (m_writeInProgress) return;
    // 询问原因（可选）+ 是否落地
    QDialog dlg(this);
    dlg.setWindowTitle("记录裁决结论 · " + decision);
    dlg.setMinimumWidth(460);
    auto *form = new QFormLayout(&dlg);
    auto *hint = new QLabel("默认仅记录裁决结论（用于审计与统计），不修改记忆内容；"
                            "勾选下方选项后才会按裁决实际修改记忆。", &dlg);
    hint->setWordWrap(true);
    hint->setStyleSheet("color:#92400E;font-size:12px;");
    form->addRow(hint);
    auto *reasonEdit = new QLineEdit(&dlg);
    reasonEdit->setPlaceholderText("处理原因（可选）");
    form->addRow("原因", reasonEdit);
    auto *applyBox = new QCheckBox("同时应用到记忆（覆盖=归档旧记忆并生成新版本；"
                                   "合并=归档旧记忆并生成合并版本；并存=保留两条）", &dlg);
    applyBox->setChecked(false);
    form->addRow(applyBox);
    auto *bb = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dlg);
    bb->button(QDialogButtonBox::Ok)->setText("提交");
    bb->button(QDialogButtonBox::Cancel)->setText("取消");
    connect(bb, &QDialogButtonBox::accepted, &dlg, &QDialog::accept);
    connect(bb, &QDialogButtonBox::rejected, &dlg, &QDialog::reject);
    form->addRow(bb);
    if (dlg.exec() != QDialog::Accepted) return;

    QJsonObject body;
    body["user_id"] = AppContext::instance()->userId();
    body["decision"] = decision;
    body["reason"] = reasonEdit->text().trimmed();
    body["result_id"] = j::str(c, "result_memory_id");
    body["apply"] = applyBox->isChecked();

    api::ApiClient *api = AppContext::instance()->api();
    m_writeInProgress = true;
    AppContext::instance()->api()->postAsync(
        "/api/memory/conflicts/" + j::str(c, "conflict_id") + "/resolve", body,
        [this](const api::Result &r) {
            m_writeInProgress = false;
            if (r.ok) loadPage(m_currentPage);
            else QMessageBox::warning(this, "失败", r.errorCode + " " + r.errorMessage);
        }, this);
}
