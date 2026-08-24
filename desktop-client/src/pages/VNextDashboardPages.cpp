#include "VNextDashboardPages.h"

#include <QFrame>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

#include "../AppContext.h"
#include "../widgets/PageHeader.h"

namespace {
struct ViewSpec { const char *title; const char *subtitle; const char *detail; const char *key; };

ViewSpec spec(VNextDashboardPage::View view) {
    switch (view) {
    case VNextDashboardPage::View::Explorer:
        return {"Memory Explorer", "Evidence · Lineage · 版本 · Activation",
                "按 trace 和记忆 ID 查看证据链；默认仅显示脱敏标识。", "dashboard/explorer"};
    case VNextDashboardPage::View::Evolution:
        return {"Evolution", "Formation · Evolution · Forget 链路",
                "查看状态变化和父子 span 关联；正文不会进入页面。", "dashboard/evolution"};
    case VNextDashboardPage::View::RetrievalDebugger:
        return {"Retrieval Debugger", "意图 · 分数 · Scope · Budget",
                "查看检索决策、分数和预算汇总；需要后端管理授权。", "dashboard/retrieval"};
    case VNextDashboardPage::View::Benchmark:
        return {"Benchmark", "四层评测 · 对照 · 消融",
                "展示固定数据版本、指标汇总和置信区间，不展示原始查询。", "dashboard/benchmark"};
    }
    return {"Dashboard", "", "", "dashboard"};
}
}

VNextDashboardPage::VNextDashboardPage(View view, QWidget *parent)
    : BasePage(parent), m_view(view) {
    const ViewSpec current = spec(view);
    auto *layout = new QVBoxLayout(this);
    auto *header = new PageHeader(this);
    header->setTitle(current.title);
    header->setSubtitle(current.subtitle);
    layout->addWidget(header);

    auto *notice = new QLabel("默认脱敏 · 管理权限受控 · 访问会记录审计日志", this);
    notice->setObjectName("inlineBanner");
    notice->setWordWrap(true);
    layout->addWidget(notice);

    auto *card = new QFrame(this);
    card->setObjectName("dashboardCard");
    auto *cardLayout = new QVBoxLayout(card);
    auto *detail = new QLabel(current.detail, card);
    detail->setWordWrap(true);
    cardLayout->addWidget(detail);
    layout->addWidget(card);

    for (View target : {View::Explorer, View::Evolution, View::RetrievalDebugger, View::Benchmark}) {
        const ViewSpec destination = spec(target);
        auto *button = new QPushButton(destination.title, this);
        button->setObjectName(target == view ? "secondaryButton" : "primaryButton");
        button->setEnabled(target != view);
        connect(button, &QPushButton::clicked, this, [destination]() {
            AppContext::instance()->navigate(destination.key);
        });
        layout->addWidget(button);
    }
    layout->addStretch(1);
}

QString VNextDashboardPage::pageKey() const {
    return spec(m_view).key;
}
