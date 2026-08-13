# MemoryHub Qt 前端第二轮改进执行方案

> 适用项目：`D:\Python_Project\XA202612-2`
>
> 前端目录：`desktop-client`
>
> 已验证构建目录：`D:\software\mhub-build`
>
> 已验证源码映射：`D:\software\mhub-src` 是 `desktop-client` 的 Junction
>
> 文档用途：直接交给一个新的 Codex 会话，按阶段修改、构建、启动和验收。

## 1. 当前基线

当前工作区已经进行过第一轮视觉重构，相关修改尚未提交。执行者必须保留现有改动，不得回退、覆盖或重建前端目录。

已经完成：

- Qt 5 Widgets 技术路线保持不变。
- 新的应用外壳、品牌区、侧边栏、顶栏和用户区已经落地。
- 导航项已切换为统一 SVG 图标。
- Dashboard 已改为卡片、图表、最近活动和待办布局。
- Dashboard 的 GET 请求已采用异步请求和 generation ID。
- Dashboard 已有滚动区域、加载占位、离线横幅和局部成功汇总。
- 偏好、知识、事实页面已经使用圆角内容容器。
- 当前源码能够用 MSVC + Qt 5 成功编译。
- 当前 EXE 在测试环境约 1.6 秒创建主窗口，满足 2 秒内显示窗口的要求。

已验证构建命令所需工具：

```text
MSVC vcvars64:
D:\software\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat

CMake:
D:\software\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe

Qt5_DIR:
D:\conda\Library\lib\cmake\Qt5
```

注意：

- `/api/health` 返回 `{"status":"ok", ...}`；`MainWindow::pollHealth()` 判断 `status == "ok"` 是正确的，不要修改为 `healthy`。
- `/api/memory/health` 是另一个接口，返回值可能是 `healthy`。不要混淆两个接口。
- 第一轮视觉方案仍是视觉规范来源：`前端重构/Qt前端视觉重构执行方案.md`。

## 2. 第二轮目标

第二轮按以下顺序推进：

1. 修复会导致真实数据错误、界面冻结或重复提交的问题。
2. 建立可复用的异步请求和页面状态模型。
3. 完成 Dashboard 的信息表达和响应式布局。
4. 统一列表页的加载、空、错误、筛选和详情体验。
5. 完成键盘操作、辅助功能和 QSS 收口。
6. 全量构建、离线启动、在线功能和不同窗口尺寸验收。

最终效果应是：

- 后端在线时显示真实数据。
- 后端离线时任何页面都不会长时间冻结。
- 用户能明确区分加载、空数据、失败和离线。
- 危险写操作不会因重复点击而提交多次。
- 1180×720 和 1440×900 下布局均可用。
- 鼠标和键盘都能完成主要导航和操作。
- 新增界面样式统一由 QSS 管理。

## 3. 范围边界

### 3.1 本轮允许修改

- `desktop-client/src/api/ApiClient.*`
- `desktop-client/src/MainWindow.*`
- `desktop-client/src/pages/*`
- `desktop-client/src/widgets/*`
- `desktop-client/resources/style/kylin.qss`
- `desktop-client/resources/icons/*`
- `desktop-client/resources/app.qrc`
- `desktop-client/CMakeLists.txt`
- `desktop-client/README.md`
- 为 Qt 前端增加必要的自动化测试文件和测试目标

如果确认前端需求被后端契约阻塞，可以对后端做最小兼容性修复，但必须：

- 先证明现有接口无法满足需求；
- 不改变已有接口的默认返回结构；
- 补测试；
- 在交付说明中单列后端修改。

### 3.2 本轮禁止事项

- 不回退当前工作区已有修改。
- 不执行 `git reset --hard`、`git checkout --` 或清理未跟踪文件。
- 不把 Qt Widgets 重写为 QML、Web、PyQt 或其他技术栈。
- 不为了美观伪造统计数据、趋势或待办数量。
- 不大改后端领域逻辑、数据库模型和安全规则。
- 不一次性建立复杂的通用框架或过深继承体系。
- 不用同步等待包装异步接口；最终不能通过嵌套 `QEventLoop` 阻塞 GUI。
- 不以等待光标代替加载状态。
- 不新增 Emoji 作为正式界面图标。

