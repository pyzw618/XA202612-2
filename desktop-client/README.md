# Kylin-MemoryHub 桌面客户端（Qt 5 Widgets）

MemoryHub 后端的可视化控制台，供**人工审计 / 演示 / 调参 / 运维**使用。
目标环境：**银河麒麟 V11 / openKylin 2.x**（UKUI 桌面，Qt 5.15）；开发验证环境：Windows + Qt 5.15。

界面遵循《前端页面规划.md》的 9 大模块与 UKUI 视觉规范（daybreakBlue `#3790FA` 强调色、浅色圆角卡片、8px 网格）。

## 功能总览

| 分组 | 页面 | 后端接口 |
|---|---|---|
| 总览 | Dashboard（统计卡 / 环图 / 柱图 / 事件流 / 系统状态） | `/api/memory/*` |
| 内置终端 | opencode / shell 终端 | QProcess |
| 记忆管理 | 偏好 / 知识 / 事实（列表·筛选·详情抽屉·版本链·批量删除·事实提案裁决） | `/api/memory/preferences|knowledge|facts` |
| 检索与冲突 | 检索测试（混合检索 + 上下文预览）、冲突中心（新旧对比 + 裁决） | `/search` `/context` `/conflicts` |
| 遗忘与生命周期 | 精准遗忘（NL/范围/ID 预览）、待审查队列、归档仓库、回收站、健康度看板、遗忘历史、遗忘设置 | `/forget*` `/memories/*` `/lifecycle/*` |
| 安全中心 | 安全总览、用户规则 CRUD（密文）、审计日志（验链）、隔离区 | `/safety/*` |
| 系统设置 | 后端状态、参数查看、演示数据工具 | `/system/*` `/agent/*` |

## 环境要求

- **Qt 5.9+**（推荐 5.15，麒麟源内置；需要 `Widgets / Network / Charts` 模块）
- **CMake 3.16+**
- C++17 编译器（Linux: g++；Windows: MSVC 或 MinGW）

## 构建

### Linux（银河麒麟 / openKylin）

```bash
# 安装依赖（麒麟源）
sudo apt install qtbase5-dev qtbase5-dev-tools libqt5charts5-dev \
                 qt5-ukui-platformtheme build-essential cmake

# 构建
bash build-linux.sh          # 等价于：
# cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
# cmake --build build -j$(nproc)

# 运行
./build/memoryhub-client
```

### Windows（开发验证）

```bash
# 1) 安装 Qt 5.15 msvc2019_64 到 C:\Qt\5.15.2（aqtinstall）
# 2) 由于中文路径会破坏 MSVC 的 PDB/moc，需要创建 ASCII junction：
powershell -Command "New-Item -ItemType Junction -Path 'C:\mhub-src' -Target '绝对路径\desktop-client' -Force"
# 3) 构建（脚本内部自动调用 vcvars64 + cmake）
powershell -ExecutionPolicy Bypass -File build-win.ps1
# 产物：C:\mhub-build\memoryhub-client.exe
```

## 使用

1. 先启动后端（仓库根目录）：`python -m uvicorn memoryhub.app:app --host 0.0.0.0 --port 8000`
2. 启动客户端，顶栏绿色圆点表示后端已连接。
3. 顶栏可切换 `user_id`（默认 `default`），切换后各页自动刷新。
4. 顶栏全局搜索框输入查询回车 → 跳转检索测试页并自动执行。

## 架构说明

```
src/
├── main.cpp            # 入口（高 DPI、加载 QSS）
├── AppContext.h/.cpp   # 全局上下文：ApiClient 单例 + user_id + baseUrl + 页面导航回调
├── api/
│   ├── ApiClient.h/.cpp  # 同步/异步 HTTP 封装（超时、等待光标、X-MemoryHub-User 头）
│   └── Json.h/.cpp       # QJson 便捷访问工具（读字段/格式化/相对时间）
├── widgets/            # 复用组件：PageHeader/StatCard/ScoreRing/StatusTag/
│                       #   JsonViewer/EmptyState/DetailDrawer/MemoryFilterBar/ConfirmDialog
├── pages/              # 21 个页面（BasePage 基类提供 refresh/applySearchQuery）
└── MainWindow.h/.cpp   # 侧边栏导航 + 顶栏（面包屑/搜索/状态灯/用户切换）+ 内容栈
```

### 关键设计

- **同步请求 + 等待光标**：`ApiClient` 内部用 `QEventLoop` 等待（超时 20s），页面代码线性可读；
  健康轮询用异步回调不阻塞 UI。
- **JSON 直用**：页面直接操作 `QJsonObject`，配合 `j::` 工具函数，避免为动态 payload 写大量结构体。
- **安全门禁感知**：写操作返回 `memory.safety.review_required` / `rejected` 时给出中文提示与 audit_id。
- **用户规则接口**自动带 `X-MemoryHub-User` 请求头。
- **细节抽屉**统一用 `DetailDrawer`，危险操作统一 `ConfirmDialog`（可要求输入确认文本）。

## 备注

- **知识列表接口限制**：后端 `GET /knowledge` 仅支持 scene / knowledge_type 过滤，**不支持按 status 过滤**
  （始终返回 active）。因此知识记忆的非 active 状态不会出现在"待审查/归档/回收站"列表里；
  但状态流转操作（PATCH status）对知识记忆仍然生效。如需完整支持，需后端为 knowledge 增加
  `status` 参数（见后端 `api.py:list_knowledge`）。
- 审计日志 / 隔离区需 `config.yaml` 中 `safety.audit.enabled` / `safety.quarantine.enabled` 为 `true`，
  否则页面显示"待开启"提示（后端返回 `safety.audit_disabled` / `safety.quarantine_disabled`）。
- 遗忘设置页的权重 / 阈值为**代码常量**（只读展示）；自动遗忘扫描与生命周期检查可手动触发。
- 内置终端通过 QProcess 启动所选命令；使用 `opencode` 需先在目标机安装。
