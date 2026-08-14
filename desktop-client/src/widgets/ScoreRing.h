#pragma once
// 分数进度环：用于置信度 / 健康度展示。
// 颜色语义：>=0.6 绿 / 0.4~0.6 琥珀 / <0.4 红

#include <QColor>
#include <QWidget>

class ScoreRing : public QWidget {
    Q_OBJECT
public:
    explicit ScoreRing(QWidget *parent = nullptr);

    void setValue(double v);                 // 0~1
    void setLabel(const QString &text);      // 环中央主文字（默认百分比）
    void setCaption(const QString &text);    // 环下方说明（如 "健康度"）
    void setSize(int diameter);              // 直径像素
    double value() const { return m_value; }

    QColor colorForValue(double v) const;

protected:
    void paintEvent(QPaintEvent *event) override;

private:
    double m_value = 0.0;
    int m_diameter = 48;
    QString m_label;
    QString m_caption;
};
