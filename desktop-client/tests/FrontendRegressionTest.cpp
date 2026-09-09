#include "AppContext.h"
#include "api/ApiClient.h"
#include "pages/SearchPage.h"
#include "pages/PreferencePage.h"
#include "pages/FactPage.h"
#include "pages/ForgetPages.h"
#include "pages/SettingsPages.h"
#include "pages/KnowledgePage.h"
#include "pages/MemoryTierPage.h"
#include "pages/ConflictPage.h"
#include "pages/SafetyPages.h"
#include "widgets/MemoryFilterBar.h"
#include "widgets/DetailDrawer.h"

#include <QtTest>
#include <QTcpServer>
#include <QTcpSocket>
#include <QNetworkReply>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QLabel>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QMessageBox>
#include <QTableWidget>
#include <QTimer>
#include <QTabWidget>
#include <QComboBox>
#include <QCheckBox>
#include <QDoubleSpinBox>

// Real pages and ApiClient against a local HTTP fixture; no production backend writes.
class FrontendRegressionTest : public QObject {
    Q_OBJECT
    struct Request { QByteArray path; QJsonObject body; QPointer<QTcpSocket> socket; };
    QTcpServer server;
    QList<Request> requests;
    std::function<void(const Request &)> respond;
    QStringList messages;

    bool eventFilter(QObject *object, QEvent *event) override {
        // Exercise message content without the platform-specific native show path.
        if (event->type() == QEvent::Show) {
            if (auto *box = qobject_cast<QMessageBox *>(object)) {
                messages.append(box->text());
                QTimer::singleShot(0, box, [box]() { box->done(QMessageBox::Ok); });
                return true;
            }
        }
        return QObject::eventFilter(object, event);
    }

