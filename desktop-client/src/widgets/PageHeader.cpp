#include "PageHeader.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QVBoxLayout>

PageHeader::PageHeader(QWidget *parent) : QWidget(parent) {
    auto *main = new QHBoxLayout(this);
    main->setContentsMargins(0, 0, 0, 0);
    main->setSpacing(8);

    m_prefix = new QLabel(this);
    m_prefix->setObjectName("pageSubtitle");
    m_prefix->hide();

    m_title = new QLabel(this);
    m_title->setObjectName("pageTitle");

    m_subtitle = new QLabel(this);
    m_subtitle->setObjectName("pageSubtitle");
    m_subtitle->setWordWrap(true);

    auto *left = new QVBoxLayout();
    left->setSpacing(2);
    auto *titleRow = new QHBoxLayout();
    titleRow->setSpacing(6);
    titleRow->addWidget(m_prefix);
    titleRow->addWidget(m_title);
    titleRow->addStretch();
    left->addLayout(titleRow);
    left->addWidget(m_subtitle);

    m_actionLayout = new QHBoxLayout();
    m_actionLayout->setSpacing(8);

    main->addLayout(left, 1);
    main->addLayout(m_actionLayout);
}

void PageHeader::setTitle(const QString &title) { m_title->setText(title); }

void PageHeader::setSubtitle(const QString &subtitle) {
    m_subtitle->setText(subtitle);
    m_subtitle->setVisible(!subtitle.isEmpty());
}

void PageHeader::setTitlePrefix(const QString &prefix) {
    m_prefix->setText(prefix);
    m_prefix->setVisible(!prefix.isEmpty());
}
