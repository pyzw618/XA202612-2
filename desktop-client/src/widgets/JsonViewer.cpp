#include "JsonViewer.h"

#include <QApplication>
#include <QClipboard>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTimer>
#include <QVBoxLayout>

#include "../api/Json.h"

JsonViewer::JsonViewer(QWidget *parent) : QWidget(parent) {
    m_edit = new QPlainTextEdit(this);
    m_edit->setReadOnly(true);
    m_edit->setLineWrapMode(QPlainTextEdit::NoWrap);
    m_edit->setStyleSheet(
        "QPlainTextEdit { font-family: 'Cascadia Mono','JetBrains Mono',Consolas,monospace;"
        " font-size: 12px; background: #0F172A; color: #E2E8F0; border-radius: 6px; }");
    m_edit->setMaximumHeight(420);

    auto *copyBtn = new QPushButton("复制", this);
    copyBtn->setObjectName("textBtn");
    connect(copyBtn, &QPushButton::clicked, this, [this, copyBtn]() {
        if (m_edit->toPlainText().isEmpty()) return;
        QApplication::clipboard()->setText(m_edit->toPlainText());
        copyBtn->setText("已复制 ✓");
        QTimer::singleShot(1200, copyBtn, [copyBtn]() { copyBtn->setText("复制"); });
    });

    auto *top = new QHBoxLayout();
    top->addStretch();
    top->addWidget(copyBtn);

    auto *lay = new QVBoxLayout(this);
    lay->setContentsMargins(0, 0, 0, 0);
    lay->setSpacing(4);
    lay->addLayout(top);
    lay->addWidget(m_edit, 1);
}

void JsonViewer::setObject(const QJsonObject &o) {
    setText(QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Indented)));
}

void JsonViewer::setArray(const QJsonArray &a) {
    setText(QString::fromUtf8(QJsonDocument(a).toJson(QJsonDocument::Indented)));
}

void JsonViewer::setText(const QString &text) {
    m_edit->setPlainText(text);
    m_edit->moveCursor(QTextCursor::Start);
}

void JsonViewer::clear() { m_edit->clear(); }
