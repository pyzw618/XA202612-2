#pragma once

#include "BasePage.h"

class VNextDashboardPage : public BasePage {
    Q_OBJECT
public:
    enum class View { Explorer, Evolution, RetrievalDebugger, Benchmark };

    explicit VNextDashboardPage(View view, QWidget *parent = nullptr);
    QString pageKey() const override;

private:
    View m_view;
};
