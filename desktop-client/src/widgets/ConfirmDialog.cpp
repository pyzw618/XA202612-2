#include "ConfirmDialog.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QVBoxLayout>

ConfirmDialog::ConfirmDialog(QWidget *parent) : QDialog(parent) {
    setWindowTitle("确认操作");
    setMinimumWidth(400);
    setModal(true);

    m_msg = new QLabel(this);
    m_msg->setWordWrap(true);

    m_input = new QLineEdit(this);
    m_input->setPlaceholderText("请输入确认文本");
    m_input->hide();

    auto *cancel = new QPushButton("取消", this);
    auto *ok = new QPushButton("确认", this);
    ok->setObjectName("dangerBtn");

    connect(cancel, &QPushButton::clicked, this, &QDialog::reject);
    connect(ok, &QPushButton::clicked, this, [this, ok]() {
        if (m_input->isVisible() && m_input->text().trimmed() != m_input->property("expect").toString()) {
            m_input->setStyleSheet("border: 1px solid #EF4444;");
            m_input->setPlaceholderText("输入不匹配，请重新输入");
            return;
        }
        accept();
    });

    auto *btnRow = new QHBoxLayout();
    btnRow->addStretch();
    btnRow->addWidget(cancel);
    btnRow->addWidget(ok);

    auto *lay = new QVBoxLayout(this);
    lay->setSpacing(12);
    lay->addWidget(m_msg);
    lay->addWidget(m_input);
    lay->addLayout(btnRow);
}

bool ConfirmDialog::confirm(QWidget *parent, const QString &title, const QString &message,
                            const QString &confirmText, const QString &confirmButtonText) {
    ConfirmDialog dlg(parent);
    dlg.setWindowTitle(title);
    dlg.m_msg->setText(message);
    if (!confirmText.isEmpty()) {
        dlg.m_input->show();
        dlg.m_input->setProperty("expect", confirmText);
        dlg.m_input->setPlaceholderText(QString("请输入 %1 确认").arg(confirmText));
    }
    if (!confirmButtonText.isEmpty()) {
        for (QPushButton *b : dlg.findChildren<QPushButton *>()) {
            if (b->text() == "确认") b->setText(confirmButtonText);
        }
    }
    return dlg.exec() == QDialog::Accepted;
}
