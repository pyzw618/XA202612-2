#pragma once
// JSON 便捷访问工具：所有页面统一通过 j:: 命名空间读写 QJson 对象，
// 屏蔽后端动态字段的差异，简化页面代码。

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>
#include <QStringList>

namespace j {

// ---- 读取 ----
QString str(const QJsonObject &o, const QString &key, const QString &def = QString());
double num(const QJsonObject &o, const QString &key, double def = 0.0);
int integer(const QJsonObject &o, const QString &key, int def = 0);
bool boolean(const QJsonObject &o, const QString &key, bool def = false);
QJsonObject obj(const QJsonObject &o, const QString &key);
QJsonArray arr(const QJsonObject &o, const QString &key);
QStringList strList(const QJsonObject &o, const QString &key);
bool contains(const QJsonObject &o, const QString &key);

// ---- 序列化展示 ----
QString pretty(const QJsonObject &o);
QString pretty(const QJsonArray &a);
// 数字统一格式化：整数不带小数点，浮点保留 2~3 位
QString fmtNum(double v, int decimals = 2);
// 百分比展示（0~1 -> 0%~100%）
QString pct(double v, int decimals = 0);

// ---- 时间展示 ----
// 相对时间（"3 分钟前"），悬停可显示绝对时间
QString timeAgo(const QString &isoDateTime);
// 绝对时间（yyyy-MM-dd HH:mm:ss）
QString fmtTime(const QString &isoDateTime);

// 把 ISO 时间字符串转成本地可读文本（失败返回原串）
QString localTime(const QString &isoDateTime);

// 短 ID（pref_ab12cd34 -> ab12cd34）用于紧凑展示
QString shortId(const QString &id);

} // namespace j