## 4. 第一阶段：正确性与防冻结

本阶段完成前，不开始大规模视觉精修。

### 4.1 修复顶层 JSON 数组成功却被判失败

位置：

- `desktop-client/src/api/ApiClient.cpp`
- `ApiClient::parseReply()`

当前问题：

```cpp
if (!doc.isObject()) return r;
...
r.ok = (code >= 200 && code < 300);
```

当 HTTP 200 响应是顶层数组时，函数提前返回，`r.ok` 保持 `false`。这会直接影响偏好、知识、事实、冲突、死信和版本链等列表接口。

修复要求：

- 先记录 HTTP 状态并设置 `ok`，不能由 JSON 根类型决定成功状态。
- object 和 array 都要保留在 `Result::doc` 中。
- 204 或合法空响应不能被误判为网络错误。
- JSON 解析失败但 HTTP 为错误响应时，应保留可诊断信息。
- FastAPI `detail` 为字符串或对象时继续提取错误码与错误消息。
- 不允许数组分支提前跳过 HTTP 状态设置。

至少增加以下测试：

1. `200 + JSON object`：`ok == true`、`hasJsonObject() == true`。
2. `200 + JSON array`：`ok == true`、`hasJsonArray() == true`。
3. `204 + empty body`：`ok == true`。
4. `400 + detail string`：`ok == false`，错误消息存在。
5. `409 + detail object`：错误码和错误消息正确。
6. 连接失败/超时：`networkError == true`。

### 4.2 扩展 ApiClient 的真正异步能力

当前只有 `getAsync()`，其余页面仍大量调用同步 `get/post/patch/del`。

建议新增统一异步入口：

```cpp
using Callback = std::function<void(const Result &)>;

QNetworkReply *getAsync(...);
QNetworkReply *postAsync(...);
QNetworkReply *patchAsync(...);
QNetworkReply *deleteAsync(...);
```

也可以实现一个内部 `sendAsync()`，公开方法只负责构造 method/body。

要求：

- GET、POST、PATCH、DELETE 共用请求构造、header、解析和超时逻辑。
- 所有异步请求有明确超时，建议普通读取 6–10 秒，长任务按接口单独配置。
- 超时后 abort，回调只执行一次。
- 返回 `QNetworkReply*` 或请求句柄，页面销毁/刷新时可取消旧请求。
- 回调接收方销毁后不得访问悬空 `this`；使用 QObject context、`QPointer` 或连接生命周期保证安全。
- 同一个页面连续刷新时旧响应不得覆盖新状态。
- 写请求必须支持按钮禁用、完成后恢复和防重复提交。
- 不在异步回调中再进入嵌套事件循环。

旧同步接口可以临时保留，供尚未迁移的页面使用，但应标记为待移除；本轮结束时用户可触发的主要页面不得再因网络请求阻塞 GUI。

### 4.3 页面迁移顺序

按风险和使用频率分批迁移：

第一批：

1. `PreferencePage`
2. `KnowledgePage`
3. `FactPage`
4. `SearchPage`
5. `ConflictPage`

第二批：

1. `ForgetPrecisePage`
2. `ForgetPendingPage`
3. `ForgetArchivedPage`
4. `ForgetRecyclePage`
5. `ForgetHealthPage`
6. `ForgetHistoryPage`
7. `ForgetSettingsPage`

第三批：

1. Safety 全部页面
2. Settings 全部页面

迁移每个页面时必须同时实现：

- 加载态；
- 成功有数据；
- 成功空数据；
- 请求失败；
- 用户点击重试；
- 页面销毁/再次刷新时旧请求不污染新状态；
- 写操作防重复提交。

