#include "TerminalPage.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QProcess>
#include <QPushButton>
#include <QStandardPaths>
#include <QTextCursor>
#include <QVBoxLayout>

#include "../widgets/PageHeader.h"

#ifdef Q_OS_WIN
#define DEFAULT_SHELL "cmd"
#else
#define DEFAULT_SHELL "bash"
#endif

TerminalPage::TerminalPage(QWidget *parent) : BasePage(parent) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *header = new PageHeader(this);
    header->setTitle("opencode 终端");
    header->setSubtitle("通过 opencode 使用自然语言管理记忆：运行 opencode 后输入如“记住我周报用 Markdown”");
    m_startBtn = new QPushButton("启动", this);
    m_startBtn->setObjectName("primaryBtn");
    m_stopBtn = new QPushButton("停止", this);
    m_stopBtn->setObjectName("dangerBtn");
    m_stopBtn->setEnabled(false);
    connect(m_startBtn, &QPushButton::clicked, this, &TerminalPage::startProcess);
    connect(m_stopBtn, &QPushButton::clicked, this, &TerminalPage::stopProcess);
    header->actionLayout()->addWidget(m_stopBtn);
    header->actionLayout()->addWidget(m_startBtn);
    root->addWidget(header);

    // 命令选择行
    auto *cmdRow = new QHBoxLayout();
    cmdRow->setSpacing(8);
    auto *label = new QLabel("命令：", this);
    m_cmdCombo = new QComboBox(this);
    m_cmdCombo->setEditable(true);
    m_cmdCombo->addItem("opencode");
    m_cmdCombo->addItem(DEFAULT_SHELL);
    m_cmdCombo->addItem("bash");
    m_cmdCombo->addItem("cmd");
    m_cmdCombo->setFixedWidth(240);
    m_stateLabel = new QLabel("未启动", this);
    m_stateLabel->setStyleSheet("color:#8A8F99;font-size:12px;");
    auto *clearBtn = new QPushButton("清屏", this);
    connect(clearBtn, &QPushButton::clicked, this, &TerminalPage::clearScreen);
    cmdRow->addWidget(label);
    cmdRow->addWidget(m_cmdCombo);
    cmdRow->addWidget(m_stateLabel);
    cmdRow->addStretch();
    cmdRow->addWidget(clearBtn);
    root->addLayout(cmdRow);

    // 终端输出区
    m_output = new QPlainTextEdit(this);
    m_output->setReadOnly(true);
    m_output->setStyleSheet(
        "QPlainTextEdit { background:#0F172A; color:#E2E8F0;"
        " font-family:'Cascadia Mono','JetBrains Mono',Consolas,monospace; font-size:13px;"
        " border:1px solid #1E293B; border-radius:8px; padding:10px; }");
    m_output->setMaximumBlockCount(5000);
    root->addWidget(m_output, 1);

    // 输入行
    m_input = new QLineEdit(this);
    m_input->setPlaceholderText("输入命令回车执行（如：opencode / echo hello）");
    m_input->setStyleSheet("font-family:Consolas,monospace;font-size:13px;");
    connect(m_input, &QLineEdit::returnPressed, this, &TerminalPage::sendInput);
    root->addWidget(m_input);

    // 提示
    append("MemoryHub 终端：选择一个命令后点击「启动」。\n"
           "选择 opencode 时会在主目录打开系统终端，以获得完整交互体验。\n"
           "────────────────────────────────────────────\n",
           QColor("#94A3B8"));
}

void TerminalPage::refresh() {}

void TerminalPage::append(const QString &text, const QColor &color) {
    QTextCharFormat fmt;
    fmt.setForeground(color);
    QTextCursor cur = m_output->textCursor();
    cur.movePosition(QTextCursor::End);
    cur.insertText(text, fmt);
    m_output->setTextCursor(cur);
    m_output->ensureCursorVisible();
}

void TerminalPage::startProcess() {
    if (m_process && m_process->state() != QProcess::NotRunning) return;
    if (!m_process) {
        m_process = new QProcess(this);
        connect(m_process, &QProcess::readyReadStandardOutput, this, &TerminalPage::onOutputAvailable);
        connect(m_process, &QProcess::readyReadStandardError, this, &TerminalPage::onErrorAvailable);
        connect(m_process, qOverload<int, QProcess::ExitStatus>(&QProcess::finished),
                this, &TerminalPage::onProcessFinished);
    }
    const QString cmd = m_cmdCombo->currentText().trimmed();
    append(QString("$ %1\n").arg(cmd), QColor("#E2E8F0"));

#ifndef Q_OS_WIN
    if (cmd == QStringLiteral("opencode")) {
        const QString launcher = QStandardPaths::findExecutable(QStringLiteral("memoryhub-open-agent"));
        if (!launcher.isEmpty() && QProcess::startDetached(launcher, {})) {
            append("已在主目录打开系统终端并启动 OpenCode。\n", QColor("#34D399"));
            m_stateLabel->setText("已打开");
            m_stateLabel->setStyleSheet("color:#16A34A;font-size:12px;");
        } else {
            append("打开失败：未找到 memoryhub-open-agent，请重新安装最新版 MemoryHub。\n",
                   QColor("#F87171"));
        }
        return;
    }
#endif

#ifdef Q_OS_WIN
    m_process->setProcessChannelMode(QProcess::MergedChannels);
    m_process->start("cmd", QStringList() << "/c" << cmd);
#else
    m_process->setProcessChannelMode(QProcess::MergedChannels);
    m_process->start("bash", QStringList() << "-c" << cmd);
#endif

    if (m_process->waitForStarted(3000)) {
        m_startBtn->setEnabled(false);
        m_stopBtn->setEnabled(true);
        m_stateLabel->setText("运行中");
        m_stateLabel->setStyleSheet("color:#16A34A;font-size:12px;");
    } else {
        append(QString("启动失败：%1\n").arg(m_process->errorString()), QColor("#F87171"));
    }
}

void TerminalPage::stopProcess() {
    if (!m_process || m_process->state() == QProcess::NotRunning) return;
    m_process->terminate();
    if (!m_process->waitForFinished(2000)) {
        m_process->kill();
    }
    append("（已停止）\n", QColor("#94A3B8"));
}

void TerminalPage::sendInput() {
    const QString line = m_input->text();
    m_input->clear();
    if (line.trimmed().isEmpty()) return;
    if (!m_process || m_process->state() == QProcess::NotRunning) {
        append(QString("终端未启动，先点击「启动」\n"), QColor("#F87171"));
        return;
    }
    append("> " + line + "\n", QColor("#FBBF24"));
    m_process->write((line + "\n").toUtf8());
}

void TerminalPage::onOutputAvailable() {
    const QByteArray data = m_process->readAllStandardOutput();
    append(QString::fromUtf8(data), QColor("#E2E8F0"));
}

void TerminalPage::onErrorAvailable() {
    const QByteArray data = m_process->readAllStandardError();
    append(QString::fromUtf8(data), QColor("#F87171"));
}

void TerminalPage::onProcessFinished(int exitCode, QProcess::ExitStatus status) {
    Q_UNUSED(status);
    append(QString("\n（进程退出，代码 %1）\n").arg(exitCode), QColor("#94A3B8"));
    m_startBtn->setEnabled(true);
    m_stopBtn->setEnabled(false);
    m_stateLabel->setText("已结束");
    m_stateLabel->setStyleSheet("color:#8A8F99;font-size:12px;");
}

void TerminalPage::clearScreen() { m_output->clear(); }
