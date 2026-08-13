# MemoryHub Qt 前端视觉重构执行方案

> 本文用于新一轮 Codex 对话直接执行。执行前应先阅读本文，再检查当前工作区状态；不要重新讨论技术选型，也不要修改后端。

## 1. 项目现状

### 1.1 项目位置

- 仓库根目录：`D:\Python_Project\XA202612-2`
- Qt 前端源码：`D:\Python_Project\XA202612-2\desktop-client`
- Windows 构建目录：`D:\software\mhub-build`
- Windows 可执行文件：`D:\software\mhub-build\memoryhub-client.exe`
- 英文源码目录映射：`D:\software\mhub-src` → `D:\Python_Project\XA202612-2\desktop-client`

### 1.2 技术栈

- Qt 5.15.2 Widgets
- C++17
- Qt Network
- Qt Charts
- CMake + MSVC 2022
- 目标系统：银河麒麟 V11 / openKylin
- 当前开发预览系统：Windows

### 1.3 已安装的 Windows 工具链

- Visual Studio 2022 Build Tools：
  `D:\software\Microsoft Visual Studio\2022\BuildTools`
- CMake：
  `D:\software\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe`
- Qt：
  `D:\conda\Library`
- Qt 部署工具：
  `D:\conda\Library\bin\windeployqt.exe`

### 1.4 当前代码结构

```text
desktop-client/
├─ resources/
│  ├─ app.qrc
│  └─ style/kylin.qss
└─ src/
   ├─ main.cpp
   ├─ MainWindow.cpp/.h
   ├─ AppContext.cpp/.h
   ├─ api/
   ├─ widgets/
   │  ├─ PageHeader
   │  ├─ StatCard
   │  ├─ ScoreRing
   │  ├─ StatusTag
   │  ├─ DetailDrawer
   │  ├─ EmptyState
   │  ├─ MemoryFilterBar
   │  ├─ ConfirmDialog
   │  └─ JsonViewer
   └─ pages/
      ├─ DashboardPage
      ├─ TerminalPage
      ├─ PreferencePage
      ├─ KnowledgePage
      ├─ FactPage
      ├─ SearchPage
      ├─ ConflictPage
      ├─ ForgetPages
      ├─ SafetyPages
      └─ SettingsPages
```

## 2. 已确定的视觉方向

视觉比例已经由用户确认：

```text
现代专业工作台       70%
UKUI 原生兼容        20%
MemoryHub AI 品牌感  10%
```

整体气质：

- 清晰
- 理性
- 可靠
- 轻盈
- 有适量技术感
- 适合长期使用，不做宣传页式炫技

### 2.1 推荐视觉原则

- 柔和浅灰页面背景
- 白色卡片
- 低饱和蓝色主色
- 细边框与极轻阴影
- 统一线性 SVG 图标
- 适中的信息密度和明确的层级
- 风险信息使用语义色，但避免大面积红橙色
- 少量蓝紫品牌渐变只用于 Logo 或关键品牌元素
- 避免大面积毛玻璃、霓虹光效和复杂动画

### 2.2 基础设计令牌

第一轮先实现浅色主题，同时保留未来从 `QPalette`/UKUI 读取系统颜色的接口。

建议色值：

```text
appBackground       #F3F6FA
sidebarBackground   #F7F9FC
surface             #FFFFFF
surfaceSecondary    #F7F9FC

textPrimary         #20242C
textSecondary       #697180
textTertiary        #8B93A2

borderSubtle        #E8EBF0
borderDefault       #DCE2EA

primary             #3D78DF
primaryHover        #336DCC
primarySoft         #E8F0FF

success             #27855B
warning             #B5791E
danger              #C55135
info                 #4677D1

preference          #4B7FE0
knowledge           #7F6BDC
fact                #39A6AF
```

字体层级：

```text
页面标题       20px / Medium 或 DemiBold
区块标题       15px / Medium
正文           13px / Regular
辅助文字       12px / Regular
核心指标       26–30px / Medium 或 DemiBold
表头           12px / Medium
```

间距和圆角：

