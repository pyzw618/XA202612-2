#pragma once
// 冲突中心：统计条 + 筛选 + 冲突卡片流（新旧对比 + 裁决）+ 分页

#include "BasePage.h"

#include <QJsonArray>

class QComboBox;
class QVBoxLayout;
class QWidget;
class QLabel;
class QPushButton;
class QScrollArea;
class PageStateView;

class ConflictPage : public BasePage {
    Q_OBJECT
public:
    explicit ConflictPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "conflicts"; }

private slots:
    void loadPage(int page);
    void onFilterChanged();

private:
    void renderCards(const QJsonArray &items);
    void buildCard(QWidget *parent, const QJsonObject &c);
    void resolveConflict(const QJsonObject &c, const QString &decision);

    QComboBox *m_statusCombo = nullptr;
    QComboBox *m_typeCombo = nullptr;
    QVBoxLayout *m_cardsLayout = nullptr;
    QWidget *m_cardsContainer = nullptr;
    QScrollArea *m_scroll = nullptr;
    QLabel *m_statPending = nullptr;
    QLabel *m_statResolved = nullptr;
    QLabel *m_pageInfo = nullptr;
    QPushButton *m_prevBtn = nullptr;
    QPushButton *m_nextBtn = nullptr;
    PageStateView *m_stateView = nullptr;
    int m_generation = 0;
    bool m_writeInProgress = false;

    int m_currentPage = 1;
    int m_total = 0;
    int m_size = 10;
};
