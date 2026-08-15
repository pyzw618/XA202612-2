#pragma once
// Projection Outbox 管理：查看当前用户的 pending/failed 投影，并对失败项执行 replay。

#include "BasePage.h"

#include <QJsonArray>

class QComboBox;
class QLabel;
class QPushButton;
class QTableWidget;
class PageStateView;

class ProjectionPage : public BasePage {
    Q_OBJECT
public:
    explicit ProjectionPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "projections"; }

private slots:
    void load();
    void replaySelected();
    void replayAllFailed();

private:
    void replay(const QJsonArray &outboxIds, bool allFailed);
    QJsonArray selectedOutboxIds() const;

    QComboBox *m_status = nullptr;
    QTableWidget *m_table = nullptr;
    QLabel *m_summary = nullptr;
    QPushButton *m_replaySelected = nullptr;
    QPushButton *m_replayAll = nullptr;
    PageStateView *m_state = nullptr;
    QJsonArray m_items;
    int m_generation = 0;
};
