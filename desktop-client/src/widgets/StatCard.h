#pragma once
// 统计卡片：图标 + 大数字 + 副标题 + 可选微趋势，支持整卡点击。

#include <QFrame>
#include <QIcon>

class QLabel;

class StatCard : public QFrame {
    Q_OBJECT
public:
    explicit StatCard(QWidget *parent = nullptr);

    void setIcon(const QIcon &icon);
    void setIconText(const QString &text); // 兼容旧页面，Dashboard 使用 SVG 图标
    void setNumber(const QString &num);
    void setCaption(const QString &caption);
    void setTrend(const QString &trend, bool good = true); // 空则隐藏
    void setClickable(bool on);
    void setLoading(bool on);
    void setError(const QString &message);

signals:
    void clicked();

protected:
    void mousePressEvent(QMouseEvent *e) override;
    void mouseReleaseEvent(QMouseEvent *e) override;
    void enterEvent(QEvent *e) override;
    void leaveEvent(QEvent *e) override;
    void keyPressEvent(QKeyEvent *e) override;

private:
    QLabel *m_icon = nullptr;
    QLabel *m_number = nullptr;
    QLabel *m_caption = nullptr;
    QLabel *m_trend = nullptr;
    bool m_clickable = false;
    bool m_pressed = false;
};
