#include "EmptyState.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

EmptyState::EmptyState(QWidget *parent) : QWidget(parent) {
    m_icon = new QLabel(this);
    m_icon->setObjectName("emptyIcon");
    m_icon->setAlignment(Qt::AlignCenter);

    m_title = new QLabel(this);
    m_title->setObjectName("emptyTitle");
    m_title->setAlignment(Qt::AlignCenter);

    m_hint = new QLabel(this);
    m_hint->setObjectName("emptyHint");
    m_hint->setAlignment(Qt::AlignCenter);
    m_hint->setWordWrap(true);

    auto *lay = new QVBoxLayout(this);
    lay->setAlignment(Qt::AlignCenter);
    lay->setSpacing(6);
    lay->addWidget(m_icon);
    lay->addWidget(m_title);
    lay->addWidget(m_hint);
}

void EmptyState::setIconText(const QString &t) { m_icon->setText(t); }
void EmptyState::setTitle(const QString &t) { m_title->setText(t); }
void EmptyState::setHint(const QString &h) {
    m_hint->setText(h);
    m_hint->setVisible(!h.isEmpty());
}

QPushButton *EmptyState::addButton(const QString &text) {
    auto *btn = new QPushButton(text, this);
    btn->setObjectName("primaryBtn");
    auto *lay = static_cast<QVBoxLayout *>(layout());
    auto *row = new QHBoxLayout();
    row->addStretch();
    row->addWidget(btn);
    row->addStretch();
    lay->addLayout(row);
    return btn;
}
