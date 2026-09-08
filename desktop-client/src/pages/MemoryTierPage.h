#pragma once
// 记忆分层流转页（I-5）：短期（工作记忆）/ 中期（情景）视图 + 手动触发分层流转。

#include "BasePage.h"

#include <QJsonArray>

class QLabel;
class QPushButton;
class QTableWidget;

class MemoryTierPage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit MemoryTierPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "mem/tiers"; }

private slots:
    void load();
    void runConsolidate();

private:
    void loadShortTerm();
    void loadMidTerm();
    void populateShort(int row, const QJsonObject &item);
    void populateMid(int row, const QJsonObject &item);

    QTableWidget *m_shortTable = nullptr;
    QTableWidget *m_midTable = nullptr;
    QLabel *m_shortSummary = nullptr;
    QLabel *m_midSummary = nullptr;
    QPushButton *m_consolidateBtn = nullptr;
    QJsonArray m_short;
    QJsonArray m_mid;
    int m_generation = 0;
};
