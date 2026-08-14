#include "ScoreRing.h"

#include <QPainter>
#include <QPainterPath>
#include <QVBoxLayout>

ScoreRing::ScoreRing(QWidget *parent) : QWidget(parent) {
    setFixedSize(m_diameter, m_diameter + 18);
}

void ScoreRing::setValue(double v) {
    m_value = qBound(0.0, v, 1.0);
    update();
}

void ScoreRing::setLabel(const QString &text) { m_label = text; update(); }

void ScoreRing::setCaption(const QString &text) { m_caption = text; update(); }

void ScoreRing::setSize(int diameter) {
    m_diameter = qMax(28, diameter);
    setFixedSize(m_diameter, m_diameter + 18);
    update();
}

QColor ScoreRing::colorForValue(double v) const {
    if (v >= 0.6) return QColor("#16A34A");
    if (v >= 0.4) return QColor("#D97706");
    return QColor("#DC2626");
}

void ScoreRing::paintEvent(QPaintEvent *) {
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);

    const int cx = m_diameter / 2;
    const int cy = m_diameter / 2;
    const int ringW = qMax(4, m_diameter / 10);

    // 背景环
    QPen bgPen(QColor("#EEF0F3"), ringW);
    p.setPen(bgPen);
    p.drawEllipse(QPointF(cx, cy), m_diameter / 2 - ringW / 2 - 1, m_diameter / 2 - ringW / 2 - 1);

    // 前景弧
    const QColor c = colorForValue(m_value);
    QPen fgPen(c, ringW, Qt::SolidLine, Qt::RoundCap);
    p.setPen(fgPen);
    const int radius = m_diameter / 2 - ringW / 2 - 1;
    const double startAngle = 90 * 16; // 从顶部开始
    const double span = -m_value * 360 * 16;
    p.drawArc(cx - radius, cy - radius, radius * 2, radius * 2, int(startAngle), int(span));

    // 中央文字（百分比或自定义）
    QString center = m_label;
    if (center.isEmpty()) {
        center = QString::number(qRound(m_value * 100)) + "%";
    }
    p.setPen(QColor("#262626"));
    QFont f = p.font();
    f.setBold(true);
    f.setPointSizeF(qMax(7.0, m_diameter / 6.5));
    p.setFont(f);
    p.drawText(QRect(0, 0, m_diameter, m_diameter), Qt::AlignCenter, center);

    // 底部说明
    if (!m_caption.isEmpty()) {
        p.setPen(QColor("#8A8F99"));
        QFont cf = p.font();
        cf.setBold(false);
        cf.setPointSizeF(8);
        p.setFont(cf);
        p.drawText(QRect(0, m_diameter, m_diameter, 18), Qt::AlignHCenter | Qt::AlignTop, m_caption);
    }
}