```text
页面边距       24px（较小窗口可降为 20px）
大区块间距     20–24px
卡片间距       12–16px
控件间距       8px
按钮/输入圆角  6–8px
卡片圆角       10px
抽屉/对话框    12px
```

## 3. 本轮重构目标

本轮只完成两件事：

1. 落地全局应用外壳与基础设计系统。
2. 将 Dashboard 做成真实可运行的 Qt 高保真样板页。

本轮不批量重做其他 20 个页面，只保证它们在新外壳中仍能打开和使用。

## 4. 明确的范围边界

### 4.1 本轮允许修改

- `desktop-client/src/MainWindow.cpp/.h`
- `desktop-client/src/main.cpp`
- `desktop-client/src/pages/DashboardPage.cpp/.h`
- `desktop-client/src/widgets/PageHeader.cpp/.h`
- `desktop-client/src/widgets/StatCard.cpp/.h`
- 必要时新增少量通用 UI 组件
- `desktop-client/resources/style/kylin.qss`
- `desktop-client/resources/app.qrc`
- 新增 `desktop-client/resources/icons/*.svg`
- `desktop-client/CMakeLists.txt`（仅在新增源码文件时）
- Windows 构建脚本（仅为适配现有 D 盘工具链）

### 4.2 本轮禁止修改

- 不修改 `memoryhub/` 后端代码
- 不修改后端数据库、审计文件、密钥文件
- 不伪造正式业务统计数据
- 不删除或重写现有其他页面业务逻辑
- 不将项目改写为 Web、QML 或 Qt 6
- 不引入重量级第三方 UI 框架
- 不在运行时依赖互联网图标/CDN
- 不使用 Emoji 作为正式界面图标
- 不为追求视觉效果破坏银河麒麟/UKUI 兼容性

## 5. 第一阶段：修复窗口启动阻塞

这是落地视觉重构前必须先完成的问题。

### 5.1 已确认的根因

当前执行顺序是：

```text
main.cpp
  → 构造 MainWindow
  → MainWindow 初始 navigateTo("dashboard")
  → DashboardPage::refresh()
  → 连续执行多次同步 HTTP 请求
  → MainWindow 构造完成
  → w.show()
```

后端离线时，每个同步请求可能等待很久，因此双击 EXE 后进程存在但没有窗口。

已有差分证据：

- 后端离线：连续 8 秒 `MainWindowHandle == 0`
- 8000 端口有即时响应服务：约 1 秒出现窗口

### 5.2 修复要求

- 主窗口必须先显示，再加载 Dashboard 数据。
- 后端离线时，窗口应在 1–2 秒内出现。
- 初始页面先展示结构、占位状态或离线状态。
- 不允许在主窗口构造函数内发起长时间同步刷新。

### 5.3 推荐最小改法

在 `MainWindow` 初始化时只设置当前页面，不立即调用 `refresh()`；在事件循环开始后使用 `QTimer::singleShot(0, ...)` 或稍后调度第一次刷新。

更稳妥的结构：

```cpp
// 构造阶段：只完成控件创建和页面选择
setCurrentPageWithoutRefresh("dashboard");

// 窗口进入事件循环后再刷新
QTimer::singleShot(0, this, [this]() {
    pollHealth();
    refreshCurrentPage();
});
```

注意：这只是第一轮最小修复。Dashboard 后续应逐步异步加载，不能继续用大量同步请求阻塞 UI。

### 5.4 启动验收

后端未启动时：

- 双击 EXE 后 2 秒内出现窗口。
- 顶部或页面显示“后端离线”。
- 界面可拖动、切换页面、关闭。
- 不出现长时间等待光标。

## 6. 第二阶段：全局应用外壳

### 6.1 侧边栏

将当前 `QTreeWidget` 工程式导航升级为现代工作台导航。

目标结构：

```text
MemoryHub 品牌区

总览
内置终端

记忆
  偏好记忆
  知识记忆
  事实记忆

处理中心
  检索测试
  冲突中心
  遗忘与生命周期

系统
  安全中心
  系统设置

当前用户
后端连接状态
```

实现要求：

