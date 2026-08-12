#pragma once
// 总览 Dashboard：统计卡片 + 类型占比环图 + 状态分布柱图 + 最近事件 + 系统状态

#include "BasePage.h"

#include <QList>

class QGridLayout;
class QLabel;
class StatCard;
class QTableWidget;
class QLabel;
namespace QtCharts {
class QChartView;
class QPieSeries;
class QBarSet;
class QBarSeries;
}

class DashboardPage : public BasePage {
    Q_OBJECT
public:
    explicit DashboardPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "dashboard"; }

private:
    void loadStats();
    void loadCharts(int pref, int know, int fact);
    void loadRecentEvents();
    void loadSystemStatus();
    void showBackendOffline();

    QGridLayout *m_statGrid = nullptr;
    QList<StatCard *> m_statCards;

    QtCharts::QChartView *m_pieView = nullptr;
    QtCharts::QPieSeries *m_pieSeries = nullptr;
    QtCharts::QChartView *m_barView = nullptr;
    QtCharts::QBarSeries *m_barSeries = nullptr;

    QTableWidget *m_eventTable = nullptr;
    QLabel *m_statusBody = nullptr;
};
