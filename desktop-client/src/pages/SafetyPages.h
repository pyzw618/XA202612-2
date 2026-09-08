#pragma once
// 安全中心 · 4 个子页
// 安全总览 / 用户规则 CRUD / 审计日志 / 隔离区

#include "BasePage.h"

#include <QJsonArray>

class QTableWidget;
class QLabel;
class QPushButton;
class MemoryFilterBar;

class SafetyOverviewPage : public BasePage {
    Q_OBJECT
public:
    explicit SafetyOverviewPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "safety/overview"; }

private:
    QLabel *m_policyLabel = nullptr;
    QLabel *m_statusLabel = nullptr;
    int m_generation = 0;
};

class SafetyUserRulesPage : public BasePage {
    Q_OBJECT
public:
    explicit SafetyUserRulesPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "safety/user-rules"; }

private slots:
    void onRefresh();
    void openCreateDialog();
    void openEditDialog(const QJsonObject &rule);
    void toggleEnabled(const QString &ruleId, int revision, bool on);
    void removeRule(const QString &ruleId, int revision);

private:
    void loadTable();
    void renderRows();

    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    QPushButton *m_addBtn = nullptr;
    QJsonArray m_all;
    int m_generation = 0;
};

class SafetyAuditPage : public BasePage {
    Q_OBJECT
public:
    explicit SafetyAuditPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "safety/audit"; }

private slots:
    void onRefresh();
    void verifyChain();

private:
    void loadTable();
    void renderRows();

    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    QPushButton *m_verifyBtn = nullptr;
    QLabel *m_stateLabel = nullptr;
    QJsonArray m_all;
    int m_total = 0;
    bool m_loadFailed = false;
    QString m_failText;
    int m_generation = 0;
};

class SafetyQuarantinePage : public BasePage {
    Q_OBJECT
public:
    explicit SafetyQuarantinePage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "safety/quarantine"; }

private slots:
    void onRefresh();
    void viewRecord(const QString &reviewId);
    void releaseRecord(const QString &reviewId, const QString &decision);
    void deleteRecord(const QString &reviewId);

private:
    void loadTable();
    void renderRows();

    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    QLabel *m_stateLabel = nullptr;
    QJsonArray m_all;
    bool m_loadFailed = false;
    QString m_failText;
    int m_generation = 0;
    int m_viewGeneration = 0;
};
