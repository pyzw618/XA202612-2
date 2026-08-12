#include "StatCard.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QVBoxLayout>

StatCard::StatCard(QWidget *parent) : QFrame(parent) {
    setObjectName("card");
    setCursor(Qt::ArrowCursor);

    m_icon = new QLabel(this);
    m_icon->setFixedSize(42, 42);
    m_icon->setAlignment(Qt::AlignCenter);
    m_icon->setStyleSheet("background: #EFF6FF; border-radius: 10px; font-size: 20px;");

    m_number = new QLabel(this);
    m_number->setStyleSheet("font-size: 26px; font-weight: 700; color: #1F2430;");

    m_caption = new QLabel(this);
    m_caption->setObjectName("pageSubtitle");

    m_trend = new QLabel(this);
    m_trend->setStyleSheet("font-size: 12px;");
    m_trend->hide();

    auto *textCol = new QVBoxLayout();
    textCol->setSpacing(2);
    textCol->addWidget(m_number);
    textCol->addWidget(m_caption);
    textCol->addWidget(m_trend);

    auto *row = new QHBoxLayout(this);
    row->setContentsMargins(14, 12, 14, 12);
    row->setSpacing(12);
    row->addWidget(m_icon);
    row->addLayout(textCol, 1);
}

void StatCard::setIconText(const QString &t) { m_icon->setText(t); }
void StatCard::setNumber(const QString &n) { m_number->setText(n); }
void StatCard::setCaption(const QString &c) { m_caption->setText(c); }

void StatCard::setTrend(const QString &trend, bool good) {
    m_trend->setText(trend);
    m_trend->setStyleSheet(good ? "font-size: 12px; color: #16A34A;" : "font-size: 12px; color: #DC2626;");
    m_trend->setVisible(!trend.isEmpty());
}

void StatCard::setClickable(bool on) {
    m_clickable = on;
    setCursor(on ? Qt::PointingHandCursor : Qt::ArrowCursor);
}

void StatCard::enterEvent(QEvent *e) {
    if (m_clickable) {
        setStyleSheet("QFrame#card { border: 1px solid #3790FA; }");
    }
    QFrame::enterEvent(e);
}

void StatCard::leaveEvent(QEvent *e) {
    if (m_clickable) {
        setStyleSheet("");
    }
    QFrame::leaveEvent(e);
}

void StatCard::mousePressEvent(QMouseEvent *e) {
    if (m_clickable && e->button() == Qt::LeftButton) m_pressed = true;
    QFrame::mousePressEvent(e);
}

void StatCard::mouseReleaseEvent(QMouseEvent *e) {
    if (m_pressed && m_clickable && e->button() == Qt::LeftButton && rect().contains(e->pos())) {
        m_pressed = false;
        emit clicked();
    }
    QFrame::mouseReleaseEvent(e);
}
