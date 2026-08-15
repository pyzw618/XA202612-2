#pragma once
// API v2 统一溯源面板：展示 lineage、脱敏 evidence 与关联审计记录。

#include <QString>
#include <QTabWidget>

class QLabel;
class QTableWidget;

class ProvenancePanel : public QTabWidget {
    Q_OBJECT
public:
    explicit ProvenancePanel(const QString &memoryId, QWidget *parent = nullptr);

private:
    void loadLineage();
    void loadEvidence();
    void loadAudit();
    QString endpoint(const QString &suffix) const;

    QString m_memoryId;
    QLabel *m_lineageState = nullptr;
    QLabel *m_evidenceState = nullptr;
    QLabel *m_auditState = nullptr;
    QTableWidget *m_lineageTable = nullptr;
    QTableWidget *m_evidenceTable = nullptr;
    QTableWidget *m_auditTable = nullptr;
};
