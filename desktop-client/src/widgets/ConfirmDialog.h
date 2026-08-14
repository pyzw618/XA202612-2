#pragma once
// 危险操作确认对话框：支持仅确认 / 需输入确认文本两种模式。

#include <QDialog>

class QLabel;
class QLineEdit;

class ConfirmDialog : public QDialog {
    Q_OBJECT
public:
    explicit ConfirmDialog(QWidget *parent = nullptr);

    // 需输入文本确认（用于清空数据等危险操作）；confirmText 为空则只需点确认
    static bool confirm(QWidget *parent, const QString &title, const QString &message,
                        const QString &confirmText = QString(),
                        const QString &confirmButtonText = QString());

private:
    QLabel *m_msg = nullptr;
    QLineEdit *m_input = nullptr;
};
