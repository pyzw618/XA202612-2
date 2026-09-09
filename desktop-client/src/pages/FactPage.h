#pragma once
// 事实记忆管理页：三元组表格 + 手动提案 + 详情抽屉

#include "BasePage.h"

#include <QJsonArray>
#include <QJsonObject>

class QTableWidget;
class QComboBox;
class MemoryFilterBar;
class DetailDrawer;
class QPushButton;
class QWidget;
class PageStateView;
class QVBoxLayout;

class FactPage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit FactPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "mem/fact"; }

private slots:
    void onRefresh();
    void applyLocalFilter();
    void openDetail(const QString &id);
    void openProposeDialog();

private:
    void populateRow(int row, const QJsonObject &f);
    void openEditDialog(const QJsonObject &fact);
    void renderCandidates();
    void removeCandidate(const QString &proposalId);

    MemoryFilterBar *m_filterBar = nullptr;
    QComboBox *m_scopeCombo = nullptr;
    QComboBox *m_statusCombo = nullptr;
    QTableWidget *m_table = nullptr;
    DetailDrawer *m_drawer = nullptr;
    QPushButton *m_proposeBtn = nullptr;

    QWidget *m_content = nullptr;
    PageStateView *m_stateView = nullptr;
    QWidget *m_candidateContainer = nullptr;
    QVBoxLayout *m_candidateLayout = nullptr;

    QJsonArray m_all;
    QJsonArray m_candidates;
    int m_generation = 0;
    int m_detailGeneration = 0;
};
