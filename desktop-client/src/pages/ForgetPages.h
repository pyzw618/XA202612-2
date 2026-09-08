#pragma once
// 遗忘与生命周期 · 7 个子页
// 精准遗忘 / 待审查队列 / 归档仓库 / 回收站 / 健康度看板 / 遗忘历史 / 遗忘设置

#include "BasePage.h"

#include <QJsonArray>
#include <QJsonObject>
#include <QList>
#include <QStringList>

class QTabWidget;
class QLineEdit;
class QComboBox;
class QTableWidget;
class QVBoxLayout;
class QWidget;
class QPushButton;
class QLabel;
class QCheckBox;
class QListWidget;
class MemoryFilterBar;

// ---- P4.1 精准遗忘：NL / 范围 / ID 三种定位 + 预览 + 执行 ----
class ForgetPrecisePage : public BasePage {
    Q_OBJECT
public:
    explicit ForgetPrecisePage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/precise"; }

private slots:
    void doPreview();
    void doExecute();

private:
    QJsonObject buildPreviewRequest();
    void renderCandidates(const QList<QString> &ids);
    QList<QString> selectedCandidateIds() const;

    QTabWidget *m_tabs = nullptr;
    // NL tab
    QLineEdit *m_nlInput = nullptr;
    // 范围 tab
    QLineEdit *m_scopeScene = nullptr;
    QLineEdit *m_scopeTask = nullptr;
    QComboBox *m_scopeType = nullptr;
    // ID tab
    QComboBox *m_idType = nullptr;
    QLineEdit *m_idSearch = nullptr;
    QListWidget *m_idList = nullptr;
    // 预览区
    QVBoxLayout *m_previewLayout = nullptr;
    QWidget *m_previewContainer = nullptr;
    QLabel *m_previewSummary = nullptr;
    QCheckBox *m_cascadeCheck = nullptr;
    QPushButton *m_executeBtn = nullptr;

    QJsonArray m_prefAll, m_knowAll, m_factAll;
    QList<QString> m_candidateIds;
    int m_generation = 0;
    int m_pendingLoads = 0;
    bool m_executeInProgress = false;
    QStringList m_loadFailures;
};

// ---- P4.2 待审查队列：pending 记忆，保持/归档/删除 ----
class ForgetPendingPage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit ForgetPendingPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/pending"; }

private slots:
    void onRefresh();
    void setSingleStatus(const QString &type, const QString &id, const QString &status,
                         QPushButton *caller = nullptr);
    void batchSetStatus(const QString &status, QPushButton *caller = nullptr);

private:
    void loadTable();
    QList<QString> selectedIds() const;

    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    QPushButton *m_allActive = nullptr;
    QPushButton *m_allArchive = nullptr;
    int m_generation = 0;
};

// ---- P4.3 归档仓库：archived 记忆，解除归档/删除 ----
class ForgetArchivedPage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit ForgetArchivedPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/archived"; }

private slots:
    void onRefresh();
    void unarchive(const QString &type, const QString &id, QPushButton *caller = nullptr);
    void deleteMemory(const QString &type, const QString &id, QPushButton *caller = nullptr);

private:
    void loadTable();
    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    int m_generation = 0;
};

// ---- P4.4 回收站：deleted 记忆，恢复/彻底删除 ----
class ForgetRecyclePage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit ForgetRecyclePage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/recycle"; }

private slots:
    void onRefresh();
    void restore(const QString &type, const QString &id, QPushButton *caller = nullptr);
    void hardDelete(const QString &id, QPushButton *caller = nullptr);

private:
    void loadTable();
    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    int m_generation = 0;
};

// ---- P4.5 健康度看板：分布直方图 + 衰减最快 TopN + 明细 ----
class ForgetHealthPage : public BasePage {
    Q_OBJECT
public:
    explicit ForgetHealthPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/health"; }

private:
    void loadData();
    QVBoxLayout *m_listLayout = nullptr;
    QWidget *m_listContainer = nullptr;
    QLabel *m_warningLabel = nullptr;
    QJsonArray m_items;
    int m_generation = 0;
};

// ---- P4.6 遗忘历史：ForgetRecord 列表 + 详情 ----
class ForgetHistoryPage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit ForgetHistoryPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/history"; }

private slots:
    void onRefresh();
    void openDetail(const QJsonObject &record);

private:
    MemoryFilterBar *m_filterBar = nullptr;
    QTableWidget *m_table = nullptr;
    int m_generation = 0;
};

// ---- P4.7 遗忘设置：权重/阈值只读展示 + 触发自动遗忘 ----
class ForgetSettingsPage : public BasePage {
    Q_OBJECT
public:
    explicit ForgetSettingsPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "forget/settings"; }

private slots:
    void runAutoForget(QPushButton *caller = nullptr);
    void runLifecycleCheck(QPushButton *caller = nullptr);

private:
    QLabel *m_weightsLabel = nullptr;
    QLabel *m_autoForgetLabel = nullptr;
    QLabel *m_lifecycleLabel = nullptr;
    QLabel *m_resultLabel = nullptr;
    int m_generation = 0;
};