- 左侧宽度约 210–220px。
- 顶部增加 MemoryHub Logo 和“智能记忆工作台”。
- 每项使用 16–18px 统一 SVG 图标。
- 选中项使用浅蓝背景和蓝色文字，不使用整块高饱和蓝。
- 分组标题使用弱文字。
- 冲突、安全等入口预留数量徽标；没有真实数据时不要写死数字。
- 用户 ID 与后端连接状态移到侧栏底部。
- 保留现有全部页面可访问性。

如果继续使用 `QTreeWidget` 很难实现目标，可以改为：

- `QScrollArea + QVBoxLayout + QPushButton`
- 每个导航按钮通过属性保存页面 key
- 分组使用 `QLabel`

不必为了保留旧控件而牺牲视觉效果。

### 6.2 顶部栏

顶部栏保留：

- 左侧面包屑
- 右侧全局搜索
- 刷新按钮

移除：

- 顶栏中的用户切换控件
- 顶栏中的后端状态文字和状态点

推荐高度：56–60px。

全局搜索：

- 约 280–320px 宽
- 左侧搜索图标
- 占位文案：“搜索记忆、事实或知识…”
- 可显示 `Ctrl + K` 提示（快捷键可在后续实现）

### 6.3 页面容器

所有页面需要统一内容边距。第一轮不要逐页大改，可在 `MainWindow` 内容区域或 `BasePage` 层提供统一容器策略。

必须避免：

- 页面标题贴边
- 标题、筛选器、表格之间零间距
- Dashboard 有边距而其他页无边距

如果一次统一会破坏现有布局，可先只为 Dashboard 使用新容器，并为后续页面迁移留出公共类。

## 7. 第三阶段：图标系统

### 7.1 要求

- 使用本地内嵌 SVG，随 Qt 资源打包。
- 统一线性图标风格、笔画宽度和 viewBox。
- 图标使用 `currentColor` 或提供可控的着色方案。
- 不依赖 Lucide CDN、浏览器脚本或系统 Emoji。
- Windows 和麒麟离线均能显示。

### 7.2 最低图标集合

```text
logo / brain-circuit
dashboard
terminal
preference / sliders
knowledge / library
fact / nodes
search
conflict
history / lifecycle
shield
settings
refresh
plus
database
activity / health
target
archive
chevron-right
user
```

### 7.3 Qt 接入

- SVG 放入 `desktop-client/resources/icons/`
- 在 `app.qrc` 中注册
- 使用 `QIcon(":/icons/xxx.svg")`
- 需要不同颜色状态时，可通过不同资源或 SVG 渲染/着色工具处理

## 8. 第四阶段：Dashboard 真实落地

### 8.1 页面结构

```text
欢迎/状态页头
├─ 标题：记忆系统状态
├─ 更新时间/后端状态
└─ 检索测试、刷新等操作

四张核心指标卡

主图表区
├─ 左：记忆状态或增长趋势
└─ 右：记忆类型分布环图

底部区
├─ 左：最近活动
└─ 右：待处理事项
```

### 8.2 指标数据原则

高保真 HTML 样板中的以下数据只是视觉示例，不能直接写死到正式客户端：

- 本周新增
- 平均健康度
- 检索命中率
- 7 天增长趋势

第一轮正式 Dashboard 应优先使用现有接口能够可靠提供的数据。

建议四张指标卡：

1. 记忆总数
2. 偏好记忆数
3. 知识记忆数
4. 事实记忆数

风险指标不要与正常指标混为同类，可放入“待处理事项”：

- 待处理冲突
- 抽取死信
- 待审查/低健康度数据（仅在接口可靠时展示）
- 安全复核（仅在接口可靠时展示）

### 8.3 图表策略

当前后端若没有真实时间序列接口，不要伪造“7 天增长趋势”。第一轮可采用：

- 左图：记忆状态分布柱图
- 右图：记忆类型分布环图

如果已有事件接口可以可靠按时间聚合，再实现真实增长趋势。

Qt Charts 视觉优化：

- 去除默认标题和多余外边距
- 背景透明
- 网格线使用弱灰色
- 轴文字使用次级文字色
- 图例统一放在底部或顶部
- 环图中心显示总记忆数
- Preference / Knowledge / Fact 颜色保持稳定映射

