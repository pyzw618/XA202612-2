// Kylin-MemoryHub 桌面客户端入口
// 目标：银河麒麟 V11 / openKylin（Qt 5.15 Widgets，UKUI 平台主题）

#include <QApplication>
#include <QFile>
#include <QMessageBox>
#include <QTextCodec>
#include <QTranslator>
#include <QLibraryInfo>

#include "AppContext.h"
#include "MainWindow.h"

int main(int argc, char *argv[]) {
    // Qt 5.6+ 默认启用高 DPI；旧版本显式开启以适配 2K/4K 屏
    QApplication::setAttribute(Qt::AA_EnableHighDpiScaling, true);
    QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps, true);

    QApplication app(argc, argv);
    QApplication::setOrganizationName("Kylin");
    QApplication::setApplicationName("Kylin-MemoryHub Client");
    QApplication::setApplicationDisplayName("MemoryHub 控制台");

    AppContext::create();

    // 加载全局样式（UKUI 风格）
    QFile qss(":/style/kylin.qss");
    if (qss.open(QIODevice::ReadOnly | QIODevice::Text)) {
        app.setStyleSheet(QString::fromUtf8(qss.readAll()));
        qss.close();
    }

    MainWindow w;
    w.show();

    return app.exec();
}
