#include "AppContext.h"

#include "api/ApiClient.h"

#include <QDir>

AppContext *AppContext::s_instance = nullptr;

AppContext::AppContext(QObject *parent)
    : QObject(parent),
      m_api(new api::ApiClient(this)),
      m_systemUserId(detectSystemUserId()),
      m_userId(m_systemUserId),
      m_baseUrl(QStringLiteral("http://127.0.0.1:8099")) {
    m_api->setBaseUrl(m_baseUrl);
    m_api->setUserId(m_userId);
}

AppContext::~AppContext() = default;

void AppContext::create() {
    if (!s_instance) s_instance = new AppContext();
}

AppContext *AppContext::instance() { return s_instance; }

QString AppContext::detectSystemUserId(const QProcessEnvironment &environment,
                                       const QString &homePath) {
    const QString sudoUser = environment.value(QStringLiteral("SUDO_USER")).trimmed();
    const QString unixUser = environment.value(QStringLiteral("USER")).trimmed();
    if (unixUser == QLatin1String("root") && !sudoUser.isEmpty() &&
        sudoUser != QLatin1String("root")) {
        return sudoUser;
    }
    for (const QString &name : {QStringLiteral("USER"), QStringLiteral("LOGNAME"),
                                QStringLiteral("USERNAME")}) {
        const QString value = environment.value(name).trimmed();
        if (!value.isEmpty()) return value;
    }
    const QString resolvedHome = homePath.isEmpty() ? QDir::homePath() : homePath;
    const QString homeName = QDir(resolvedHome).dirName().trimmed();
    return homeName.isEmpty() ? QStringLiteral("default") : homeName;
}

void AppContext::setUserId(const QString &id) {
    const QString v = id.trimmed();
    if (v.isEmpty() || v == m_userId) return;
    m_userId = v;
    m_api->setUserId(v);
    emit userIdChanged(v);
}

void AppContext::setBaseUrl(const QString &url) {
    const QString v = url.trimmed();
    if (v.isEmpty()) return;
    m_baseUrl = v;
    m_api->setBaseUrl(v);
    emit baseUrlChanged(v);
}

void AppContext::navigate(const QString &key) {
    if (m_navigate) m_navigate(key);
}

namespace Api {
api::ApiClient *client() { return AppContext::instance()->api(); }
} // namespace Api