    static void reply(const Request &r, const QByteArray &body, int status = 200) {
        if (!r.socket) return;
        r.socket->write("HTTP/1.1 " + QByteArray::number(status) + " Test\r\nContent-Type: application/json\r\nContent-Length: "
                        + QByteArray::number(body.size()) + "\r\nConnection: close\r\n\r\n" + body);
        r.socket->disconnectFromHost();
    }
private slots:
    void initTestCase() {
        AppContext::create();
        qApp->installEventFilter(this);
        connect(&server, &QTcpServer::newConnection, this, [this]() {
            auto *socket = server.nextPendingConnection();
            connect(socket, &QTcpSocket::disconnected, socket, &QObject::deleteLater);
            connect(socket, &QTcpSocket::readyRead, this, [this, socket]() {
                QByteArray data = socket->property("request").toByteArray() + socket->readAll();
                socket->setProperty("request", data);
                const int end = data.indexOf("\r\n\r\n");
                if (end < 0 || socket->property("handled").toBool()) return;
                int length = 0;
                for (const QByteArray &line : data.left(end).split('\n'))
                    if (line.toLower().startsWith("content-length:")) length = line.mid(15).trimmed().toInt();
                if (data.size() < end + 4 + length) return;
                socket->setProperty("handled", true);
                Request request{data.split(' ').at(1), QJsonDocument::fromJson(data.mid(end + 4, length)).object(), socket};
                requests.append(request);
                if (respond) respond(request);
            });
        });
    }
    void init() {
        requests.clear();
        messages.clear();
        QVERIFY(server.listen(QHostAddress::LocalHost));
        AppContext::instance()->setBaseUrl(QString("http://127.0.0.1:%1").arg(server.serverPort()));
        respond = [](const Request &r) { reply(r, "[]"); };
        AppContext::instance()->setUserId("alice");
    }
    void cleanup() {
        respond = nullptr;
        // Each page may schedule follow-up reads. Drain them before the next case
        // so they cannot hit its handler (or references to expired test locals).
        AppContext::instance()->setUserId("test-cleanup");
        for (auto *pending : AppContext::instance()->api()->findChildren<QNetworkReply *>()) pending->abort();
        QTRY_VERIFY(AppContext::instance()->api()->findChildren<QNetworkReply *>().isEmpty());
        server.close();
        for (auto *socket : server.findChildren<QTcpSocket *>()) {
            socket->abort();
            socket->deleteLater();
        }
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
    }
    void searchClearsResultsAndContextBeforeFailure() {
        SearchPage page;
        page.m_lastResponse = QJsonObject{{"preferences", QJsonArray{QJsonObject{{"text", "old result"}}}}};
        page.renderResults(page.m_lastResponse);
        page.m_contextText->setText("old context");
        page.m_copyContextBtn->setEnabled(true);
        respond = [](const Request &r) { reply(r, "{\"detail\":\"offline\"}", 503); };
        page.applySearchQuery("new query");
        QVERIFY(page.m_contextText->text().isEmpty());
        QVERIFY(!page.m_copyContextBtn->isEnabled());
        QCOMPARE(page.m_totalLabel->text(), QStringLiteral("—"));
        QTRY_VERIFY(page.m_searchButton->isEnabled());
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        for (auto *label : page.findChildren<QLabel *>()) QVERIFY(label->text() != "old result");
        QCOMPARE(page.m_queryEdit->text(), QStringLiteral("new query"));
    }
    void contextFromPreviousQueryCannotReturn() {
        SearchPage page;
        respond = nullptr;
        page.m_queryEdit->setText("old query");
        page.generateContext();
        QTRY_COMPARE(requests.size(), 1);
        const Request old = requests.first();
        page.applySearchQuery("new query");
        reply(old, "{\"context_text\":\"stale context\"}");
        QTest::qWait(50);
        QVERIFY(page.m_contextText->text().isEmpty());
        QVERIFY(!page.m_copyContextBtn->isEnabled());
    }
    void searchRendersFactContractFallbacksAndStringScope() {
        SearchPage page;
        page.m_sceneCombo->setCurrentIndex(0);
        page.renderResults(QJsonObject{
            {"facts", QJsonArray{QJsonObject{{"fact_id", "fact-1"}, {"object_value", "Alice"},
                                               {"scope", "global"}, {"confidence", 0.9}}}},
            {"preferences", QJsonArray()}, {"knowledge", QJsonArray()}});
        bool found = false;
        for (auto *label : page.findChildren<QLabel *>())
            if (label->text() == "Alice") found = true;
        QVERIFY(found);
    }
    void searchFiltersCachedResultsWithoutRequests() {
        SearchPage page;
        QVERIFY(page.m_sceneCombo->isEnabled());
        QVERIFY(page.m_taskEdit->isEnabled());
        page.m_lastResponse = QJsonObject{{"facts", QJsonArray{
            QJsonObject{{"object_value", "Alice"}, {"confidence", 0.9}},
            QJsonObject{{"object_value", "Bob"}, {"confidence", 0.2}}}}};
        page.renderResults(page.m_lastResponse);
        page.m_minConf->setValue(0.5);
        QCOMPARE(page.m_totalLabel->text(), QStringLiteral("结果总数：1"));
        page.m_cbFact->setChecked(false);
        QCOMPARE(page.m_totalLabel->text(), QStringLiteral("结果总数：0"));
        page.m_cbFact->setChecked(true);
        QCOMPARE(page.m_totalLabel->text(), QStringLiteral("结果总数：1"));
        QVERIFY(requests.isEmpty());
    }
    void userRulesFilterLocallyAndPreserveLoadFailure() {
        SafetyUserRulesPage page;
        auto *table = page.findChild<QTableWidget *>();
        auto *filter = page.findChild<MemoryFilterBar *>();
        respond = [](const Request &r) {
            reply(r, "[{\"label\":\"alpha\"},{\"label\":\"beta\"}]");
        };
        page.refresh();
        QTRY_COMPARE(table->rowCount(), 2);
        filter->searchBox()->setText("alpha");
        QTRY_COMPARE(table->rowCount(), 1);
        QCOMPARE(table->item(0, 0)->text(), QStringLiteral("alpha"));
        QCOMPARE(requests.size(), 1);
        respond = [](const Request &r) { reply(r, "{}", 503); };
        page.refresh();
        QTRY_VERIFY(table->cellWidget(0, 0) != nullptr);
        QPointer<QWidget> failure(table->cellWidget(0, 0));
        filter->searchBox()->setText("beta");
        QTest::qWait(350);
        QCOMPARE(requests.size(), 2);
        QVERIFY(failure);
        QCOMPARE(table->cellWidget(0, 0), failure.data());
    }
    void batchStatusSurvivesDestroyedButton() {
        ForgetPendingPage page;
        page.m_table->setRowCount(1);
        auto *check = new QCheckBox;
        check->setChecked(true);
        check->setProperty("memoryId", "fact-1");
        page.m_table->setCellWidget(0, 0, check);
        auto *button = new QPushButton;
        respond = nullptr;
        page.batchSetStatus("active", button);
        QTRY_COMPARE(requests.size(), 1);
        const Request update = requests.first();
        delete button;
        respond = [](const Request &r) { reply(r, "[]"); };
        reply(update, "{\"applied\":1,\"total\":1}");
        QTRY_VERIFY(!messages.isEmpty());
        QTRY_COMPARE(requests.size(), 4);
    }
    void preferenceEditDoesNotOverwritePayload() {
        PreferencePage page;
        QJsonObject sent;
        respond = [&sent](const Request &r) {
            if (r.path.startsWith("/api/memory/preference/")) { sent = r.body; reply(r, "{}"); }
            else reply(r, "[]");
        };
        QTimer click;
        connect(&click, &QTimer::timeout, this, []() {
            if (qobject_cast<QMessageBox *>(QApplication::activeModalWidget())) return;
            if (auto *dialog = qobject_cast<QDialog *>(QApplication::activeModalWidget())) {
                if (auto *buttons = dialog->findChild<QDialogButtonBox *>()) buttons->button(QDialogButtonBox::Ok)->click();
            }
        });
        click.start(10);
        page.openEditDialog(QJsonObject{{"memory_id", "pref-1"}, {"text", "keep text"},
                            {"payload", QJsonObject{{"format", "markdown"}}}}, false);
        // 编辑请求已异步化：等待请求到达服务器，而不是立即检查
        QTRY_VERIFY(!sent.isEmpty());
        QVERIFY(!sent.contains("payload"));
    }
    void factProposeReportsCreatedAndFailed_data() {
        QTest::addColumn<QByteArray>("response");
        QTest::addColumn<bool>("reload");
        QTest::addColumn<QString>("summary");
        QTest::newRow("success") << QByteArray("{\"created\":[{\"fact_id\":\"know_fact_1\"}],\"pending\":[],\"failed\":[]}")
            << true << QStringLiteral("写入成功 1 条，待裁决 0 条，失败 0 条。");
        QTest::newRow("partial") << QByteArray("{\"created\":[{}],\"pending\":[],\"failed\":[{\"reason\":\"write rejected\"}]}")
            << true << QStringLiteral("写入成功 1 条，待裁决 0 条，失败 1 条。\nwrite rejected");
        QTest::newRow("all-failed") << QByteArray("{\"created\":[],\"pending\":[],\"failed\":[{\"reason\":\"write rejected\"}]}")
            << false << QStringLiteral("写入成功 0 条，待裁决 0 条，失败 1 条。\nwrite rejected");
    }
    void factProposeReportsCreatedAndFailed() {
        QFETCH(QByteArray, response);
        QFETCH(bool, reload);
        QFETCH(QString, summary);
        FactPage page;
        bool reloaded = false;
        respond = [response, &reloaded](const Request &r) {
            if (r.path == "/api/memory/facts/propose") {
                QCOMPARE(r.body.value("scope_hint").toString(), QStringLiteral("global"));
                QVERIFY(!r.body.contains("project_id"));
                QCOMPARE(r.body.value("triples").toArray().first().toObject().value("evidence").toString(),
                         QStringLiteral("sample evidence"));
                reply(r, response);
            }
            else { reloaded = true; reply(r, "[]"); }
        };
        QTimer::singleShot(0, this, []() {
            auto *dlg = qobject_cast<QDialog *>(QApplication::activeModalWidget());
            if (!dlg) return;
            for (auto *input : dlg->findChildren<QLineEdit *>()) input->setText("sample");
            for (auto *input : dlg->findChildren<QPlainTextEdit *>())
                input->setPlainText("sample evidence");
            dlg->accept();
        });
        page.openProposeDialog();
        QTRY_VERIFY(!messages.isEmpty());
        QCOMPARE(messages.last(), summary);
        if (reload) QTRY_VERIFY(reloaded);
        else QVERIFY(!reloaded);
    }
    void pendingFactUsesKnowledgeAndSurvivesDestroyedButton() {
        ForgetPendingPage page;
        respond = nullptr;
        page.m_table->setRowCount(1);
        auto *button = new QPushButton("保持");
        page.m_table->setCellWidget(0, 5, button);
        page.setSingleStatus("fact", "know_fact_1", "active", button);
        QTRY_COMPARE(requests.size(), 1);
        const Request update = requests.first();
        QCOMPARE(update.path, QByteArray("/api/memory/knowledge/know_fact_1"));
        QCOMPARE(update.body.value("status").toString(), QStringLiteral("active"));
        QPointer<QPushButton> guard(button);
        page.m_table->setRowCount(0);
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        QVERIFY(guard.isNull());
        respond = [](const Request &r) { reply(r, "[]"); };
        reply(update, "{}");
        QTRY_COMPARE(requests.size(), 4);
    }
    void userSwitchClearsCachedMemoryAndDrawerOnFailure() {
        PreferencePage page;
        page.m_all = QJsonArray{QJsonObject{{"text", "alice private"}}};
        page.m_drawer->open("alice", new QLabel("private detail"));
        respond = [](const Request &r) { reply(r, "{\"detail\":\"offline\"}", 503); };
        AppContext::instance()->setUserId("bob");
        QVERIFY(page.m_all.isEmpty());
        QVERIFY(!page.m_drawer->isOpen());
        QCOMPARE(page.m_table->rowCount(), 0);
        QTRY_VERIFY(!requests.isEmpty());
        QTest::qWait(30);
        QVERIFY(page.m_all.isEmpty());
    }
    void demoDeletionIsDisabled() {
        SettingsDemoPage page;
        int count = 0;
        for (auto *button : page.findChildren<QPushButton *>())
            if (button->text().startsWith("清空")) { ++count; QVERIFY(!button->isEnabled()); }
        QCOMPARE(count, 2);
    }
    void preciseForgetOmitsEmptyPreferenceStatus() {
        ForgetPrecisePage page;
        page.refresh();
        QTRY_COMPARE(requests.size(), 3);
        // 偏好/知识/事实三组列表都不允许携带空 status 参数（后端可能按它过滤导致恒空）
        const QList<QByteArray> prefixes = {"/api/memory/preferences?", "/api/memory/knowledge?",
                                            "/api/memory/facts?"};
        for (const QByteArray &prefix : prefixes) {
            bool found = false;
            for (const Request &r : requests) if (r.path.startsWith(prefix)) {
                found = true;
                QVERIFY2(!r.path.contains("status="), r.path.constData());
                QVERIFY(r.path.contains("user_id=alice"));
            }
            QVERIFY2(found, prefix.constData());
        }
    }
    void conflictResolvedFilterOmitsStatusParam() {
        ConflictPage page;
        QComboBox *statusCombo = nullptr;
        for (auto *combo : page.findChildren<QComboBox *>())
            if (combo->itemData(0).toString() == "pending") statusCombo = combo;
        QVERIFY(statusCombo);
        statusCombo->setCurrentIndex(1); // "已解决"
        QTRY_COMPARE(requests.size(), 2);
        bool found = false;
        for (const Request &r : requests) if (r.path.startsWith("/api/memory/conflicts?")) {
            QVERIFY2(!r.path.contains("status=resolved"), r.path.constData());
            // 已解决视图必须省略 page/size 走全量返回；size 上限 200，
            // 传 500 会被后端参数校验拒绝（422），导致"已解决"筛选必然报错
            QVERIFY2(!r.path.contains("page=") && !r.path.contains("size="),
                     r.path.constData());
            found = true;
        }
        QVERIFY(found);
    }
    void consolidationSendsUserInQuery() {
        MemoryTierPage page;
        respond = [](const Request &r) {
            reply(r, r.path.startsWith("/api/memory/lifecycle/consolidate") ? "{}" : "[]");
        };
        QTimer::singleShot(0, this, []() {
            if (auto *dlg = qobject_cast<QDialog *>(QApplication::activeModalWidget())) dlg->accept();
        });
        page.runConsolidate();
        QTRY_VERIFY(!requests.isEmpty());
        QCOMPARE(requests.first().path, QByteArray("/api/memory/lifecycle/consolidate?user_id=alice"));
        QVERIFY(requests.first().body.isEmpty());
        QTRY_VERIFY(!messages.isEmpty());
    }
    void archivedAndRecycleFactUseKnowledgeRoute() {
        respond = [](const Request &r) {
            reply(r, r.path.startsWith("/api/memory/knowledge/know_fact_1") ? "{}" : "[]");
        };
        // 单条操作成功后会异步触发列表刷新 GET，与后续 PUT 交错到达；
        // 断言只认目标 PUT 是否出现，不依赖请求顺序
        auto knowledgePutSeen = [this]() {
            for (const Request &r : requests)
                if (r.path == QByteArray("/api/memory/knowledge/know_fact_1")
                    && r.body.value("status").toString() == QStringLiteral("active"))
                    return true;
            return false;
        };
        ForgetArchivedPage archived;
        archived.unarchive("fact", "know_fact_1");
        QTRY_VERIFY_WITH_TIMEOUT(knowledgePutSeen(), 2000);
        requests.clear();
        ForgetRecyclePage recycle;
        recycle.restore("fact", "know_fact_1");
        QTRY_VERIFY_WITH_TIMEOUT(knowledgePutSeen(), 2000);
    }
    void historyDetailUsesOnlyRecordSnapshot() {
        ForgetHistoryPage page;
        QStringList ids;
        QTimer::singleShot(0, this, [&ids]() {
            if (auto *dlg = qobject_cast<QDialog *>(QApplication::activeModalWidget())) {
                if (auto *table = dlg->findChild<QTableWidget *>())
                    for (int i = 0; i < table->rowCount(); ++i) ids.append(table->item(i, 0)->text());
                dlg->accept();
            }
        });
        page.openDetail(QJsonObject{{"record_id", "record-1"}, {"instruction", "forget sample"},
            {"deleted_count", 2}, {"target_memory_ids", QJsonArray{"pref-1", "know_fact_1"}}});
        QCOMPARE(ids, QStringList({"pref-1", "know_fact_1"}));
        QVERIFY(requests.isEmpty());
    }
    void knowledgeDetailHasNoUnsupportedVersionsTab() {
        KnowledgePage page;
        respond = [](const Request &r) { reply(r, "{\"memory_id\":\"know-1\",\"name\":\"sample\"}"); };
        page.openDetail("know-1");
        // 详情已异步化：轮询等待抽屉内容构建完成
        QTRY_VERIFY(!page.findChildren<QTabWidget *>().isEmpty());
        for (auto *tabs : page.findChildren<QTabWidget *>())
            for (int i = 0; i < tabs->count(); ++i) QVERIFY(tabs->tabText(i) != QStringLiteral("版本历史"));
        QVERIFY(!requests.isEmpty());
        for (const Request &r : requests) QVERIFY(!r.path.contains("/versions"));
    }
    void switchingUserDropsOldResponseEvenWhenSwitchingBack() {
        auto *api = AppContext::instance()->api();
        respond = nullptr;
        bool called = false;
        auto *pending = api->getAsync("/delayed", [&called](const api::Result &) { called = true; }, this);
        QSignalSpy finished(pending, &QNetworkReply::finished);
        QTRY_COMPARE(requests.size(), 1);
        AppContext::instance()->setUserId("bob");
        AppContext::instance()->setUserId("alice");
        reply(requests.first(), "{}");
        QTRY_COMPARE(finished.count(), 1);
        QVERIFY(!called);
    }
};

QTEST_MAIN(FrontendRegressionTest)
#include "FrontendRegressionTest.moc"
