#include "StatCard.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QStyle>
#include <QKeyEvent>
#include <QVBoxLayout>

StatCard::StatCard(QWidget *parent) : QFrame(parent) {
    setObjectName("statCard");
    setCursor(Qt::ArrowCursor);

    m_icon = new QLabel(this);
    m_icon->setFixedSize(42, 42);
    m_icon->setAlignment(Qt::AlignCenter);
    m_icon->setObjectName("statIcon");

    m_number = new QLabel(this);
    m_number->setObjectName("statNumber");

    m_caption = new QLabel(this);
    m_caption->setObjectName("statCaption");

    m_trend = new QLabel(this);
    m_trend->setObjectName("statTrend");
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
void StatCard::setIcon(const QIcon &icon) {
    m_icon->setText(QString());
    m_icon->setPixmap(icon.pixmap(20, 20));
}
void StatCard::setNumber(const QString &n) { m_number->setText(n); }
void StatCard::setCaption(const QString &c) { m_caption->setText(c); }

void StatCard::setTrend(const QString &trend, bool good) {
    m_trend->setText(trend);
    m_trend->setStyleSheet(good ? "font-size: 12px; color: #16A34A;" : "font-size: 12px; color: #DC2626;");
    m_trend->setVisible(!trend.isEmpty());
}

void StatCard::setHint(const QString &hint) {
    m_trend->setText(hint);
    m_trend->setStyleSheet("font-size: 11px; color: #697180;");
    m_trend->setVisible(!hint.isEmpty());
}

void StatCard::setClickable(bool on) {
    m_clickable = on;
    setFocusPolicy(on ? Qt::StrongFocus : Qt::NoFocus);
    setAccessibleName(m_caption->text());
    setCursor(on ? Qt::PointingHandCursor : Qt::ArrowCursor);
}

void StatCard::setLoading(bool on) {
    setProperty("loading", on);
    if (on) {
        setProperty("state", "loading");
        setToolTip("正在加载");
    }
    m_number->setText(on ? QStringLiteral("—") : m_number->text());
    style()->unpolish(this);
    style()->polish(this);
}

bool StatCard::isLoading() const { return property("loading").toBool(); }

void StatCard::setError(const QString &message) {
    setProperty("loading", false);
    setProperty("state", "error");
    setToolTip(message);
    m_number->setText("不可用");
    style()->unpolish(this);
    style()->polish(this);
}

void StatCard::enterEvent(QEvent *e) {
    if (m_clickable) {
        setProperty("hovered", true);
        style()->unpolish(this);
        style()->polish(this);
    }
    QFrame::enterEvent(e);
}

void StatCard::leaveEvent(QEvent *e) {
    if (m_clickable) {
        setProperty("hovered", false);
        style()->unpolish(this);
        style()->polish(this);
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

void StatCard::keyPressEvent(QKeyEvent *e) {
    if (m_clickable && (e->key() == Qt::Key_Return || e->key() == Qt::Key_Space)) {
        emit clicked();
        e->accept();
        return;
    }
    QFrame::keyPressEvent(e);
}
