#include "PageStateView.h"

#include <QHBoxLayout>
#include <QIcon>
#include <QLabel>
#include <QPushButton>
#include <QStyle>
#include <QVariant>
#include <QVBoxLayout>

PageStateView::PageStateView(QWidget *parent) : QWidget(parent) {
    setObjectName("pageStateView");
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 28, 24, 28);
    layout->setSpacing(8);
    layout->setAlignment(Qt::AlignCenter);

    m_icon = new QLabel(this);
    m_icon->setObjectName("pageStateIcon");
    m_icon->setAlignment(Qt::AlignCenter);
    m_icon->setFixedHeight(24);
    layout->addWidget(m_icon);

    m_title = new QLabel(this);
    m_title->setObjectName("pageStateTitle");
    m_title->setAlignment(Qt::AlignCenter);
    layout->addWidget(m_title);

    m_description = new QLabel(this);
    m_description->setObjectName("pageStateDescription");
    m_description->setWordWrap(true);
    m_description->setAlignment(Qt::AlignCenter);
    layout->addWidget(m_description);

    m_action = new QPushButton(this);
    m_action->setObjectName("pageStateAction");
    m_action->setFocusPolicy(Qt::StrongFocus);
    m_action->setAccessibleName("页面状态操作");
    m_action->hide();
    layout->addWidget(m_action, 0, Qt::AlignCenter);
}

void PageStateView::setState(PageState state, const QString &title,
                             const QString &description, const QIcon &icon) {
    m_state = state;
    setProperty("state", state == PageState::Loading ? "loading"
                : state == PageState::Empty ? "empty"
                : state == PageState::Error ? "error"
                : state == PageState::Offline ? "offline" : "content");
    m_title->setText(title);
    m_description->setText(description);
    m_icon->setPixmap(icon.isNull() ? QPixmap() : icon.pixmap(22, 22));
    style()->unpolish(this);
    style()->polish(this);
    setVisible(state != PageState::Content);
}

void PageStateView::setAction(const QString &text, const std::function<void()> &action) {
    m_action->setText(text);
    m_action->show();
    disconnect(m_action, nullptr, this, nullptr);
    connect(m_action, &QPushButton::clicked, this, [action]() { if (action) action(); });
}

void PageStateView::clearAction() {
    m_action->hide();
    disconnect(m_action, nullptr, this, nullptr);
}
