#include "BasePage.h"
#include "../AppContext.h"

BasePage::BasePage(QWidget *parent) : QWidget(parent) {
    connect(AppContext::instance(), &AppContext::userIdChanged, this, [this]() {
        refresh();
    });
}
