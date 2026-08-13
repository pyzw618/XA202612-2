#pragma once

#include <QWidget>

class QResizeEvent;
class QShowEvent;
class RoundedBorderOverlay;

class RoundedContainer : public QWidget {
public:
    explicit RoundedContainer(QWidget *parent = nullptr);

    void setCornerRadius(int radius);

protected:
    void resizeEvent(QResizeEvent *event) override;
    void showEvent(QShowEvent *event) override;

private:
    void updateRoundedMask();
    void updateBorderOverlay();

    int m_cornerRadius = 10;
    RoundedBorderOverlay *m_borderOverlay = nullptr;
};
