#include "AppContext.h"

#include "api/ApiClient.h"

AppContext *AppContext::s_instance = nullptr;

AppContext::AppContext(QObject *parent)
    : QObject(parent),
      m_api(new api::ApiClient(this)),
      m_userId(QStringLiteral("default")),
      m_baseUrl(QStringLiteral("http://127.0.0.1:8099")) {
    m_api->setBaseUrl(m_baseUrl);
    m_api->setUserId(m_userId);
}

AppContext::~AppContext() = default;

void AppContext::create() {
    if (!s_instance) s_instance = new AppContext();
}

AppContext *AppContext::instance() { return s_instance; }

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
