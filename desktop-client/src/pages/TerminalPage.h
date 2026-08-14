#pragma once
// 内置终端：通过 opencode（或系统 shell）用自然语言管理记忆。
// 基于 QProcess + 等宽输出区，输入行回车发送命令。

#include "BasePage.h"

#include <QProcess>

class QPlainTextEdit;
class QLineEdit;
class QPushButton;
class QComboBox;
class QLabel;

class TerminalPage : public BasePage {
    Q_OBJECT
public:
    explicit TerminalPage(QWidget *parent = nullptr);

    void refresh() override;
    QString pageKey() const override { return "terminal"; }

private slots:
    void startProcess();
    void stopProcess();
    void sendInput();
    void onOutputAvailable();
    void onErrorAvailable();
    void onProcessFinished(int exitCode, QProcess::ExitStatus status);
    void clearScreen();

private:
    void append(const QString &text, const QColor &color);

    QPlainTextEdit *m_output = nullptr;
    QLineEdit *m_input = nullptr;
    QPushButton *m_startBtn = nullptr;
    QPushButton *m_stopBtn = nullptr;
    QComboBox *m_cmdCombo = nullptr;
    QLabel *m_stateLabel = nullptr;
    QProcess *m_process = nullptr;
    QString m_cwd;
};
