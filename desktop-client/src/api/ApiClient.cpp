#include "ApiClient.h"

#include <QApplication>
#include <QEventLoop>
#include <QJsonParseError>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>

namespace api {

ApiClient::ApiClient(QObject *parent)
    : QObject(parent), m_baseUrl(QStringLiteral("http://127.0.0.1:8000")),
      m_userId(QStringLiteral("default")) {}

void ApiClient::setBaseUrl(const QString &url) {
    QString u = url.trimmed();
    while (u.endsWith('/')) u.chop(1);
    if (!u.startsWith("http://") && !u.startsWith("https://")) {
        u = "http://" + u;
    }
    m_baseUrl = u;
}

void ApiClient::setUserId(const QString &id) { m_userId = id; }

void ApiClient::applyCommonHeaders(QNetworkRequest *req, bool useUserHeader) const {
    req->setRawHeader("Accept", "application/json");
    if (useUserHeader) {
        // 用户规则接口要求 X-MemoryHub-User，内容为当前 user_id
        req->setRawHeader("X-MemoryHub-User", m_userId.toUtf8());
    }
    if (req->header(QNetworkRequest::ContentTypeHeader).isNull()) {
        req->setHeader(QNetworkRequest::ContentTypeHeader,
                       QVariant(QStringLiteral("application/json")));
    }
}

Result ApiClient::parseReply(QNetworkReply *reply) const {
    Result r;
    const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    r.statusCode = code;

    const QByteArray raw = reply->readAll();

    QJsonParseError perr;
    const QJsonDocument doc = QJsonDocument::fromJson(raw, &perr);
    if (perr.error == QJsonParseError::NoError) {
        r.doc = doc;
        // 解析 FastAPI 错误结构
        if (!doc.isObject()) return r;
        const QJsonObject o = doc.object();
        const QJsonValue detail = o.value("detail");
        if (detail.isString()) {
            r.errorMessage = detail.toString();
        } else if (detail.isObject()) {
            const QJsonObject d = detail.toObject();
            r.errorCode = d.value("code").toString();
            r.errorMessage = d.value("message").toString();
        }
    }
    r.ok = (code >= 200 && code < 300);
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
    Result r;
    const QString full = m_baseUrl + path;
    QNetworkRequest req((QUrl(full)));   // 双层括号避免 most vexing parse
    applyCommonHeaders(&req, useUserHeader);

    const bool wantCursor = m_waitCursor;
    if (wantCursor) QApplication::setOverrideCursor(Qt::WaitCursor);

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
        r = parseReply(reply);
        r.networkError = true;
    } else {
        r = parseReply(reply);
    }

    if (wantCursor) QApplication::restoreOverrideCursor();

    reply->deleteLater();
    return r;
}

Result ApiClient::get(const QString &path, bool useUserHeader) {
    return sendSync("GET", path, QByteArray(), useUserHeader);
}

Result ApiClient::post(const QString &path, const QJsonObject &body, bool useUserHeader) {
    return sendSync("POST", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                    useUserHeader);
}

Result ApiClient::postRaw(const QString &path, const QJsonValue &body, bool useUserHeader) {
    QJsonDocument doc;
    if (body.isArray()) doc = QJsonDocument(body.toArray());
    else if (body.isObject()) doc = QJsonDocument(body.toObject());
    else return Result{false};
    return sendSync("POST", path, doc.toJson(QJsonDocument::Compact), useUserHeader);
}

Result ApiClient::patch(const QString &path, const QJsonObject &body, bool useUserHeader) {
    return sendSync("PATCH", path, QJsonDocument(body).toJson(QJsonDocument::Compact),
                    useUserHeader);
}

Result ApiClient::del(const QString &path, bool useUserHeader) {
    return sendSync("DELETE", path, QByteArray(), useUserHeader);
}

Result ApiClient::delNoBody(const QString &path, bool useUserHeader) {
    return sendSync("DELETE", path, QByteArray(), useUserHeader);
}

void ApiClient::getAsync(const QString &path, std::function<void(const Result &)> callback) {
    const QString full = m_baseUrl + path;
    QNetworkRequest req((QUrl(full)));
    applyCommonHeaders(&req, false);

    QNetworkReply *reply = m_nam.get(req);
    QObject::connect(reply, &QNetworkReply::finished, this,
                     [this, reply, callback]() {
                         Result r = parseReply(reply);
                         reply->deleteLater();
                         if (callback) callback(r);
                     });
}

} // namespace api
