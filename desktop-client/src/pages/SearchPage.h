#pragma once
// 检索测试页：混合检索 + 结果分组展示 + 上下文预览 + 性能/请求 JSON 侧栏

#include "BasePage.h"

#include <QJsonArray>
#include <QJsonObject>

class QLineEdit;
class QPushButton;
class QSpinBox;
class QDoubleSpinBox;
class QComboBox;
class QCheckBox;
class QVBoxLayout;
class QLabel;
class QScrollArea;

class SearchPage : public BasePage {
    Q_OBJECT
public:
    explicit SearchPage(QWidget *parent = nullptr);

    void refresh() override;
    void applySearchQuery(const QString &query) override;
    QString pageKey() const override { return "search"; }

private slots:
    void runSearch();

private:
    void renderResults(const QJsonObject &resp);
    void renderGroup(const QString &title, const QColor &color, const QJsonArray &items);
    void generateContext();
    QJsonObject updateRequestJson();

    QLineEdit *m_queryEdit = nullptr;
    QComboBox *m_sceneCombo = nullptr;
    QLineEdit *m_taskEdit = nullptr;
    QSpinBox *m_topK = nullptr;
    QCheckBox *m_cbPreference = nullptr;
    QCheckBox *m_cbKnowledge = nullptr;
    QCheckBox *m_cbFact = nullptr;
    QDoubleSpinBox *m_minConf = nullptr;

    QVBoxLayout *m_resultsLayout = nullptr;
    QWidget *m_resultsContainer = nullptr;
    QScrollArea *m_resultsScroll = nullptr;

    QLabel *m_latencyLabel = nullptr;
    QLabel *m_totalLabel = nullptr;
    QLabel *m_cacheLabel = nullptr;
    QLabel *m_contextText = nullptr;
    QPushButton *m_copyContextBtn = nullptr;

    QJsonObject m_lastRequest;
    QJsonObject m_lastResponse;
};
