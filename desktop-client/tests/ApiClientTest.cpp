#include "api/ApiClient.h"

#include <QAbstractSocket>
#include <QTcpServer>
#include <QTcpSocket>
#include <QtTest>

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
        QTcpServer server;
        if (!server.listen(QHostAddress::LocalHost, 0))
            return api::Result();
        const QByteArray response = httpResponse(status, body);
        QObject::connect(&server, &QTcpServer::newConnection, &server, [&server, response]() {
            QTcpSocket *socket = server.nextPendingConnection();
            QObject::connect(socket, &QTcpSocket::readyRead, socket, [socket, response]() {
                if (socket->property("responded").toBool()) return;
                socket->setProperty("responded", true);
                socket->write(response);
                socket->flush();
                QObject::connect(socket, &QTcpSocket::bytesWritten, socket, [socket](qint64) {
                    if (socket->bytesToWrite() == 0)
                        socket->disconnectFromHost();
                });
                QObject::connect(socket, &QTcpSocket::disconnected, socket, &QTcpSocket::deleteLater);
            });
        });

        api::ApiClient client;
        client.setBaseUrl(QString("http://127.0.0.1:%1").arg(server.serverPort()));
        return client.get("/");
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
};

QTEST_MAIN(ApiClientTest)
#include "ApiClientTest.moc"
