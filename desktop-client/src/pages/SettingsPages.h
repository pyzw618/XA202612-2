#pragma once
// 系统设置 · 3 个子页
// 后端状态 / 参数查看 / 演示数据工具

#include "BasePage.h"

class QLabel;
class QTableWidget;
class QVBoxLayout;
class QWidget;

class SettingsStatusPage : public BasePage {
    Q_OBJECT
public:
    explicit SettingsStatusPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "settings/status"; }

private:
    void loadStatus();

    QTableWidget *m_table = nullptr;
    QLabel *m_connLabel = nullptr;
};

class SettingsConfigPage : public BasePage {
    Q_OBJECT
public:
    explicit SettingsConfigPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "settings/config"; }

private:
    void loadConfig();
    void addGroup(QVBoxLayout *lay, const QString &title, const QString &html);

    QWidget *m_body = nullptr;
    QVBoxLayout *m_layout = nullptr;
};

class SettingsDemoPage : public BasePage {
    Q_OBJECT
public:
    explicit SettingsDemoPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "settings/demo"; }

private slots:
    void clearPreferences();
    void clearAllDemo();

private:
    QLabel *m_resultLabel = nullptr;
};
