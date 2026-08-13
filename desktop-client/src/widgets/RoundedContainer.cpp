#include "RoundedContainer.h"

#include <QPainterPath>
#include <QPainter>
#include <QPaintEvent>
#include <QRegion>
#include <QResizeEvent>
#include <QShowEvent>

class RoundedBorderOverlay : public QWidget {
public:
    explicit RoundedBorderOverlay(QWidget *parent) : QWidget(parent) {
        setAttribute(Qt::WA_TransparentForMouseEvents, true);
        setAttribute(Qt::WA_NoSystemBackground, true);
        setAttribute(Qt::WA_TranslucentBackground, true);
    }

    void setCornerRadius(int radius) {
        m_cornerRadius = radius;
        update();
    }

protected:
    void paintEvent(QPaintEvent *event) override {
        Q_UNUSED(event)
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setBrush(Qt::NoBrush);
        painter.setPen(QPen(QColor("#C9D3E0"), 1.25));
        painter.drawRoundedRect(QRectF(rect()).adjusted(0.75, 0.75, -0.75, -0.75),
                                m_cornerRadius, m_cornerRadius);
    }

private:
    int m_cornerRadius = 10;
};

RoundedContainer::RoundedContainer(QWidget *parent) : QWidget(parent) {
    setAttribute(Qt::WA_StyledBackground, true);
    m_borderOverlay = new RoundedBorderOverlay(this);
}

void RoundedContainer::setCornerRadius(int radius) {
    m_cornerRadius = qMax(0, radius);
    updateRoundedMask();
    m_borderOverlay->setCornerRadius(m_cornerRadius);
}

void RoundedContainer::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);
    updateRoundedMask();
    updateBorderOverlay();
}

void RoundedContainer::showEvent(QShowEvent *event) {
    QWidget::showEvent(event);
    updateRoundedMask();
    updateBorderOverlay();
}

void RoundedContainer::updateRoundedMask() {
    if (width() <= 0 || height() <= 0) return;

    QPainterPath path;
    path.addRoundedRect(QRectF(rect()).adjusted(0.0, 0.0, -0.5, -0.5),
                        m_cornerRadius, m_cornerRadius);
    setMask(QRegion(path.toFillPolygon().toPolygon()));
}

void RoundedContainer::updateBorderOverlay() {
    m_borderOverlay->setGeometry(rect());
    m_borderOverlay->raise();
}
