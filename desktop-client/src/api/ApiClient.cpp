#include "ApiClient.h"

#include <QApplication>
#include <QEventLoop>
#include <QJsonParseError>
#include <QNetworkReply>
#include <QNetworkProxy>
#include <QNetworkRequest>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>
#include <QPointer>

namespace api {

ApiClient::ApiClient(QObject *parent)
    : QObject(parent), m_baseUrl(QStringLiteral("http://127.0.0.1:8099")),
      m_userId(QStringLiteral("default")) {
    // The desktop client talks to a local MemoryHub service. System/VPN proxy
    // settings must never intercept loopback traffic.
    m_nam.setProxy(QNetworkProxy::NoProxy);
}

void ApiClient::setBaseUrl(const QString &url) {
    QString u = url.trimmed();
    while (u.endsWith('/')) u.chop(1);
    if (!u.startsWith("http://") && !u.startsWith("https://")) {
        u = "http://" + u;
    }
    m_baseUrl = u;
}

void ApiClient::setUserId(const QString &id) {
    if (id == m_userId) return;
    m_userId = id;
    ++m_userGeneration;
}

void ApiClient::setVNextManagementCredentials(const QString &tenantId, const QString &adminToken) {
    m_vnextTenantId = tenantId.trimmed();
    m_vnextAdminToken = adminToken.trimmed();
}

void ApiClient::applyCommonHeaders(QNetworkRequest *req, bool useUserHeader) const {
    req->setRawHeader("Accept", "application/json");
    if (useUserHeader) {
        // 用户规则接口要求 X-MemoryHub-User，内容为当前 user_id
        req->setRawHeader("X-MemoryHub-User", m_userId.toUtf8());
    }
    if (!m_vnextTenantId.isEmpty())
        req->setRawHeader("X-MemoryHub-Tenant", m_vnextTenantId.toUtf8());
    if (!m_vnextAdminToken.isEmpty())
        req->setRawHeader("X-MemoryHub-Admin", m_vnextAdminToken.toUtf8());
    if (req->header(QNetworkRequest::ContentTypeHeader).isNull()) {
        req->setHeader(QNetworkRequest::ContentTypeHeader,
                       QVariant(QStringLiteral("application/json")));
    }
}

Result ApiClient::parseReply(QNetworkReply *reply) const {
    Result r;
    const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    r.statusCode = code;
    r.ok = (code >= 200 && code < 300);

    const QByteArray raw = reply->readAll();

    QJsonParseError perr;
    const QJsonDocument doc = QJsonDocument::fromJson(raw, &perr);
    if (perr.error == QJsonParseError::NoError) {
        r.doc = doc;
        if (doc.isObject()) {
            // 解析 FastAPI 错误结构；成功响应仍完整保留 object。
            const QJsonObject o = doc.object();
            const QJsonValue detail = o.value("detail");
            if (detail.isString()) {
                r.errorMessage = detail.toString();
            } else if (detail.isObject()) {
                const QJsonObject d = detail.toObject();
                r.errorCode = d.value("code").toString();
                r.errorMessage = d.value("message").toString();
                if (r.errorMessage.isEmpty()) r.errorMessage = d.value("detail").toString();
            }
        }
    } else if (!raw.trimmed().isEmpty()) {
        r.errorMessage = QString::fromUtf8(raw).trimmed();
    }
    if (!r.ok && r.errorMessage.isEmpty() && code > 0)
        r.errorMessage = QStringLiteral("HTTP %1").arg(code);
    return r;
}

QString ApiClient::urlWithQuery(const QString &path,
                                const QList<QPair<QString, QString>> &params) {
    QUrl url(path);
    QUrlQuery q;
    for (const auto &p : params) {
        if (p.second.isNull()) continue;
        q.addQueryItem(p.first, p.second);
    }
    url.setQuery(q);
    return url.toString(QUrl::FullyEncoded);
}

Result ApiClient::sendSync(const QString &method, const QString &path,
                           const QByteArray &body, bool useUserHeader) {
    const quint64 userGeneration = m_userGeneration;
    Result r;
    const QString full = m_baseUrl + path;
    QNetworkRequest req((QUrl(full)));   // 双层括号避免 most vexing parse
    applyCommonHeaders(&req, useUserHeader);

    QApplication::setOverrideCursor(Qt::WaitCursor);

    QNetworkReply *reply = nullptr;
    if (method == QLatin1String("GET")) {
        reply = m_nam.get(req);
    } else if (method == QLatin1String("POST")) {
        reply = m_nam.post(req, body);
    } else if (method == QLatin1String("PATCH")) {
        reply = m_nam.sendCustomRequest(req, "PATCH", body);
    } else if (method == QLatin1String("DELETE")) {
        reply = m_nam.deleteResource(req);
    } else {
        reply = m_nam.sendCustomRequest(req, method.toUtf8(), body);
    }

    // 事件循环等待结果（含超时）
    QEventLoop loop;
    const int timeoutMs = 20000;
    QTimer timer;
    timer.setSingleShot(true);
    QObject::connect(&timer, &QTimer::timeout, &loop, &QEventLoop::quit);
    QObject::connect(reply, &QNetworkReply::finished, &loop, &QEventLoop::quit);
    timer.start(timeoutMs);
    loop.exec();

    if (!timer.isActive() && !reply->isFinished()) {
        // 超时：中止请求
        reply->abort();
        r.networkError = true;
        r.networkErrorText = tr("请求超时（%1 ms）").arg(timeoutMs);
    } else if (reply->error() != QNetworkReply::NoError) {
        r.networkError = true;
        r.networkErrorText = reply->errorString();
        // 部分网络错误仍带响应体（如 503），尽量解析
        Result parsed = parseReply(reply);
        parsed.networkError = true;
        parsed.networkErrorText = r.networkErrorText;
        if (parsed.errorMessage.isEmpty() && !parsed.networkErrorText.isEmpty())
            parsed.errorMessage = parsed.networkErrorText;
        r = parsed;
    } else {
        r = parseReply(reply);
    }

    QApplication::restoreOverrideCursor();

    reply->deleteLater();
    if (userGeneration != m_userGeneration) {
        r = Result{};
        r.errorCode = "client.user_changed";
        r.errorMessage = tr("用户已切换，请重新操作。");
    }
    return r;
}

Result ApiClient::get(const QString &path, bool useUserHeader) {
    return sendSync("GET", path, QByteArray(), useUserHeader);
}

Result ApiClient::post(const QString &path, const QJsonObject &body, bool useUserHeader) {
    return sendSync("POST", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                    useUserHeader);
}

Result ApiClient::patch(const QString &path, const QJsonObject &body, bool useUserHeader) {
    return sendSync("PATCH", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                    useUserHeader);
}

Result ApiClient::put(const QString &path, const QJsonObject &body, bool useUserHeader) {
    return sendSync("PUT", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                    useUserHeader);
}

Result ApiClient::del(const QString &path, bool useUserHeader) {
    return sendSync("DELETE", path, QByteArray(), useUserHeader);
}

QNetworkReply *ApiClient::sendAsync(const QString &method, const QString &path,
                                    const QByteArray &body, bool useUserHeader,
                                    Callback callback, QObject *context, int timeoutMs) {
    const quint64 userGeneration = m_userGeneration;
    const QString full = m_baseUrl + path;
    QNetworkRequest req((QUrl(full)));
    applyCommonHeaders(&req, useUserHeader);

    QNetworkReply *reply = nullptr;
    if (method == QLatin1String("GET")) reply = m_nam.get(req);
    else if (method == QLatin1String("POST")) reply = m_nam.post(req, body);
    else if (method == QLatin1String("PATCH")) reply = m_nam.sendCustomRequest(req, "PATCH", body);
    else if (method == QLatin1String("DELETE")) reply = m_nam.deleteResource(req);
    else reply = m_nam.sendCustomRequest(req, method.toUtf8(), body);

    QTimer::singleShot(timeoutMs, reply, [reply]() {
        if (!reply->isFinished()) reply->abort();
    });
    QObject *receiver = context ? context : this;
    QObject::connect(reply, &QNetworkReply::finished, reply, &QObject::deleteLater);
    QObject::connect(reply, &QNetworkReply::finished, receiver,
                     [this, reply, callback, userGeneration]() {
                         if (userGeneration != m_userGeneration) return;
                         Result r = parseReply(reply);
                         if (reply->error() != QNetworkReply::NoError) {
                             r.networkError = true;
                             r.networkErrorText = reply->errorString();
                             if (r.errorMessage.isEmpty())
                                 r.errorMessage = r.networkErrorText;
                         }
                         if (callback) callback(r);
                     });
    return reply;
}

QNetworkReply *ApiClient::getAsync(const QString &path, Callback callback,
                                   QObject *context, int timeoutMs) {
    return sendAsync("GET", path, QByteArray(), false, std::move(callback), context, timeoutMs);
}

QNetworkReply *ApiClient::getAsync(const QString &path, Callback callback,
                                   bool useUserHeader, QObject *context, int timeoutMs) {
    return sendAsync("GET", path, QByteArray(), useUserHeader, std::move(callback), context, timeoutMs);
}

QNetworkReply *ApiClient::postAsync(const QString &path, const QJsonObject &body,
                                    Callback callback, bool useUserHeader,
                                    QObject *context, int timeoutMs) {
    return sendAsync("POST", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                     useUserHeader, std::move(callback), context, timeoutMs);
}

QNetworkReply *ApiClient::patchAsync(const QString &path, const QJsonObject &body,
                                     Callback callback, bool useUserHeader,
                                     QObject *context, int timeoutMs) {
    return sendAsync("PATCH", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                     useUserHeader, std::move(callback), context, timeoutMs);
}

QNetworkReply *ApiClient::putAsync(const QString &path, const QJsonObject &body,
                                   Callback callback, bool useUserHeader,
                                   QObject *context, int timeoutMs) {
    return sendAsync("PUT", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                     useUserHeader, std::move(callback), context, timeoutMs);
}

QNetworkReply *ApiClient::deleteAsync(const QString &path, Callback callback,
                                      bool useUserHeader, QObject *context, int timeoutMs) {
    return sendAsync("DELETE", path, QByteArray(), useUserHeader,
                     std::move(callback), context, timeoutMs);
}

} // namespace api
