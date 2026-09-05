#include "api/ApiClient.h"
#include "AppContext.h"

#include <QAbstractSocket>
#include <QTcpServer>
#include <QTcpSocket>
#include <QtTest>
#include <future>
#include <thread>

class ApiClientTest : public QObject {
    Q_OBJECT

private:
    static QByteArray httpResponse(int status, const QByteArray &body,
                                   const QByteArray &contentType = "application/json") {
        const QByteArray reason = status == 200 ? "OK" : status == 204 ? "No Content"
                                      : status == 400 ? "Bad Request" : "Conflict";
        return "HTTP/1.1 " + QByteArray::number(status) + " " + reason + "\r\n"
             + "Content-Type: " + contentType + "\r\n"
             + "Content-Length: " + QByteArray::number(body.size()) + "\r\n"
             + "Connection: close\r\n\r\n" + body;
    }

    api::Result getResponse(int status, const QByteArray &body) {
        const QByteArray response = httpResponse(status, body);
        std::promise<quint16> portPromise;
        std::future<quint16> portFuture = portPromise.get_future();
        std::thread serverThread([response, promise = std::move(portPromise)]() mutable {
            QTcpServer server;
            if (!server.listen(QHostAddress::LocalHost, 0)) {
                promise.set_value(0);
                return;
            }
            promise.set_value(server.serverPort());
            if (!server.waitForNewConnection(5000)) return;
            QTcpSocket *socket = server.nextPendingConnection();
            if (socket && (socket->bytesAvailable() > 0 || socket->waitForReadyRead(5000))) {
                socket->write(response);
                socket->waitForBytesWritten(5000);
                socket->disconnectFromHost();
            }
            delete socket;
        });

        const quint16 port = portFuture.get();
        if (port == 0) {
            serverThread.join();
            return api::Result();
        }

        api::ApiClient client;
        client.setBaseUrl(QString("http://127.0.0.1:%1").arg(port));
        const api::Result result = client.get("/");
        serverThread.join();
        return result;
    }

private slots:
    void objectResponseIsPreserved() {
        const api::Result result = getResponse(200, "{\"items\":[]}");
        QVERIFY(result.ok);
        QCOMPARE(result.statusCode, 200);
        QVERIFY(result.hasJsonObject());
        QVERIFY(result.jsonObject().contains("items"));
    }

    void arrayResponseIsPreserved() {
        const api::Result result = getResponse(200, "[{\"id\":\"m-1\"}]");
        QVERIFY(result.ok);
        QVERIFY(result.hasJsonArray());
        QCOMPARE(result.jsonArray().size(), 1);
    }

    void noContentIsSuccessful() {
        const api::Result result = getResponse(204, QByteArray());
        QVERIFY(result.ok);
        QCOMPARE(result.statusCode, 204);
        QVERIFY(result.doc.isNull());
    }

    void stringDetailIsReadable() {
        const api::Result result = getResponse(400, "{\"detail\":\"invalid request\"}");
        QVERIFY(!result.ok);
        QCOMPARE(result.statusCode, 400);
        QCOMPARE(result.errorMessage, QStringLiteral("invalid request"));
    }

    void objectDetailPreservesCode() {
        const api::Result result = getResponse(
            409, "{\"detail\":{\"code\":\"memory.conflict\",\"message\":\"review required\"}}");
        QVERIFY(!result.ok);
        QCOMPARE(result.statusCode, 409);
        QCOMPARE(result.errorCode, QStringLiteral("memory.conflict"));
        QCOMPARE(result.errorMessage, QStringLiteral("review required"));
    }

    void networkFailureIsReported() {
        QTcpServer server;
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        const quint16 port = server.serverPort();
        server.close();

        api::ApiClient client;
        client.setBaseUrl(QString("http://127.0.0.1:%1").arg(port));
        const api::Result result = client.get("/");
        QVERIFY(!result.ok);
        QVERIFY(result.networkError);
        QVERIFY(!result.networkErrorText.isEmpty());
    }

    void detectsInteractiveLinuxUser() {
        QProcessEnvironment env;
        env.insert(QStringLiteral("USER"), QStringLiteral("ethan"));
        QCOMPARE(AppContext::detectSystemUserId(env, QStringLiteral("/home/ignored")),
                 QStringLiteral("ethan"));
    }

    void detectsSudoInvokerInsteadOfRoot() {
        QProcessEnvironment env;
        env.insert(QStringLiteral("USER"), QStringLiteral("root"));
        env.insert(QStringLiteral("SUDO_USER"), QStringLiteral("ethan"));
        QCOMPARE(AppContext::detectSystemUserId(env, QStringLiteral("/root")),
                 QStringLiteral("ethan"));
    }

    void fallsBackToHomeDirectoryName() {
        const QProcessEnvironment env;
        QCOMPARE(AppContext::detectSystemUserId(env, QStringLiteral("/home/alice")),
                 QStringLiteral("alice"));
    }

    void exposesGlobalMemoryUser() {
        QCOMPARE(AppContext::globalUserId(), QStringLiteral("global"));
    }
};

QTEST_MAIN(ApiClientTest)
#include "ApiClientTest.moc"
