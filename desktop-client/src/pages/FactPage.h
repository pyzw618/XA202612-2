#pragma once
// 事实记忆管理页：三元组表格 + 手动提案 + 候选裁决 + 详情抽屉

#include "BasePage.h"

#include <QJsonArray>
#include <QJsonObject>

class QTableWidget;
class QComboBox;
class MemoryFilterBar;
class DetailDrawer;
class QPushButton;
class QVBoxLayout;
class QWidget;
class PageStateView;

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
    void renderCandidates();

private:
    void populateRow(int row, const QJsonObject &f);
    void openEditDialog(const QJsonObject &fact);
    void removeCandidate(const QString &proposalId);

    MemoryFilterBar *m_filterBar = nullptr;
    QComboBox *m_scopeCombo = nullptr;
    QComboBox *m_statusCombo = nullptr;
    QTableWidget *m_table = nullptr;
    DetailDrawer *m_drawer = nullptr;
    QPushButton *m_proposeBtn = nullptr;

    QVBoxLayout *m_candidateLayout = nullptr; // 候选裁决区
    QWidget *m_candidateContainer = nullptr;
    QWidget *m_content = nullptr;
    PageStateView *m_stateView = nullptr;

    QJsonArray m_all;
    QJsonArray m_candidates;  // 本会话提案（裁决区）
    int m_generation = 0;
    int m_detailGeneration = 0;
};