### 4.4 优先处理精准遗忘页

`ForgetPrecisePage::refresh()` 当前顺序请求偏好、知识和事实，离线时可能产生最长累计阻塞。

改造要求：

- 三个 GET 并行执行。
- 页面立即显示框架和“正在读取可选记忆”。
- 分类型独立记录成功或失败。
- 三类全部结束后再汇总 ID 列表。
- 部分成功时保留成功类型，同时明确显示缺失类型。
- 执行遗忘时禁用执行按钮，完成或失败后恢复。
- 预览响应和正式执行响应使用不同 generation/request token。

### 4.5 修复列表页错误态

当前偏好、知识、事实页面在失败后清空表格，看起来像“没有数据”。

统一要求：

- 请求开始时保留旧数据，可增加半透明加载提示或顶部进度条。
- 首次加载无数据时显示骨架屏。
- HTTP 成功且数组为空才进入 empty。
- 请求失败进入 error，显示简短原因和重试按钮。
- 刷新失败时优先保留旧数据，并提示“刷新失败，当前显示上次数据”。
- 不把 JSON 类型错误当成正常空数组。

## 5. 第二阶段：通用页面状态组件

不要每个页面重复手写状态标签。新增一个轻量组件即可，例如：

```text
widgets/PageStateView.h/.cpp
```

建议支持：

```cpp
enum class PageState {
    Loading,
    Content,
    Empty,
    Error,
    Offline
};
```

组件能力：

- 图标；
- 标题；
- 说明；
- 可选主按钮，如“重试”“新增记忆”“启动后端”；
- `setState()` 或明确的 `showLoading/showEmpty/showError`；
- 支持放在表格、图表或整页区域中；
- 键盘可聚焦主操作；
- 文案和颜色由 QSS 控制。

限制：

- 不制作复杂状态机框架。
- 不把所有页面强制塞进同一个继承基类。
- 终端等特殊页面可以不用该组件。

建议首先接入：

- Preference / Knowledge / Fact 表格区；
- Dashboard 活动区、图表区和指标卡；
- Safety audit / quarantine；
- Forget 列表页。

## 6. 第三阶段：Dashboard V2

### 6.1 保留真实数据原则

四张指标卡继续使用真实接口：

1. 记忆总数
2. 偏好记忆数
3. 知识记忆数
4. 事实记忆数

不得写死：

- 本周新增；
- 7 天增长；
- 检索命中率；
- 平均健康度；
- 任意演示数字。

### 6.2 修复 Dashboard 模块级状态

每个数据模块独立记录：

- loading
- value/data
- empty
- error

要求：

- 单个记忆接口失败只影响对应指标卡及依赖它的图表。
- 卡片不能永久停在 `—` 而没有解释。
- 失败卡显示小型错误标记和“重试”或 tooltip。
- 成功空数据显示 `0`，不能显示 `—`。
- 整页横幅只负责汇总 offline/partial，不替代局部状态。
- 刷新按钮在请求进行时应防止无限叠加请求，可取消旧请求或只接受最新 generation。

### 6.3 重新定义两张图表

当前柱图和环图都表达偏好/知识/事实数量，信息重复。

目标：

- 右图保留“记忆类型分布”环图：偏好、知识、事实。
- 环图中心显示总记忆数和“总记忆”文字。
- 左图只有在能通过真实接口获得 active/pending/archived/deleted 等状态数量时，才展示“记忆状态分布”。

如果现有接口无法一次可靠获得状态分布：

- 不伪造；
- 可以暂时将左图改为三类记忆数量的横向条形图，但必须将标题改为“各类记忆数量”，明确它与右图一个强调绝对数量、一个强调占比；
- 或用真实健康度/事件统计替代，但必须先确认接口契约和测试。

图表要求：

- 偏好固定蓝色 `#4B7FE0`；
- 知识固定紫色 `#7F6BDC`；
- 事实固定青色 `#39A6AF`；
- 轴文字使用次级文字色；
- 网格线弱化；
- 空图和错误图使用布局内 overlay，不使用固定 `setGeometry(0, 0, 260, 180)`；
- 高 DPI 和缩放时覆盖层始终居中。

