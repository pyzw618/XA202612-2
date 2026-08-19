#pragma once

#include "BasePage.h"

#include <QJsonArray>
#include <QList>

class QLabel;
class QWidget;
class QVBoxLayout;
class QGridLayout;
class QHBoxLayout;
class PageStateView;
class StatCard;
class QFrame;
namespace QtCharts {
class QChartView;
class QPieSeries;
class QBarSeries;
}

class DashboardPage : public BasePage {
    Q_OBJECT
public:
    explicit DashboardPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "dashboard"; }

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;
    void resizeEvent(QResizeEvent *event) override;

private:
    void beginLoading();
    void finishRequest(bool ok);
    void updateMemoryVisuals();
    void updateActivity(const QJsonArray &items, bool ok);
    void updateTasks();
    void setBanner(const QString &text, const QString &state);

    QList<StatCard *> m_statCards;
    QtCharts::QPieSeries *m_pieSeries = nullptr;
    QtCharts::QBarSeries *m_barSeries = nullptr;
    QLabel *m_banner = nullptr;
    QLabel *m_chartEmpty = nullptr;
    QLabel *m_pieCenter = nullptr;
    QLabel *m_conflictCount = nullptr;
    QLabel *m_deadLetterCount = nullptr;
    QLabel *m_updateTime = nullptr;
    QWidget *m_activityContainer = nullptr;
    QVBoxLayout *m_activityLayout = nullptr;
    PageStateView *m_activityState = nullptr;
    QGridLayout *m_statsLayout = nullptr;
    QHBoxLayout *m_chartLayout = nullptr;
    QHBoxLayout *m_bottomLayout = nullptr;
    QFrame *m_barCard = nullptr;
    QFrame *m_pieCard = nullptr;
    QFrame *m_activityCard = nullptr;
    QFrame *m_taskCard = nullptr;
    bool m_narrowLayout = false;

    int m_generation = 0;
    int m_pendingRequests = 0;
    int m_successfulRequests = 0;
    int m_pref = -1;            // 偏好记忆总数
    int m_know = -1;            // 知识记忆总数
    int m_knowWorkflow = -1;    // 知识·工作流
    int m_knowCase = -1;        // 知识·案例
    int m_knowTemplate = -1;    // 知识·模板
    int m_knowFact = -1;        // 知识·事实（原独立事实记忆并入知识）
    int m_conflicts = -1;
    int m_deadLetters = -1;
};
