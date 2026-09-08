#pragma once
// 系统设置 · 4 个子页
// 后端状态 / LLM 服务 / 参数查看 / 演示数据工具

#include "BasePage.h"

class QLabel;
class QTableWidget;
class QVBoxLayout;
class QWidget;
class QPushButton;
class QLineEdit;

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
    int m_generation = 0;
};

class SettingsLLMPage : public BasePage {
    Q_OBJECT
public:
    explicit SettingsLLMPage(QWidget *parent = nullptr);
    void refresh() override;
    QString pageKey() const override { return "settings/llm"; }

private:
    void loadConfig();
    void saveConfig();

    QLineEdit *m_apiBase = nullptr;
    QLineEdit *m_apiKey = nullptr;
    QLineEdit *m_model = nullptr;
    QLabel *m_keyStatus = nullptr;
    QLabel *m_resultLabel = nullptr;
    QPushButton *m_saveButton = nullptr;
    int m_generation = 0;
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
    int m_generation = 0;
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
    QLabel *m_warningLabel = nullptr;
    QLabel *m_resultLabel = nullptr;
    QPushButton *m_clearPreferencesButton = nullptr;
    QPushButton *m_clearAllButton = nullptr;
};
