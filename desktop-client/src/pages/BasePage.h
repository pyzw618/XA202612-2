#pragma once
// 页面基类：所有内容页继承，提供统一的刷新/搜索入口。
// MainWindow 在用户切换 user_id 或全局搜索跳转时调用这些虚函数。

#include <QWidget>

class BasePage : public QWidget {
    Q_OBJECT
public:
    explicit BasePage(QWidget *parent = nullptr);
    ~BasePage() override = default;

    // 首次显示或手动刷新时重新拉取数据
    virtual void refresh() {}

    // 全局搜索跳转：由 MainWindow 调用，带上查询词
    virtual void applySearchQuery(const QString &query) {
        Q_UNUSED(query);
    }

    // 页面标识（用于调试/面包屑）
    virtual QString pageKey() const { return QString(); }
};
