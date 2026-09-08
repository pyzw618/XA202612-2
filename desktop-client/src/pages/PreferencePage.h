#pragma once
// 偏好记忆管理页：筛选栏 + 表格 + 详情抽屉 + 增删改 + 批量删除

#include "BasePage.h"

#include <QJsonArray>
#include <QJsonObject>
#include <QList>

class QTableWidget;
class QComboBox;
class QLineEdit;
class QDoubleSpinBox;
class MemoryFilterBar;
class DetailDrawer;
class QPushButton;
class PageStateView;
class QWidget;

class PreferencePage : public BasePage {
    Q_OBJECT
    friend class FrontendRegressionTest;
public:
    explicit PreferencePage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "mem/preference"; }

private slots:
    void onRefresh();
    void applyLocalFilter();
    void openDetail(const QString &memoryId);
    void openEditDialog(const QJsonObject &memory, bool isNew);
    void deleteSelected();

private:
    void loadTable();
    void populateRow(int row, const QJsonObject &m);
    void openFeedbackMenu(const QJsonObject &m);
    QList<QString> selectedIds() const;

    MemoryFilterBar *m_filterBar = nullptr;
    QComboBox *m_typeCombo = nullptr;
    QComboBox *m_statusCombo = nullptr;
    QLineEdit *m_sceneEdit = nullptr;
    QDoubleSpinBox *m_minConf = nullptr;
    QTableWidget *m_table = nullptr;
    DetailDrawer *m_drawer = nullptr;
    QPushButton *m_batchDelete = nullptr;
    QPushButton *m_addBtn = nullptr;
    QWidget *m_content = nullptr;
    PageStateView *m_stateView = nullptr;

    QJsonArray m_all;   // 最近一次从后端拉取的全量（未应用客户端过滤）
    int m_generation = 0;
};
