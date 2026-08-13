#pragma once

#include <QWidget>
#include <QIcon>
#include <functional>

class QLabel;
class QPushButton;

enum class PageState { Loading, Content, Empty, Error, Offline };

class PageStateView : public QWidget {
    Q_OBJECT
public:
    explicit PageStateView(QWidget *parent = nullptr);

    void setState(PageState state, const QString &title, const QString &description,
                  const QIcon &icon = QIcon());
    void setAction(const QString &text, const std::function<void()> &action);
    void clearAction();
    PageState state() const { return m_state; }

private:
    PageState m_state = PageState::Content;
    QLabel *m_icon = nullptr;
    QLabel *m_title = nullptr;
    QLabel *m_description = nullptr;
    QPushButton *m_action = nullptr;
};