### 6.4 最近活动改为轻量时间线

将当前三列 `QTableWidget` 改成 5–8 条活动项：

```text
[图标] 事件标题                     相对时间
       场景 · 类型 · 内容摘要
```

要求：

- 使用 `/api/memory/events` 的真实数据。
- 根据事件类型使用统一 SVG 图标或中性 activity 图标。
- 相对时间旁提供绝对时间 tooltip。
- 长摘要省略，tooltip 显示完整内容。
- 无数据显示统一 Empty 状态。
- 失败显示 Error 状态，不伪装为空。
- 如果事件无法定位详情，整项不要伪装成可点击。

可以新增 `ActivityItem`，但只在 Dashboard 或其他页面确有复用时使用。

### 6.5 待办事项修正

当前“抽取死信”错误跳转到遗忘待审查队列。

处理方案优先级：

1. 若本轮新增轻量“抽取任务”页面，则跳转到该页，并支持查看错误、retry、run。
2. 若不新增页面，则死信项只展示数量和解释，不设置错误跳转。
3. 绝不能继续跳到业务无关的遗忘待审查页。

待办项仅在有可靠接口时显示：

- 待处理冲突；
- 抽取死信；
- 安全复核；
- 低健康度记忆。

数量为 0 时弱化显示；接口不可用时显示局部错误或隐藏，不写死数字。

### 6.6 Dashboard 响应式布局

当前最小窗口为 1180×720，侧栏占用约 224px。Dashboard 内容宽度不足时不能坚持固定四列。

建议断点策略：

- 内容区宽度充足：指标 4×1，图表 3:2，底部 3:2。
- 内容区较窄：指标 2×2。
- 更窄时：两张图上下排列，活动和待办上下排列。

Qt Widgets 可在 `resizeEvent()` 中按内容宽度重排 `QGridLayout`；避免反复销毁控件，只重新放置已有控件。

验收要求：

- 1180×720 无卡片重叠和横向裁切。
- 1440×900 保持自然比例。
- 图表标签、环图中心和空态不偏移。
- 页面垂直滚动正常。

## 7. 第四阶段：列表页和功能补齐

### 7.1 统一列表页结构

Preference、Knowledge、Fact、Safety、Forget 列表页统一为：

```text
页面标题 / 副标题 / 主操作
筛选栏
结果数量 / 已选数量 / 批量操作
表格或列表
分页（接口支持时）
右侧详情抽屉
```

视觉要求：

- 标题到筛选栏 16–20px。
- 筛选栏到内容区 12–16px。
- 行 hover、选中和 focus 状态可区分。
- 长文本省略并提供 tooltip。
- 危险操作默认克制，hover 或确认阶段再强化红色。
- 批量操作只在存在选中项时突出显示。
- 表格空、错、加载统一使用 `PageStateView`。

### 7.2 修正“全部状态”语义

偏好和知识页目前将空状态转换为 `active`，但下拉文案为“全部状态”。

执行者先检查后端接口是否支持真正的全状态查询：

- 如果支持，传递能表达全部状态的参数并补接口测试。
- 如果默认空值仍代表 active，则前端将选项改名为“有效”，不要伪装为全部。
- 如果需要前端聚合多状态请求，必须异步并行并正确合并/去重，不得重新引入阻塞。

Fact 页当前没有“全部状态”项，如要增加也遵守同一原则。

### 7.3 Knowledge 页面

补齐：

- 场景筛选；
- 场景列或在名称下显示场景辅助文字；
- 与类型、状态、搜索组合过滤；
- 错误态和刷新失败保留旧数据；
- 详情中的工作流/案例/模板内容层级统一。

### 7.4 Fact 页面

补齐：

