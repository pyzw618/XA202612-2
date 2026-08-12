#include "MemoryFilterBar.h"

#include <QHBoxLayout>
#include <QLineEdit>
#include <QPushButton>
#include <QTimer>

MemoryFilterBar::MemoryFilterBar(QWidget *parent) : QWidget(parent) {
    m_row = new QHBoxLayout(this);
    m_row->setContentsMargins(0, 0, 0, 0);
    m_row->setSpacing(8);

    m_search = new QLineEdit(this);
    m_search->setPlaceholderText("搜索...");
    m_search->setClearButtonEnabled(true);
    m_search->setMaximumWidth(220);

    m_refresh = new QPushButton("刷新", this);
    connect(m_refresh, &QPushButton::clicked, this, &MemoryFilterBar::refreshRequested);

    m_debounce = new QTimer(this);
    m_debounce->setSingleShot(true);
    m_debounce->setInterval(300);
    connect(m_debounce, &QTimer::timeout, this, [this]() {
        emit searchTextChanged(m_search->text().trimmed());
    });
    connect(m_search, &QLineEdit::textChanged, this, [this](const QString &) {
        m_debounce->start();
    });

    m_row->addWidget(m_search);
    m_row->addWidget(m_refresh);
}

void MemoryFilterBar::addWidget(QWidget *w) {
    if (w) m_row->insertWidget(m_row->count() - 1, w);
}

void MemoryFilterBar::addStretch() {
    m_row->insertStretch(m_row->count() - 1);
}

void MemoryFilterBar::setSearchPlaceholder(const QString &hint) {
    m_search->setPlaceholderText(hint);
}