### 8.4 最近活动

用时间线式列表替代传统重表格观感：

```text
[图标] 事件标题                     相对时间
       场景、类型或内容摘要
```

要求：

- 最多显示 5–8 条。
- 使用真实事件接口。
- 无数据时显示统一空态。
- 请求失败时显示错误态，不要伪装成空数据。

### 8.5 待处理事项

使用三条紧凑任务卡或列表：

- 冲突中心
- 待审查/死信
- 安全复核或低健康度记忆

每项应支持点击跳转到对应页面。

没有可靠接口时隐藏该项，不写死数字。

### 8.6 Dashboard 状态模型

至少支持：

1. `loading`：卡片显示占位符，图表区显示加载状态。
2. `onlineWithData`：显示真实数据。
3. `onlineEmpty`：显示 0 和引导空态。
4. `offline`：页面框架正常显示，并提供后端离线提示和重试按钮。
5. `partialError`：某个模块失败时只影响该模块，不让整页空白。

## 9. 异步加载建议

### 9.1 最低要求

- Dashboard 不能在 UI 线程中连续执行十几次同步请求。
- 页面切换和窗口拖动不能被网络请求阻塞。
- 后端离线要快速失败并反馈。

### 9.2 推荐实现

扩展 `ApiClient` 的异步能力：

- `getAsync`
- 必要时增加 `postAsync`
- 为每个 Dashboard 模块分别加载
- 使用请求计数或 generation ID，避免页面切换后旧回调污染新状态
- 异步请求增加合理超时

第一轮可以先把 Dashboard 用到的 GET 全部异步化，不必立即改造全项目所有页面。

## 10. 公共组件改造

### 10.1 `PageHeader`

支持：

- 页面标题
- 副标题
- 可选图标
- 右侧主操作和次操作
- 统一底部间距

### 10.2 `StatCard`

支持：

- 标题
- 大数字
- 图标
- 辅助说明
- 可选趋势
- loading 占位状态
- 点击状态

避免 Emoji，改用 `QIcon`。

### 10.3 建议新增的组件

仅在确有复用价值时增加：

- `IconButton`
- `InlineBanner`：离线/错误提示
- `ActivityItem`
- `TaskItem`
- `LoadingPlaceholder`

不要一次创建大量抽象组件。

## 11. QSS 重构策略

当前约有几十处内联 `setStyleSheet()`。本轮不要求一次全部消除，但必须做到：

- 新外壳和 Dashboard 不再大量硬编码内联颜色。
- 通过 `objectName` 或动态属性在 QSS 中统一控制。
- 颜色、字号、边框、圆角集中管理。
- 保留终端等确实需要专用主题的局部样式。

建议 QSS 分段：

```text
基础与字体
应用外壳
侧边栏
顶部栏
页面容器
卡片
按钮
输入控件
指标卡
图表辅助
活动列表
任务列表
状态标签
表格
抽屉与对话框
```

## 12. 高 DPI、窗口尺寸和 UKUI 兼容

### 12.1 Windows 验收尺寸

- 1440 × 900：标准开发尺寸
- 1180 × 720：当前最小尺寸

要求：

- 四张指标卡在最小窗口不重叠。
- 图表标签不截断。
- 侧栏和顶部搜索不挤压面包屑。
- 必要时 Dashboard 使用滚动区域。

### 12.2 UKUI 兼容原则

- 不修改 Qt Widgets 技术路线。
- 字体优先使用系统字体，Windows 回退微软雅黑，麒麟回退 Noto Sans CJK SC。
- 原生对话框、文件选择器等仍交给 Qt/UKUI。
- 品牌色和业务语义色由应用控制。
- 后续再在 openKylin 虚拟机做最终验收。

## 13. Windows 构建与部署命令

在 PowerShell 中执行。

### 13.1 配置与编译

