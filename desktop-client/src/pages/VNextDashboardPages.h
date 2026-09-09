#pragma once

#include "BasePage.h"

class VNextDashboardPage : public BasePage {
    Q_OBJECT
public:
    enum class View { Explorer, Evolution, RetrievalDebugger, Benchmark };

    explicit VNextDashboardPage(View view, QWidget *parent = nullptr);
    QString pageKey() const override;
    void refresh() override;

private:
    View m_view;
    class QLineEdit *m_tenant = nullptr;
    class QLineEdit *m_adminToken = nullptr;
    class QTableWidget *m_table = nullptr;
    class QLabel *m_summary = nullptr;
    class PageStateView *m_state = nullptr;
    int m_generation = 0;
};