- 详情抽屉中的关联冲突区域；
- 证据、版本/演化和冲突的清晰分组；
- 候选裁决期间禁用重复提交；
- 三元组长文本的换行和 tooltip；
- 置信度颜色改为动态属性，不在代码里拼接颜色样式。

### 7.5 Search 页面

补齐：

- 搜索请求异步化；
- 搜索按钮 loading 和防重复提交；
- 结果卡左侧使用稳定类型色条；
- 显示标题、摘要、场景、类型、分数；
- 展开后显示完整 metadata 和原始字段；
- 缓存命中只有接口真实返回时才显示，不固定写 `—`；
- 上下文预览作为独立异步模块，失败不清空搜索结果；
- 支持 Enter 搜索和 Esc 收起详情。

### 7.6 Conflict 页面

在保留现有业务能力前提下改善对比：

- 旧内容和新内容使用结构化区域；
- 能可靠分词时增加词级 diff；否则使用行级或整段差异，不做错误高亮；
- 删除内容浅红、增加内容浅绿或浅蓝；
- 相同内容弱化；
- 裁决按钮集中放置；
- 提交时禁用全部裁决按钮；
- 失败后保留当前冲突内容和用户输入原因。

### 7.7 Safety Audit 页面

补齐：

- 使用后端 `limit/offset` 实现分页；
- 详情抽屉；
- `showRecord()` 不得保持空实现；
- 哈希链验证结果使用 SVG + 文本，不使用 ✅/❌；
- 功能未开启状态使用统一 warning banner；
- 搜索/过滤防抖，不能每输入一个字符就同步发请求。

### 7.8 抽取任务页的范围判断

项目已有抽取任务接口时，可以新增一个最小页面：

- 状态筛选；
- 任务列表；
- 错误码/最近错误；
- retry 单条任务；
- run 扫描；
- dead letter 计数。

如果新增页面会显著扩大本轮范围，则不要半做。此时只修正 Dashboard 的错误跳转，并在交付说明中列为下一阶段任务。

## 8. 第五阶段：可访问性和键盘操作

### 8.1 主导航

移除 `m_nav->setFocusPolicy(Qt::NoFocus)`，恢复键盘焦点。

要求：

- Tab 能进入导航；
- 上下键移动；
- Enter/Space 打开叶子页面；
- 分组标题不可被误当作页面；
- focus 状态在 QSS 中清晰可见；
- 不影响现有鼠标选择和选中样式。

### 8.2 可点击卡片

`StatCard` 和 Dashboard 待办目前主要依赖鼠标事件。

建议：

- 将真正可点击的卡片改为 `QAbstractButton` 派生控件，或实现 StrongFocus、keyPressEvent 和 accessible role。
- Enter/Space 与鼠标点击产生相同信号。
- pressed、hover、focus 三种状态分别可见。
- 不可点击的总数卡不要设置手型光标或按钮角色；如果总数卡有明确目标页再设为可点击。

### 8.3 辅助信息

至少为以下内容设置 accessible name/description：

- 全局搜索；
- 刷新按钮；
- 用户切换；
- 后端状态；
- 纯图标按钮；
- 可点击指标卡；
- 图表摘要；
- 危险操作确认输入框。

新增快捷键：

- `Ctrl+K`：聚焦全局搜索；
- `Ctrl+R` 或 F5：刷新当前页；
- Esc：关闭详情抽屉/取消轻量弹层（不能绕过危险确认）。

## 9. 第六阶段：QSS 和视觉收口

当前约有几十处内联 `setStyleSheet()`。本轮不要求机械清零，但业务页面的语义颜色应集中管理。

### 9.1 动态属性

建议统一使用：

```text
tone = primary / success / warning / danger / muted
state = loading / empty / error / offline
kind = preference / knowledge / fact
interactive = true / false
```

将以下硬编码迁移到 QSS：

- Conflict 页红绿对比；
- Fact 置信度颜色；
- Safety warning/error；
- 删除按钮；
- 状态文本；
- StatCard 趋势色。

允许保留局部样式：

