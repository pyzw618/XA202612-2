#pragma once
// HTTP 客户端封装：同步调用（阻塞 + 等待光标）与异步调用（后台轮询）并存。
// 后端为本地 FastAPI 服务（http://127.0.0.1:8099），响应通常在百毫秒内。

#include <QByteArray>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QNetworkAccessManager>
#include <QString>
#include <functional>
#include <QList>

class QNetworkReply;

namespace api {

// 一次请求的结果
struct Result {
    bool ok = false;             // 请求成功且 HTTP 2xx/3xx
    int statusCode = 0;          // HTTP 状态码，网络错误时为 0
    bool networkError = false;   // 网络层失败（连接拒绝/超时）
    QString networkErrorText;    // 网络错误文本
    QJsonDocument doc;           // 解析后的响应体（可能为空）
    QString errorCode;           // 稳定错误码（detail.code，如 memory.safety.review_required）
    QString errorMessage;        // 友好错误消息（detail 为字符串时）

    // 便捷：响应体为对象时返回
    QJsonObject jsonObject() const {
        if (doc.isObject()) return doc.object();
        return QJsonObject();
    }
    // 便捷：响应体为数组时返回
    QJsonArray jsonArray() const {
        if (doc.isArray()) return doc.array();
        return QJsonArray();
    }
    bool hasJsonObject() const { return doc.isObject(); }
    bool hasJsonArray() const { return doc.isArray(); }
};

class ApiClient : public QObject {
    Q_OBJECT
public:
    explicit ApiClient(QObject *parent = nullptr);

    // ---- 配置 ----
    QString baseUrl() const { return m_baseUrl; }
    void setBaseUrl(const QString &url);
    QString userId() const { return m_userId; }
    void setUserId(const QString &id);

    // 是否在请求期间显示等待光标（同步请求默认开启）
    void setWaitCursorEnabled(bool on) { m_waitCursor = on; }

    // ---- 同步调用（遗留兼容接口；新页面必须使用异步接口） ----
    // path 以 "/api/..." 或 "/" 开头；useUserHeader 用于需要 X-MemoryHub-User 的接口（用户规则）
    Result get(const QString &path, bool useUserHeader = false);
    Result post(const QString &path, const QJsonObject &body, bool useUserHeader = false);
    Result postRaw(const QString &path, const QJsonValue &body, bool useUserHeader = false);
    Result patch(const QString &path, const QJsonObject &body, bool useUserHeader = false);
    Result put(const QString &path, const QJsonObject &body, bool useUserHeader = false);
    Result del(const QString &path, bool useUserHeader = false);

    // 无响应体的请求（如 204），返回状态码
    Result delNoBody(const QString &path, bool useUserHeader = false);

    // ---- 异步调用（非阻塞；context 销毁后自动断开回调） ----
    using Callback = std::function<void(const Result &)>;
    QNetworkReply *getAsync(const QString &path, Callback callback,
                            QObject *context = nullptr, int timeoutMs = 8000);
    QNetworkReply *getAsync(const QString &path, Callback callback,
                            bool useUserHeader, QObject *context = nullptr,
                            int timeoutMs = 8000);
    QNetworkReply *postAsync(const QString &path, const QJsonObject &body, Callback callback,
                             bool useUserHeader = false, QObject *context = nullptr,
                             int timeoutMs = 10000);
    QNetworkReply *patchAsync(const QString &path, const QJsonObject &body, Callback callback,
                              bool useUserHeader = false, QObject *context = nullptr,
                              int timeoutMs = 10000);
    QNetworkReply *putAsync(const QString &path, const QJsonObject &body, Callback callback,
                            bool useUserHeader = false, QObject *context = nullptr,
                            int timeoutMs = 10000);
    QNetworkReply *deleteAsync(const QString &path, Callback callback,
                               bool useUserHeader = false, QObject *context = nullptr,
                               int timeoutMs = 10000);

    // 查询字符串构造辅助
    static QString urlWithQuery(const QString &path, const QList<QPair<QString, QString>> &params);

private:
    Result sendSync(const QString &method, const QString &path,
                    const QByteArray &body, bool useUserHeader);
    QNetworkReply *sendAsync(const QString &method, const QString &path,
                             const QByteArray &body, bool useUserHeader,
                             Callback callback, QObject *context, int timeoutMs);
    void applyCommonHeaders(QNetworkRequest *req, bool useUserHeader) const;
    Result parseReply(QNetworkReply *reply) const;

    QString m_baseUrl;
    QString m_userId;
    QNetworkAccessManager m_nam;
    bool m_waitCursor = true;
};

} // namespace api

// 全局便捷入口（单例持有在 AppContext）
namespace Api {
    api::ApiClient *client();
}
