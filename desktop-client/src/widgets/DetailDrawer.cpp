#include "DetailDrawer.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QStackedWidget>
#include <QVBoxLayout>

DetailDrawer::DetailDrawer(QWidget *parent) : QFrame(parent) {
    setObjectName("drawer");
    setMinimumWidth(440);
    setMaximumWidth(560);
    hide();

    m_title = new QLabel(this);
    m_title->setObjectName("drawerTitle");

    auto *closeBtn = new QPushButton("✕", this);
    closeBtn->setObjectName("textBtn");
    closeBtn->setToolTip("关闭");
    connect(closeBtn, &QPushButton::clicked, this, &DetailDrawer::closeDrawer);

    m_headerBtns = new QHBoxLayout();
    m_headerBtns->setSpacing(6);

    auto *header = new QHBoxLayout();
    header->setContentsMargins(16, 14, 16, 10);
    header->setSpacing(8);
    header->addWidget(m_title, 1);
    header->addLayout(m_headerBtns);
    header->addWidget(closeBtn);

    m_stack = new QStackedWidget(this);

    auto *main = new QVBoxLayout(this);
    main->setContentsMargins(0, 0, 0, 0);
    main->setSpacing(0);
    main->addLayout(header);
    main->addWidget(m_stack, 1);
}

void DetailDrawer::setWidth(int w) {
    setMinimumWidth(w);
    setMaximumWidth(w);
}

void DetailDrawer::setContent(QWidget *content) {
    m_stack->addWidget(content);
}

void DetailDrawer::open(const QString &title, QWidget *content) {
    m_title->setText(title);
    // 移除之前的 content（若已设置）
    if (m_stack->count() > 0) {
        QWidget *old = m_stack->widget(0);
        m_stack->removeWidget(old);
        old->deleteLater();
    }
    if (content) m_stack->addWidget(content);
    show();
    m_open = true;
    raise();
}

QPushButton *DetailDrawer::addHeaderButton(const QString &text, const QString &objName) {
    auto *btn = new QPushButton(text, this);
    btn->setObjectName(objName);
    m_headerBtns->addWidget(btn);
    return btn;
}

void DetailDrawer::closeDrawer() {
    hide();
    m_title->clear();
    while (m_stack->count() > 0) {
        QWidget *old = m_stack->widget(0);
        m_stack->removeWidget(old);
        old->hide();
        old->deleteLater();
    }
    m_open = false;
    emit closed();
}