- Terminal 深色终端主题；
- JSON/代码查看器等确实需要等宽字体和专用背景的控件。

### 9.2 移除正式界面 Emoji

搜索以下字符并替换：

```text
🔒 🔍 ⚠ ✅ ❌ ＋
```

说明：

- `＋` 若只是按钮文本中的全角加号，也建议使用 `plus.svg`，但不是阻断项。
- 警告、成功、失败必须同时有文字，不得只剩颜色或图标。
- SVG 缺失时新增统一线性图标，并加入 `app.qrc`。

### 9.3 字体和对比度

- Linux/UKUI 优先系统字体或 `Noto Sans CJK SC`，Windows 回退微软雅黑。
- 避免强行让所有平台首先使用 `Microsoft YaHei UI`。
- 12px 辅助文字 `#8B93A2` 在白底上偏淡，适当提升到更深的灰色，尤其是表格、说明和时间。
- 焦点边框不能只依赖极淡颜色。
- 红、绿状态必须有文本标签。

### 9.4 顶栏与侧栏尺寸

- 侧栏当前 224px 可保留，不需要为了满足建议值机械改成 220px；重点是内容完整和比例自然。
- 顶栏建议实际高度 56–60px，但先以 1180×720 不拥挤为准。
- 全局搜索从固定 320px 改为合理的最小/最大宽度或随窗口弹性调整。
- 长面包屑要省略或 tooltip，不能挤掉搜索和刷新。

## 10. 代码结构治理

本轮只做能直接降低重复和缺陷风险的拆分。

优先抽取：

1. 统一异步请求实现。
2. `PageStateView`。
3. 共用的 Result 到页面状态转换辅助。
4. 重复列表操作中的小型工具函数或 model。

可以拆分超大文件：

- `ForgetPages.cpp` 可按页面拆为多个 `.cpp`，头文件保持兼容或同步拆分。
- `SafetyPages.cpp` 可按 Overview/UserRules/Audit/Quarantine 拆分。

不要做：

- 为每种记忆建立多层抽象工厂；
- 把所有页面塞入一个万能基类；
- 在没有第二个使用点时建立复杂组件系统；
- 顺手重写无关后端模块。

清理明确的无效成员或声明：

- 未实现且未使用的 `MainWindow::buildTopBar()` 声明；
- 仅赋值但无消费的状态字段应删除或真正用于 UI；
- `AppContext` 生命周期应由 QApplication 或 RAII 托管，关闭窗口后不保留捕获悬空 MainWindow 的导航回调。

## 11. 测试与验收

### 11.1 构建命令

PowerShell 中执行：

```powershell
$buildLine = 'call "D:\software\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" && "D:\software\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build D:\software\mhub-build --config Release'
cmd.exe /d /s /c $buildLine
```

构建成功标志：

```text
[100%] Built target memoryhub-client
```

产物：

```text
D:\software\mhub-build\memoryhub-client.exe
```

### 11.2 静态检查

```powershell
git diff --check -- desktop-client
rg -n "QEventLoop|sendSync|setStyleSheet|setFocusPolicy\(Qt::NoFocus\)|🔒|🔍|✅|❌" desktop-client/src
```

验收解释：

- `git diff --check` 必须无错误。
- `QEventLoop/sendSync` 如果仍存在，必须证明用户可触发的主流程已经不调用它。
- 内联样式只允许保留已说明的特殊控件。
- 主导航不得再是 `NoFocus`。
- 正式 UI 不应残留 Emoji。

### 11.3 离线启动

确保 8000 端口没有后端监听，然后启动 EXE。

必须满足：

- 2 秒左右出现窗口，最大不超过 2 秒目标值；若机器负载导致偶发超限，应记录多次测量。
- 主窗口可拖动、缩放和切换页面。
- Dashboard 明确显示离线或模块错误。
- 进入偏好、知识、事实、搜索、精准遗忘、安全和设置页面不会冻结 20–60 秒。
- 点击刷新或重试不会叠加大量重复请求。
- 窗口能够正常关闭。

