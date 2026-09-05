#pragma once
// 全局应用上下文：持有 ApiClient 实例、当前 user_id、后端 base URL。
// 通过 AppContext::instance() 访问；user_id 变化时发出信号以便各页刷新。

#include <QObject>
#include <QProcessEnvironment>
#include <QString>
#include <functional>

namespace api { class ApiClient; }

class AppContext : public QObject {
    Q_OBJECT
public:
    static AppContext *instance();
    static void create();   // 在 main() 中创建单例

    api::ApiClient *api() const { return m_api; }

    QString userId() const { return m_userId; }
    void setUserId(const QString &id);
    QString systemUserId() const { return m_systemUserId; }
    static QString detectSystemUserId(
        const QProcessEnvironment &environment = QProcessEnvironment::systemEnvironment(),
        const QString &homePath = QString());
    static QString globalUserId() { return QStringLiteral("global"); }

    QString baseUrl() const { return m_baseUrl; }
    void setBaseUrl(const QString &url);

    // 页面导航：由 MainWindow 注入回调（key 见导航树）
    void setNavigateCallback(std::function<void(const QString &)> cb) { m_navigate = std::move(cb); }
    void navigate(const QString &key);

signals:
    void userIdChanged(const QString &id);
    void baseUrlChanged(const QString &url);

private:
    explicit AppContext(QObject *parent = nullptr);
    ~AppContext() override;

    static AppContext *s_instance;
    api::ApiClient *m_api = nullptr;
    QString m_systemUserId;
    QString m_userId;
    QString m_baseUrl;
    std::function<void(const QString &)> m_navigate;
};