```powershell
$vs = 'D:\software\Microsoft Visual Studio\2022\BuildTools'
$cmake = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

cmd /c "`"$vs\VC\Auxiliary\Build\vcvars64.bat`" && `"$cmake`" -S D:\software\mhub-src -B D:\software\mhub-build -G `"NMake Makefiles`" -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=D:\conda\Library && `"$cmake`" --build D:\software\mhub-build --config Release"
```

### 13.2 部署 Qt 运行库

```powershell
& 'D:\conda\Library\bin\windeployqt.exe' `
  --release `
  --compiler-runtime `
  --no-translations `
  'D:\software\mhub-build\memoryhub-client.exe'
```

### 13.3 运行

```powershell
Start-Process `
  -FilePath 'D:\software\mhub-build\memoryhub-client.exe' `
  -WorkingDirectory 'D:\software\mhub-build'
```

## 14. 验收清单

### 14.1 构建验收

- [ ] CMake 配置成功
- [ ] MSVC 编译成功
- [ ] `memoryhub-client.exe` 生成成功
- [ ] `windeployqt` 成功
- [ ] EXE 无缺失 DLL 或平台插件错误

### 14.2 离线启动验收

- [ ] 8000 端口无后端监听
- [ ] 双击后 2 秒内出现主窗口
- [ ] 窗口可拖动、响应正常
- [ ] Dashboard 显示明确离线状态
- [ ] 点击重试不会冻结整个窗口

### 14.3 视觉验收

- [ ] 侧栏有完整品牌区和 SVG 图标
- [ ] 导航选中态与高保真样板一致
- [ ] 用户与后端状态位于侧栏底部
- [ ] 顶栏简洁，搜索框和刷新入口清晰
- [ ] Dashboard 页面留白统一
- [ ] 指标卡、图表、活动、待办层级明确
- [ ] 不再出现 Emoji 图标
- [ ] 不存在明显空白图标块
- [ ] 1180×720 无重叠或关键内容裁切
- [ ] 1440×900 整体比例自然

### 14.4 功能回归

- [ ] 全部现有导航入口仍可打开
- [ ] 全局搜索仍能跳转检索页面
- [ ] 用户 ID 切换仍能工作
- [ ] 后端状态轮询仍能工作
- [ ] Dashboard 卡片/待办跳转正确
- [ ] 其他页面业务逻辑没有被改坏

## 15. 推荐执行顺序

严格按以下顺序执行，每一步完成后编译验证：

1. 修复窗口显示前的同步刷新阻塞。
2. 新增 SVG 图标资源并验证 Qt 显示。
3. 重构侧边栏。
4. 重构顶部栏与用户/连接状态位置。
5. 整理全局 QSS 与新设计令牌。
6. 改造 `PageHeader` 和 `StatCard`。
7. 重做 Dashboard 静态布局。
8. 接入 Dashboard 真实数据。
9. 将 Dashboard GET 请求异步化。
10. 实现 loading、offline、empty、partial error 状态。
11. 在后端离线模式编译运行验收。
12. 有可用后端时再做在线数据验收。

## 16. 完成交付要求

本轮完成时应向用户交付：

- 修改后的 Qt 源码
- 可直接运行的 `D:\software\mhub-build\memoryhub-client.exe`
- 主要改动说明
- 已完成的验收项
- 尚未接入或因后端缺口被替换的指标说明
- 下一阶段迁移建议：优先偏好记忆页和检索测试页

## 17. 新对话可直接使用的执行指令

将下面这段作为新对话首条任务即可：

```text
请先完整阅读：
D:\Python_Project\XA202612-2\前端重构\Qt前端视觉重构执行方案.md

然后严格按照方案执行“全局应用外壳 + Dashboard 高保真 Qt 落地”。

要求：
1. 先检查 git 状态，保留用户已有改动。
2. 不修改后端、数据库、审计和密钥文件。
3. 首先修复后端离线时 EXE 长时间不显示窗口的问题。
4. 使用本地 SVG 图标，不使用 Emoji 或网络资源。
5. Dashboard 只能展示真实可获取的数据，不能将 HTML 样板数字写死进正式客户端。
6. 每个阶段完成后编译验证。
7. 最终重新生成并启动 D:\software\mhub-build\memoryhub-client.exe 供我验收。
8. 不要只给方案，直接实施、编译、运行并验证。
```