### 11.4 在线功能回归

启动后端后验证：

- `/api/health` 正确显示“后端已连接”。
- Dashboard 数字与接口返回一致。
- 顶层数组响应被判定为成功。
- 最近活动、冲突和死信不被伪装成空数据。
- 用户切换后只显示新用户的数据，旧异步回调不会覆盖新数据。
- 全局搜索跳转和搜索执行正常。
- 偏好、知识、事实 CRUD 正常。
- 精准遗忘预览和执行正常，按钮防重复提交。
- 冲突裁决正常。
- Safety Audit 分页和详情正常。
- 所有失败都能显示可理解的错误并重试。

### 11.5 窗口尺寸

至少检查：

- 1180×720
- 1440×900
- Windows 125% 缩放（环境允许时）

检查项：

- Dashboard 四卡自动 4×1 或 2×2，无重叠。
- 图表不裁切，空态居中。
- 活动和待办在窄宽度下能上下排列。
- 顶栏搜索不遮挡面包屑和刷新。
- 列表筛选栏不挤出窗口；必要时换行或横向滚动。
- 详情抽屉不把主表压缩到不可用。

### 11.6 键盘验收

- Tab 可遍历主导航、搜索、刷新、页面主操作和表格。
- 上下键可以移动导航选择。
- Enter/Space 可激活导航和可点击卡片。
- `Ctrl+K` 聚焦搜索。
- F5 或 `Ctrl+R` 刷新当前页。
- Esc 关闭详情抽屉。
- focus 状态始终可见。

## 12. 推荐提交拆分

如果执行者需要提交代码，建议拆成：

1. `fix(frontend): correct API result parsing`
2. `refactor(frontend): add cancellable async requests`
3. `fix(frontend): add reliable page loading and error states`
4. `feat(frontend): refine dashboard data states and layout`
5. `feat(frontend): improve memory list interactions`
6. `feat(frontend): add keyboard and accessibility support`
7. `style(frontend): consolidate semantic QSS styles`

每个提交都应能编译。不要把全部改动压成一个无法定位回归的大提交。

## 13. 完成交付要求

最终回复必须说明：

- 修改了哪些文件；
- 修复了哪些确定缺陷；
- 哪些页面已完成异步化；
- 哪些视觉和可访问性改进已落地；
- 实际运行过哪些构建、测试和启动检查；
- 1180×720、1440×900 的检查结果；
- 仍未完成或受后端契约限制的项目；
- 没有把哪些规划项纳入本轮，以及原因。

不得只回复“已优化”“已美化”或“构建通过”。

## 14. 新会话直接执行指令

将下面内容连同本文件路径发给新会话：

```text
请严格按照《前端重构/Qt前端第二轮改进执行方案.md》实施当前项目的 Qt 前端第二轮改进。

要求：
1. 先完整阅读方案、现有第一轮视觉方案、desktop-client/README.md 和当前 git diff。
2. 当前工作区已有未提交的前端重构，必须保留并在其上继续修改，禁止回退或覆盖用户改动。
3. 按方案阶段执行：先修 ApiClient 数组解析和 GUI 阻塞，再做页面状态、Dashboard、列表页、可访问性与 QSS。
4. 每完成一个阶段都进行相关测试，并使用 D:\software\mhub-build 全量编译。
5. 使用已验证的 D:\software MSVC/CMake 和 D:\conda Qt 工具链；不要使用旧文档里的 C:\ 路径。
6. 不伪造业务数据，不扩大到无关后端重构，不使用 Emoji 代替正式图标。
7. 完成后执行离线启动、在线功能、1180×720、1440×900 和键盘操作验收。
8. 持续推进到方案中所有可执行项目完成；若某项被真实接口契约阻塞，提供证据并采用最小安全降级，不要猜测实现。
9. 最终给出文件级改动摘要、测试证据、剩余限制和后续建议。
```

