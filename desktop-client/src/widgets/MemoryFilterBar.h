#pragma once
// 记忆列表通用筛选栏：搜索框（防抖）+ 刷新按钮 + 可插入的自定义筛选控件。

#include <QWidget>

class QLineEdit;
class QPushButton;
class QHBoxLayout;
class QTimer;

class MemoryFilterBar : public QWidget {
    Q_OBJECT
public:
    explicit MemoryFilterBar(QWidget *parent = nullptr);

    QLineEdit *searchBox() const { return m_search; }
    QPushButton *refreshBtn() const { return m_refresh; }
    void addWidget(QWidget *w);
    void addStretch();
    void setSearchPlaceholder(const QString &hint);

signals:
    void searchTextChanged(const QString &text);   // 300ms 防抖
    void refreshRequested();

private:
    QLineEdit *m_search = nullptr;
    QPushButton *m_refresh = nullptr;
    QHBoxLayout *m_row = nullptr;
    QTimer *m_debounce = nullptr;
};
