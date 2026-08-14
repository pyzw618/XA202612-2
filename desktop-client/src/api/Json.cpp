#include "Json.h"

#include <QDateTime>
#include <QJsonParseError>
#include <QLocale>
#include <QRegularExpression>

namespace j {

QString str(const QJsonObject &o, const QString &key, const QString &def) {
    const QJsonValue v = o.value(key);
    if (v.isUndefined() || v.isNull()) return def;
    if (v.isString()) return v.toString();
    if (v.isDouble()) return QString::number(v.toDouble());
    if (v.isBool()) return v.toBool() ? "true" : "false";
    return def;
}

double num(const QJsonObject &o, const QString &key, double def) {
    const QJsonValue v = o.value(key);
    if (!v.isDouble()) return def;
    return v.toDouble();
}

int integer(const QJsonObject &o, const QString &key, int def) {
    const QJsonValue v = o.value(key);
    if (v.isDouble()) return int(v.toDouble());
    if (v.isString()) {
        bool ok = false;
        int n = v.toString().toInt(&ok);
        return ok ? n : def;
    }
    return def;
}

bool boolean(const QJsonObject &o, const QString &key, bool def) {
    const QJsonValue v = o.value(key);
    if (v.isBool()) return v.toBool();
    if (v.isString()) {
        const QString s = v.toString().toLower();
        if (s == "true" || s == "1") return true;
        if (s == "false" || s == "0") return false;
    }
    return def;
}

QJsonObject obj(const QJsonObject &o, const QString &key) {
    const QJsonValue v = o.value(key);
    return v.isObject() ? v.toObject() : QJsonObject();
}

QJsonArray arr(const QJsonObject &o, const QString &key) {
    const QJsonValue v = o.value(key);
    return v.isArray() ? v.toArray() : QJsonArray();
}

QStringList strList(const QJsonObject &o, const QString &key) {
    QStringList out;
    const QJsonValue v = o.value(key);
    if (v.isArray()) {
        const QJsonArray a = v.toArray();
        for (const QJsonValue &item : a) {
            if (item.isString()) out << item.toString();
            else if (item.isDouble()) out << QString::number(item.toDouble());
        }
    } else if (v.isString()) {
        out << v.toString();
    }
    return out;
}

bool contains(const QJsonObject &o, const QString &key) {
    const QJsonValue v = o.value(key);
    return !v.isUndefined() && !v.isNull();
}

QString pretty(const QJsonObject &o) {
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Indented));
}

QString pretty(const QJsonArray &a) {
    return QString::fromUtf8(QJsonDocument(a).toJson(QJsonDocument::Indented));
}

QString fmtNum(double v, int decimals) {
    // 接近整数的数值按整数展示，避免 1.00
    if (qAbs(v - qRound(v)) < 1e-9) return QString::number(qRound(v));
    return QString::number(v, 'f', decimals);
}

QString pct(double v, int decimals) {
    return QString::number(v * 100.0, 'f', decimals) + "%";
}

QDateTime parseDateTime(const QString &iso) {
    QString s = iso.trimmed();
    if (s.isEmpty()) return QDateTime();
    // 兼容 "2026-08-11T10:00:00.000Z" / 带时区 / 不带时间
    QDateTime dt = QDateTime::fromString(s, Qt::ISODate);
    if (dt.isValid()) return dt;
    // 尝试去掉毫秒
    s = s.replace(QRegularExpression("\\.\\d{1,9}"), "");
    dt = QDateTime::fromString(s, Qt::ISODate);
    if (dt.isValid()) return dt;
    return QDateTime();
}

QString localTime(const QString &isoDateTime) {
    const QDateTime dt = parseDateTime(isoDateTime);
    if (!dt.isValid()) return isoDateTime;
    QDateTime local = dt.toLocalTime();
    return local.toString("yyyy-MM-dd HH:mm:ss");
}

QString fmtTime(const QString &isoDateTime) {
    return localTime(isoDateTime);
}

QString timeAgo(const QString &isoDateTime) {
    const QDateTime dt = parseDateTime(isoDateTime);
    if (!dt.isValid()) return isoDateTime;
    const QDateTime local = dt.toLocalTime();
    const qint64 secs = local.secsTo(QDateTime::currentDateTime());
    if (secs < 0) return local.toString("yyyy-MM-dd HH:mm");
    if (secs < 60) return QString("%1 秒前").arg(secs);
    if (secs < 3600) return QString("%1 分钟前").arg(secs / 60);
    if (secs < 86400) return QString("%1 小时前").arg(secs / 3600);
    if (secs < 86400 * 30) return QString("%1 天前").arg(secs / 86400);
    return local.toString("yyyy-MM-dd");
}

QString shortId(const QString &id) {
    const int idx = id.indexOf('_');
    if (idx >= 0 && idx + 1 < id.size()) return id.mid(idx + 1);
    return id;
}

} // namespace j
