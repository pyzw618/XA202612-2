#pragma once
// 知识记忆管理页：名称/类型/成功率表格 + 详情抽屉（步骤/版本/复用统计）

#include "BasePage.h"

#include <QJsonArray>
#include <QJsonObject>

class QTableWidget;
class QComboBox;
class MemoryFilterBar;
class DetailDrawer;
class QPushButton;
class PageStateView;
class QWidget;

class KnowledgePage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit KnowledgePage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "mem/knowledge"; }

private slots:
    void onRefresh();
    void applyLocalFilter();
    void openDetail(const QString &id);
    void openEditDialog(const QJsonObject &memory, bool isNew);

private:
    void populateRow(int row, const QJsonObject &m);
    void buildDetail(const QString &id, const QJsonObject &m);
    QList<QString> selectedIds() const;

    MemoryFilterBar *m_filterBar = nullptr;
    QComboBox *m_typeCombo = nullptr;
    QComboBox *m_statusCombo = nullptr;
    QTableWidget *m_table = nullptr;
    DetailDrawer *m_drawer = nullptr;
    QPushButton *m_batchDelete = nullptr;
    QPushButton *m_addBtn = nullptr;
    QWidget *m_content = nullptr;
    PageStateView *m_stateView = nullptr;
    QJsonArray m_all;
    int m_generation = 0;
    int m_detailGeneration = 0;
};
