# 银河麒麟 V11 原生桌面应用 UI 开发流程

> 适用对象：后端已就绪，仅需构建前端 UI 的开发者
> 目标环境：银河麒麟 V11 / openKylin 2.x（UKUI 桌面环境，兼容 X11 与 Wayland）
> 推荐技术栈：**Qt 5 (C++) + Qt Widgets / Qt Quick + UKUI 平台主题 + 麒麟开发者套件 (Kylin SDK)**

---

## 目录

1. [背景与结论速览](#1-背景与结论速览)
2. [技术选型：为什么是 Qt + UKUI](#2-技术选型为什么是-qt--ukui)
3. [原生感的秘密：qt5-ukui-platformtheme](#3-原生感的秘密qt5-ukui-platformtheme)
4. [Kylin SDK 三件套](#4-kylin-sdk-三件套)
   - 4.1 基础层 libkysdk-base
   - 4.2 桌面层 libkysdk-desktop
   - 4.3 系统能力层 libkysdk-system
   - 4.4 主题包结构：kylin-theme-builder 深度分析
5. [开发环境准备](#5-开发环境准备)
6. [完整开发流程](#6-完整开发流程)
   - 6.1 创建项目
   - 6.2 界面搭建（Widgets 路线）
   - 6.3 界面搭建（QML/Quick 路线）
   - 6.4 对接后端与系统服务
   - 6.5 主题适配与深浅色
7. [构建、打包与部署](#7-构建打包与部署)
8. [调试与常见问题](#8-调试与常见问题)
9. [参考仓库与源码获取](#9-参考仓库与源码获取)
10. [附录：SDK 关键 API 速查](#10-附录sdk-关键-api-速查)

---

## 1. 背景与结论速览

基于对 openKylin 社区《技术全景案例集（2024）》及 UKUI / wlcom / Kylin SDK 源码的调研，得出以下结论：

| 问题 | 结论 |
|---|---|
| 用什么框架 | **Qt 5**（UKUI 本身就是 Qt 技术栈，天然集成） |
| Widgets 还是 QML | 两者皆可；传统桌面表单类业务优先 **Qt Widgets**；现代动效/平板场景优先 **Qt Quick (QML)** |
| 怎么做到"像系统原生" | 安装并使用 **`qt5-ukui-platformtheme`**（QPA 平台主题插件），一行代码都不用写，系统自动接管按钮圆角、菜单毛玻璃、强调色等 |
| 怎么对接系统能力 | **Kylin SDK**：`libkysdk-base`（配置/日志/定时器）、`libkysdk-desktop`（主题/通知/应用管理/快捷键/音效）、`libkysdk-system`（系统信息/网络/电源/硬件） |
| 主题切换 | 通过 GSettings `org.ukui.style` 与 `org.mate.interface` 控制，SDK 提供封装 |
| 显示协议 | 银河麒麟默认 UKUI 4.x 支持 X11 + Wayland 双协议，Qt 应用两者皆可正常显示（wlcom 合成器） |
| 打包 | `.deb` 包（首选）、AppImage、linuxdeployqt |
| 主题包结构/定制 | 官方 **kylin-theme-builder**（主题制作工坊）源码揭示了主题包完整结构，可直接参考/复用 |

---

## 2. 技术选型：为什么是 Qt + UKUI

UKUI（Ultimate Kylin User Interface）是麒麟桌面环境的核心，其桌面核心组件（开始菜单、控制面板、任务栏、文件管理器 peony、设置中心 ukcc 等）**全部基于 Qt/C++ 开发**。因此：

- Qt 应用在麒麟系统上拥有**最好的原生集成度**（图标、字体、颜色、动效自动统一）
- 系统级平台主题插件 `qt5-ukui-platformtheme` 会自动为所有 Qt 应用应用 UKUI 风格，无需逐个调样式
- 后端可通过 Qt 的 `QtDBus` 模块与 KylinSDK 系统服务通信（获取日期格式、监听设置变化等）

> 注意：银河麒麟 V11 使用 UKUI 4.x（含 UKUI Framework + 轻量化 UI 重构），同时提供 wlcom（基于 wlroots 的 Wayland 合成器）。UI 开发层面无需直接接触 wlcom，只需保证应用遵循 Qt 平台规范即可。

---

## 3. 原生感的秘密：qt5-ukui-platformtheme

这是让 Qt 应用变"原生"的**核心组件**，建议优先理解它。

**仓库**：`https://gitee.com/openkylin/qt5-ukui-platformtheme`

**它做了什么**（源码分析结论）：

1. **QPA 平台主题插件**（`Qt5UKUIPlatformTheme`，注册名 `ukui`）：
   - 接管 `QPalette`（系统调色板）、`QFont`（系统字体）、图标引擎、原生对话框（文件选择器）、全局菜单、系统托盘等
   - 安装后系统自动加载，应用侧零代码
2. **QStyle 样式库 `libqt5-ukui-style`**：
   - 提供 `ukui-dark` / `ukui-default` / `ukui-light` 三种 Qt 风格
   - 提供大量控件细节参数（按钮圆角、滚动条动画、TabWidget 动画、阴影等），支持毛玻璃、区域模糊
3. **QML 支持**：
   - `qml-module-org-ukui-qqc2desktopstyle`（org.ukui.style 主题模块，QtQuickControls2 桌面风格）
   - `qml-module-org-ukui-stylehelper`（QML 主题辅助库，提供主题色/字体/图标）
4. **配置来源 GSettings schema `org.ukui.style`**，默认值如下：

| 键 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `style-name` | s | `"ukui-light"` | Qt 风格：ukui-dark / ukui-default / ukui-light |
| `icon-theme-name` | s | `"ukui-icon-theme-default"` | 图标主题 |
| `widget-theme-name` | s | `"default"` | 控件主题：default / classical / fashion |
| `system-font` | s | `"Noto Sans CJK SC"` | 系统字体 |
| `system-font-size` | s | `"10"` | 字号（point size） |
| `theme-color` | s | `"daybreakBlue"` | 强调色：default/daybreakBlue/jamPurple/magenta/sunRed/sunsetOrange/dustGold/polarGreen |
| `enabled-global-blur` | b | true | 全局毛玻璃开关 |
| `menu-transparency` | i | 72 | 菜单透明度 |
| `use-system-palette` | b | false | 是否使用系统调色板 |
| `custom-highlight-color` | s | `"#3D6BE5"` | 高亮色（第三方兼容用） |

**关键点**：`style-name` 与 GTK 主题 `org.mate.interface/gtk-theme` 联动（`ukui-dark`→`ukui-black`，`ukui-light`→`ukui-white`），深浅色切换由 UKUI 设置中心/ SDK 统一管理。

---

## 4. Kylin SDK 三件套

麒麟开发者套件（Kylin SDK）分三层，均在 openKylin 软件源中，名称与安装方式见第 5 节。

### 4.1 基础层 libkysdk-base

> 定位：日志管理、配置读写、消息通信、进程守护、定时器、调试埋点、utils
> 源码包：`libkysdk-base`，当前版本 2.5.1.0
> 头文件安装到：`/usr/include/kysdk/kysdk-base/`

| 子库 | 动态库 | 头文件 | 功能 |
|---|---|---|---|
| config | `libkyconf.so` | `libkyconf.h` | 配置文件读写（STRUCT 格式，支持 ini 风格 `[组]` + `key=value`） |
| conf2 | `libkyconf2.so` | `libkysettings.h` | **统一配置服务**（DBus 架构，schema 版本管理/权限/值域校验，推荐用于写配置） |
| log | `libkylog.so` | `libkylog.h` | 日志库（syslog 级别，异步队列，支持每日/大小滚动、压缩） |
| gsetting | `libkygsetting.so` | `libkygsetting.h` | GSettings 封装（C API） |
| timer | `libkytimer.so` | `libkytimer.h` | 定时器（单次/周期） |
| utils | `libkyutils.so`、`libkydatastruct.so` | `kyutils.h`、`cstring-extension.h` 等 | 单位换算、字符串扩展、跳表数据结构 |
| diagnostics | `libkydiagnostics.so` | `libkydiagnostics.h` | 埋点上报 |

> 注意：`libkyconf` 是 **C 接口**（`kdk_conf_*`），不是 Qt 的 `KConfig`；写入功能由 `conf2` 提供。`src/process` 进程守护模块默认不编译。

### 4.2 桌面层 libkysdk-desktop

> 定位：与桌面 UI/交互直接相关的能力
> 源码包：`libkysdk-desktop`，当前版本 3.0.1.0
> 头文件安装到：`/usr/include/kysdk/desktop/`，命名空间 `kdk`

| 模块 | 动态库 | 类 | 功能 |
|---|---|---|---|
| **主题管理** | `libkysdk-thememanager.so` | `kdk::KThemeManager` | 设置/查询系统主题、强调色、字体、字号、透明度、窗口特效 |
| **通知** | `libkysdk-notification.so` | `kdk::KNotifier` | 发送系统通知（D-Bus `org.freedesktop.Notifications`） |
| **应用管理** | `libkysdk-appmanager.so` | `kdk::KAppManager`、`kdk::AppInfo` | 枚举应用、按 MIME 取默认应用、开机自启 |
| **快捷键** | `libkysdk-shortcut.so` | `kdk::KGlobalShortcut` + C API | 全局快捷键注册/冲突检测（KGlobalAccel） |
| **音效** | `libkysdk-soundeffects.so` | `kdk::KSoundEffects` | 系统音效播放 |

### 4.3 系统能力层 libkysdk-system

> 定位：openSDK 的系统能力 SDK，获取系统/硬件/运行时信息
> 源码包：`libkysdk-system`，当前版本 2.5.1.2
> 头文件安装到：`/usr/include/kysdk/kysdk-system/`，**全部为 C 接口**（`extern "C"`）

| 模块 | 动态库 | 功能 |
|---|---|---|
| systeminfo | `libkysysinfo.so` | 系统名、版本、架构、内核、激活状态、主机名、用户切换、负载 |
| net | `libkynetinfo.so` | 端口状态、路由、防火墙、DNS、WiFi 信息、DHCP |
| powermanagement | `libkypowermanagement.so` | 电源模式、息屏超时、禁止/恢复锁屏 |
| hardware | `libkyhw.so`、`libkybluetooth.so`、`libkyedid.so`、`libkyfan.so` | CPU/BIOS/主板/显卡/网卡/USB/打印机/EDID/蓝牙/风扇 |
| accounts | `libkysdk-accounts.so` | 创建用户、改密、登录 |
| disk / storage | `libkydiskinfo.so` / `libkystorage.so` | 磁盘详情 / 文件系统、默认目录、文件操作 |
| filesystem | `libkyfilewatcher.so` | **文件监控（Qt5 C++）**：`FileWatcher` 类，监听创建/修改/删除/移动 |
| battery | `libkybattery.so` | 电量、充电状态、健康度、温度 |
| proc | `libkyrtinfo.so` | 内存/CPU 使用率、进程信息 |
| realtime | `libkyrealtime.so` | 实时网速、CPU/磁盘温度 |
| image / kdkocr | `libkyimageproc.so` / `libkyocr.so` | JPEG 编码 / OCR（PaddleOCR） |

> 通用约定：返回 `char*` 需 `free()`；返回 `char**` 用对应 `kdk_xxx_freeall()` 释放；返回结构体用 `kdk_xxx_free_xxx()`。

### 4.4 主题包结构：kylin-theme-builder 深度分析

`kylin-theme-builder`（主题制作工坊）是麒麟官方定制/打包系统主题的 Qt5 工具，**它的源码完整揭示了 UKUI 主题包的目录结构、配置文件格式、以及"主题包 ↔ 控制面板(ukcc)"的注册机制**。对想深度定制 UI 或为应用提供主题能力的开发者极具参考价值（当前版本 1.0.0.1-ok2.7）。

**技术栈**：Qt5 Widgets + `kysdk-qtwidgets`（KDialog/KNavigationBar/UkuiStyleHelper）+ `kysdk-sysinfo` + `kysdk-datacollect`（埋点）+ `kysdk-waylandhelper` + `ukui-log4qt` + `gsettings-qt`。

#### 4.4.1 它揭开了 UKUI 主题包的完整结构

制作完成后生成的 `.deb` 主题包源码内部文件树（这是 ukcc 主题页消费的标准布局）：

```
<themeEN>/                               # 主题名（英文小写，2~15字符，不能与系统包重名）
├── meson.build / meson_options.txt      # 安装规则（各组件开关）
├── debian/                              # deb 打包：control/changelog/postinst/postrm...
├── globalTheme/                         # ★ 全局主题
│   ├── theme.conf                       # ★ UKUI 全局主题核心配置（见 4.4.2）
│   ├── <themeEN>.json                   # ★ Qt 平台主题配色（json.txt 改名）
│   ├── preview.png                      # 控制面板封面（1640×1080）
│   ├── 1-openkylin.jpg                  # 壁纸（3840×2160）
│   └── wallpaper/*.xml                  # gnome 壁纸列表
├── iconTheme/<themeEN>/                 # 图标主题：index.theme + scalable + 8档尺寸PNG
├── cursorTheme/<themeEN>-cursor/        # 光标：index.theme/cursor.theme/cursor.sh/xcursorgen
├── plymouthTheme/                       # 开机动画：logo.plymouth + 104帧PNG
├── grubTheme/background-<themeEN>.png   # grub 背景
├── setupConfig/                         # 安装时写 gsettings 强调色
└── application/<themeEN>.desktop        # ★ 控制面板主题注册文件
```

#### 4.4.2 核心配置文件格式（可直接复用）

**`theme.conf`（安装到 `/usr/share/config/globaltheme/<themeEN>/`）**——ukcc 消费的核心描述文件：

```ini
[generic]
Name[zh_CN]=寻光

[color-schemes]
supportLightDarkMode=true
defaultLightDarkMode=light

[qt]
widgetStyleName=default
lightThemeName=ukui-light
darkThemeName=ukui-dark
mixedThemeName=ukui-default
accentRole=daybreakBlue

[gtk]
themeName=ukui-white
lightThemeName=ukui-white
darkThemeName=ukui-black
accent=#3790FA

[xdg]
iconThemeName=ukui-icon-theme-default
cursorThemeName=dark-sense
soundThemeName=Light-Seeking

[wallpaper]
wallPaperPath=/usr/share/backgrounds/1-openkylin.jpg

[effect]
supportBlur=true
blurEnabled=true
supportTransparency=true
transparencyBlur=65
transparencyNoBlur=90
supportAnimation=true
animationDuration=150
windowRadius=6
```

**`<themeEN>.json`（安装到 `/usr/share/qt5-ukui-platformtheme/themeconfig/`）**——这是 `qt5-ukui-platformtheme`（Qt5 平台主题插件）实际读取的配色文件，结构与 `org.ukui.style` schema 对应：

```json
{
  "Radius": {
    "Max_Radius": {"value": "8", "type": "int"},
    "Normal_Radius": {"value": "6", "type": "int"},
    "Min_Radius": {"value": "4", "type": "int"}
  },
  "ColorAdjustRules": "Default",
  "LightTheme": {
    "Palette": {
      "WindowText_at": {"value": "38, 38, 38", "type": "color"},
      "Button_at": {"value": "230, 230, 230", "type": "color"},
      "..._at/_iat/_dis": "…"
    },
    "PushButton": {
      "DefaultPushButton": {"DefaultBrush": {"value": "Button_at", "type": "paletterole"}, "..."}
    },
    "ToolButton": { "..." }, "LineEdit": { "..." }, "SpinBox": { "..." }, "ComboBox": { "..." },
    "ListView": { "..." }, "TreeView": { "..." }, "Table": { "..." }, "CheckBox": { "..." },
    "RadioButton": { "..." }, "SliderBar": { "..." }, "ProgressBar": { "..." }, "ScrollBar": { "..." },
    "ToolTip": { "..." }, "TabWidget": { "..." }, "Menu": { "..." }
  },
  "DarkTheme": { "…同样结构，深色配色…" }
}
```

> 命名约定：颜色名后缀 `_at`（active）/`_iat`（inactive）/`_dis`（disabled）；`type` 可为 `color`（RGB 或 `R,G,B,A*0.55` 表达式）或 `paletterole`（引用 `Palette` 中的键）。

**强调色 HEX ↔ 角色名映射**（来自 `bridge.cpp`，与 3.3 节 `theme-color` 枚举一致）：

| HEX | 角色名 | | HEX | 角色名 |
|---|---|---|---|---|
| `#3790FA` | daybreakBlue | | `#F3222D` | sunRed |
| `#7873F5` | jamPurple | | `#F68C27` | sunsetOrange |
| `#EB3096` | magenta | | `#F9C53D` | dustGold |
| `#52C429` | polarGreen | | | |

#### 4.4.3 主题如何被系统安装/识别（注册机制）

1. **注册入口**：`/usr/share/kylin-theme-builder/desktops/<themeEN>.desktop`（ukcc 控制面板主题页扫描此目录识别可切换主题）。
2. **全局主题**：`theme.conf` + `preview` + 壁纸 → `/usr/share/config/globaltheme/<themeEN>/`。
3. **图标/光标**：`/usr/share/icons/<themeEN>/`、`/usr/share/icons/<themeEN>-cursor/`（含 `index.theme` + `cursors/`，用 `xcursorgen` 生成 X11 光标）。
4. **Qt 配色**：`<themeEN>.json` → `/usr/share/qt5-ukui-platformtheme/themeconfig/`，平台主题插件自动读取。
5. **强调色**：通过 `40_kylin-theme-builder.gschema.override`（写 `org.ukui.style theme-color`）安装时改 schema 默认值；`/etc/xdg/autostart/kylin-theme-builder-change.desktop` 开机自启脚本补写 `gsettings set org.ukui.style theme-color <accentRole>`。
6. **plymouth/grub**：`update-alternatives` 切换开机动画、`sed` 改写 `/usr/share/grub/themes/UKUI/theme.txt` 的 `desktop-image:`。
7. **打包**：`tar` 出 orig 源码包 → `debuild -us -uc` 生成 `.deb`（纯数据包 `Architecture: all`）。

#### 4.4.4 对应用开发者的价值

- **若你的应用需要"主题包"能力**（自定义壁纸/图标/配色并让系统识别）：直接复用上述目录结构与 `theme.conf`/`json` 格式。
- **若只需应用内适配系统主题**：无需理解打包，用第 3 节 `org.ukui.style` GSettings + `KThemeManager` 即可。
- **新增 SDK 库速记**：`libkysdk-qtwidgets`（UKUI 原生控件：`kdk::KDialog`、`kdk::KNavigationBar`、`UkuiStyleHelper`）、`libkysdk-datacollect`（埋点 `kdk_dia_*`）、`libkysdk-waylandhelper`（Wayland 窗口模糊/圆角辅助）、`libukui-log4qt`（`initUkuiLog4qt()` 日志）。

---

## 5. 开发环境准备

推荐在**麒麟 V11（或 openKylin 2.x）真机/虚拟机**上开发，保证所见即所得。你的开发机是 x86_64，目标若为 ARM（飞腾/鲲鹏）需交叉编译或目标机编译。

```bash
# 1) 基础编译工具
sudo apt update
sudo apt install build-essential gdb cmake git

# 2) Qt 5 开发环境（麒麟源内置 Qt 5.15.x）
sudo apt install qt5-default qtbase5-dev qtbase5-dev-tools qtchooser
sudo apt install qtcreator
# 常用模块
sudo apt install libqt5network5-dev libqt5sql5-dev libqt5svg5-dev \
                 libqt5x11extras5-dev qtdeclarative5-dev qtquickcontrols2-5-dev

# 3) UKUI 平台主题（原生感核心，通常系统已预装）
sudo apt install qt5-ukui-platformtheme qt5-styles-ukui libqt5-ukui-style1
# 开发它的 API 需要：
sudo apt install libqt5-ukui-style-dev qml-module-org-ukui-qqc2desktopstyle \
                 qml-module-org-ukui-stylehelper

# 4) 麒麟开发者套件（Kylin SDK）
sudo apt install libkysdk-base-dev libkysdk-desktop-dev libkysdk-system-dev
# 附加 SDK（见 4.4）：UKUI 原生控件 / 埋点 / Wayland 辅助 / 日志
sudo apt install libkysdk-qtwidgets-dev libkysdk-datacollect-dev \
                 libkysdk-waylandhelper-dev libukui-log4qt-dev

# 5) 让 gsettings 配置生效（若主题切换后无变化）
sudo glib-compile-schemas /usr/share/glib-2.0/schemas
```

**验证平台主题生效**：

```bash
export QT_QPA_PLATFORMTHEME=ukui
# 运行任意 Qt 程序，观察是否为 UKUI 风格（系统预装时默认即 ukui）
```

---

## 6. 完整开发流程

### 6.1 创建项目

在 Qt Creator 中新建：
- **Qt Widgets Application**：传统桌面业务（表单、表格、树、设置页等），推荐
- **Qt Quick Application (QML)**：现代动效、触摸友好界面

构建系统建议 **CMake**（跨平台、与后端工程易集成），老工程可沿用 qmake。

工程结构建议：

```
MyApp/
├── CMakeLists.txt
├── src/                # C++ 业务逻辑 + UI 代码
├── qml/                # (QML路线) *.qml
├── ui/                 # (Widgets路线) *.ui
├── resources.qrc       # 图标、qss 等资源
├── translations/       # *.ts 国际化
└── packaging/          # deb 打包相关（debian/ 目录或脚本）
```

### 6.2 界面搭建（Widgets 路线）

1. 用 Qt Designer（.ui）拖控件，或代码构建布局。
2. **不要手写 QSS 硬编码颜色**：让 UKUI 平台主题接管。遵循 Qt 标准控件 + 标准调色板角色（`QPalette::Highlight`、`Window` 等）即可自动适配深浅色。
3. 需要与系统一致的对话框时，直接使用 `QFileDialog`/`QMessageBox` 等原生对话框——平台主题会自动替换为 UKUI 原生实现。
4. 若需读取系统强调色/字体以自定义渲染，用 GSettings：

```cpp
#include <QGSettings>
QGSettings styleSettings("org.ukui.style");
QString themeColor = styleSettings.get("theme-color").toString();   // daybreakBlue ...
QString font       = styleSettings.get("system-font").toString();   // Noto Sans CJK SC
```

### 6.3 界面搭建（QML/Quick 路线）

1. QML 中为 `ApplicationWindow` 设置 UKUI 风格：

```qml
import org.ukui.style 1.0
ApplicationWindow {
    // 使用 ukui-qqc2 风格时，控件自动带 UKUI 外观
}
```

或 C++ 侧指定风格：

```cpp
#include <QQuickStyle>
int main(int argc, char **argv) {
    QQuickStyle::setStyle("org.ukui.style");   // 或使用平台主题默认
    ...
}
```

2. 需要更细粒度主题信息时，使用 stylehelper：`import org.ukui.style.private 1.0 as StylePrivate`，读取 `StylePrivate.StyleHelper` 提供的调色板/主题色/字体。
3. 平板模式（若需）通过 DBus 查询：`com.kylin.statusmanager.interface` 的 `get_current_tabletmode`，据此切换布局密度。

### 6.4 对接后端与系统服务

**方式 A：QtDBus（推荐）**——后端若暴露 DBus 服务：

```cpp
#include <QDBusInterface>
QDBusInterface iface("com.your.Backend", "/", "com.your.Backend",
                     QDBusConnection::sessionBus());
QDBusReply<QVariantMap> reply = iface.call("GetStatus");
if (reply.isValid()) { /* 处理 */ }
```

**方式 B：Kylin SDK**——需要系统能力时（见附录 API 速查）。

**方式 C：HTTP/WebSocket**——后端为 REST 服务，用 QtNetwork 即可（银河麒麟支持国产加密网络栈，一般无需特殊处理）。

### 6.5 主题适配与深浅色

应用应响应系统主题切换：

```cpp
// 监听平台主题变化
QGSettings settings("org.ukui.style");
connect(&settings, &QGSettings::changed, [](const QString &key){
    if (key == "style-name") { /* 刷新 UI 配色/图标 */ }
});
```

复杂应用建议使用 Qt 6 的 `ColorScheme` 或自行维护 `QPalette` 派生类；简单应用直接依赖平台主题自动处理即可。

---

## 7. 构建、打包与部署

### 构建

```bash
# CMake
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

### 打包为 .deb（推荐，麒麟为 Debian 系）

```bash
# 方式一：简单脚本打包（把依赖打进 /usr/lib/<app>/）
# 方式二：debian/ 目录 + dpkg-buildpackage（正规做法）
dpkg-buildpackage -us -uc -b
```

### 依赖收集与 AppImage

```bash
# linuxdeployqt（Qt 官方推荐 Linux 部署工具）
wget -q https://github.com/probonopd/linuxdeployqt/releases/download/7/linuxdeployqt-7-x86_64.AppImage
chmod +x linuxdeployqt-7-x86_64.AppImage
./linuxdeployqt-7-x86_64.AppImage MyApp

# 若用到 Kylin SDK 库，需额外拷贝：
#   libkysdk-*.so*  ->  /usr/lib/x86_64-linux-gnu/（系统已装则无需）
```

### 架构注意事项

- 目标为 ARM（飞腾/鲲鹏/麒麟）时：使用**目标机编译**或**交叉编译**（`aarch64-linux-gnu-g++` + 目标 Qt）
- 所有 Kylin SDK 均支持 x86_64 / arm64 / loong64 / riscv64（见构建服务二进制包列表）

---

## 8. 调试与常见问题

| 现象 | 排查 |
|---|---|
| 界面不是 UKUI 风格 | `export QT_QPA_PLATFORMTHEME=ukui`；确认 `qt5-ukui-platformtheme` 已装；`glib-compile-schemas /usr/share/glib-2.0/schemas` |
| 深浅色不跟随系统 | 监听 `org.ukui.style/style-name` 变化并刷新 palette |
| 毛玻璃/透明无效果 | 确认 `enabled-global-blur` 为 true，且窗口设了透明属性 |
| SDK 接口无响应 | 确认对应 DBus 服务运行：`org.freedesktop.Notifications`、`conf2-server`、`kysdk-net`、`kdkshortcut` 等 |
| 中文字体错乱 | `org.ukui.style/system-font` 需为系统字体列表中存在的字体（Noto Sans CJK SC） |
| Wayland 下截图/全局热键失效 | Wayland 对全局热键有安全限制，使用 `KGlobalShortcut`/`libkysdk-shortcut` 注册 |
| 编译器报找不到 SDk 头文件 | 安装 `libkysdk-*-dev` 后，`pkg-config --cflags --libs kysdk-system`（或对应模块 .pc） |

---

## 9. 参考仓库与源码获取

> 麒麟官方源码主要托管在 **Gitee**（openkylin 组织）。若 Gitee 要求登录/代理失效，可用 GitHub 镜像 `github.com/OpenKylin/<repo>`（部分仓库镜像为空，需回 Gitee 或用构建服务下载源码包）。

| 仓库 | Gitee 地址 | 用途 |
|---|---|---|
| **qt5-ukui-platformtheme** | `gitee.com/openkylin/qt5-ukui-platformtheme` | ⭐ 平台主题 + UKUI 样式库 + QML 风格（原生感核心） |
| **openkylin-theme** | `gitee.com/openkylin/openkylin-theme` | UKUI 主题资源（GTK/Qt 主题、图标、音效、光标） |
| **ukui-interface** | `gitee.com/openkylin/ukui-interface` | UKUI 核心接口库（log4qt 日志、common 工具） |
| **libkysdk-base** | `gitee.com/openkylin/libkysdk-base` | 开发者套件·基础层（配置/日志/定时器/埋点） |
| **libkysdk-desktop** | `gitee.com/openkylin/libkysdk-desktop` | 开发者套件·桌面层（主题/通知/应用/快捷键/音效） |
| **libkysdk-system** | `gitee.com/openkylin/libkysdk-system` | openSDK 系统能力（系统信息/网络/电源/硬件） |
| **kylin-theme-builder** | `gitee.com/openkylin/kylin-theme-builder` | ⭐ 主题制作工坊：揭示 UKUI 主题包结构与注册机制（见 4.4 节） |
| ukui-control-center | `gitee.com/openkylin/ukui-control-center` | UKUI 设置中心（深度集成 UI 最佳范例） |
| peony | `gitee.com/openkylin/peony` | 文件管理器（Qt Widgets 最佳范例） |
| ukui-menu | `gitee.com/openkylin/ukui-menu` | 开始菜单（QML/Widgets 混合范例） |
| kylin-wayland-compositor | `gitee.com/openkylin/kylin-wayland-compositor` | wlcom 合成器（了解显示协议，一般不需动） |

**源码包下载（Git 拉不动的场景）**：openKylin 构建服务 `build.openkylin.top` 可下载官方 orig 源码包，例如：
- `https://build.openkylin.top/openkylin/nile/+source/libkysdk-base`（源码包：`libkysdk-base_2.5.1.0.orig.tar.xz`）
- `https://build.openkylin.top/openkylin/nile/+source/libkysdk-system`
- `https://build.openkylin.top/openkylin/nile.bedrock/+source/libkysdk-desktop`
- `https://build.openkylin.top/openkylin/nile/+source/openkylin-theme`

> 本项目已将核心源码拉取至 `代码仓库分析/` 目录：`qt5-ukui-platformtheme`、`ukui-interface`、`libkysdk-desktop`（git 克隆）及 `sdk-source/libkysdk-base`、`sdk-source/libkysdk-system`、`sdk-source/libkysdk-desktop-3.0.1.0`、`sdk-source/openkylin-theme-ok0.8`、`sdk-source/kylin-theme-builder-ok2.7`（构建服务源码包），可直接查阅。

---

## 10. 附录：SDK 关键 API 速查

### 10.1 桌面层 libkysdk-desktop

**主题管理 `kdk::KThemeManager`**（`#include <kthememanager.h>`，链接 `-lkysdk-thememanager`）

```cpp
kdk::KThemeManager m;
QString global = m.getUkccGlobalTheme();      // 当前全局主题
QStringList list = m.getSupportSystemStyle(); // [ukui-dark, ukui-default, ukui-light]
bool ok = m.setSystemStyle("ukui-dark");      // 设暗色主题（同时写 GTK + Qt）
bool ok = m.setSystemThemeColor("daybreakBlue");
bool ok = m.setSystemFont("Noto Sans CJK SC");
bool ok = m.setSystemFontSize(12);
bool ok = m.setPanelSpecialEffect(true);      // 窗口特效
bool ok = m.setTransparency(0.70);            // 透明度
connect(&m, &kdk::KThemeManager::changed, [](QString prop, QVariant val){});
```

**通知 `kdk::KNotifier`**（`#include <knotifier.h>`，链接 `-lkysdk-notification`）

```cpp
kdk::KNotifier n;
n.setAppName("MyApp");
n.setSummary("标题");
n.setBodyText("正文内容");
n.setAppIcon("my-app");        // 系统图标名
n.addAction("myapp.open", "打开"); // 按钮（最多3个）
uint id = n.notify();          // 发送，返回通知id
kdk::KNotifier::closeNotification(id); // 关闭
```

### 10.2 基础层 libkysdk-base

**配置读写 `libkyconf.h`**（C 接口，链接 `-lkyconf`）

```c
#include <libkyconf.h>
int id = kdk_conf_init("/etc/app.conf");
const char *v = kdk_conf_get_value(id, "System", "Version");
kdk_conf_destroy(id);
```

**统一配置 `libkysettings.h`**（conf2，链接 `-lkyconf2`，推荐写场景）

```c
#include <libkysettings.h>
KSettings *s = kdk_conf2_new("test.notice", NULL);
char *v = kdk_conf2_get_string(s, "name");
int ok = kdk_conf2_set_int(s, "port", 8080);
kdk_conf2_ksettings_destroy(s);
```

**日志 `libkylog.h`**（链接 `-lkylog`）

```c
#include <libkylog.h>
kdk_logger_init(NULL);          // 用默认配置
klog_info("port=%d", 8080);     // klog_trace/debug/info/warning/err/crit/alert/emerg
```

### 10.3 系统能力层 libkysdk-system

**系统信息 `libkysysinfo.h`**（链接 `-lkysysinfo`）

```c
#include <kysdk/kysdk-system/libkysysinfo.h>
char *arch = kdk_system_get_architecture();   // x86_64 / aarch64
char *name = kdk_system_get_systemName();     // 银河麒麟...
char *ver  = kdk_system_get_version(true);
char *host = kdk_system_get_hostName();
kdk_loadavg la = kdk_system_get_loadavg();
free(arch); free(name); free(ver); free(host);
```

**电源/锁屏 `libkypowermanager.h`、`libkylockscreen.h`**（链接 `-lkypowermanagement`）

```c
int idle = kdk_power_get_screenidle_timeout();   // 息屏超时
int mode = kdk_power_get_mode();                 // 0性能 1平衡 2能效
uint32_t flag = kdk_set_inhibit_lockscreen("MyApp", "正在播放视频");
kdk_un_inhibit_lockscreen(flag);
```

**网络 `libkynetinfo.h`**（链接 `-lkynetinfo`）

```c
int type = kdk_net_get_link_type();   // LINK_TYPE_ETHERNET/WIFI...
char **cards = kdk_nc_get_cardlist(); // 网卡列表（hardware 模块）
```

**文件监控 `libkyfilewatcher.hpp`**（Qt5 C++，链接 `-lkyfilewatcher`）

```cpp
#include <kysdk/kysdk-system/libkyfilewatcher.hpp>
KYSDK_FILEWATCHER::FileWatcher w;
w.addWatchTarget("/data/upload", FileWatcherType::PERIODIC, OPEN|CLOSE|MODIFY|DELETE);
connect(&w, &FileWatcher::fileCreated, [](QString f){ qDebug() << f; });
```

### 10.4 编译示例

```pro
# qmake
QT += widgets gui dbus
CONFIG += link_pkgconfig
PKGCONFIG += kysdk-thememanager kysdk-notification kysdk-system
SOURCES += main.cpp
```

```cmake
# CMake
find_package(PkgConfig REQUIRED)
pkg_check_modules(KYSDK REQUIRED kysdk-thememanager kysdk-notification kysdk-system)
target_link_libraries(myapp PRIVATE ${KYSDK_LIBRARIES})
target_include_directories(myapp PRIVATE ${KYSDK_INCLUDE_DIRS})
```

---

## 参考来源

- OpenAtom openKylin 社区《技术全景案例集（2024）》：UKUI 桌面环境、wlcom 合成器、openSDK 章节
- `qt5-ukui-platformtheme` 源码：org.ukui.style schema、QStyle/平台主题插件
- `libkysdk-base` / `libkysdk-desktop` / `libkysdk-system` 源码：各模块 API
- `kylin-theme-builder` 源码：UKUI 主题包结构、theme.conf / themeconfig json 格式、主题注册机制
- 《Qt 开发麒麟 Linux 桌面应用程序的流程》《前端开发思路》调研笔记
