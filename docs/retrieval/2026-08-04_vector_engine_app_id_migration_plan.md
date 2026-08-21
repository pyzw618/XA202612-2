# 向量引擎 C API `app_id` 迁移实施方案

> 状态：已完成（阶段 5 文档与回归已交付；阶段 4 真实 SDK 构建/烟测受外部环境与 app_id 未提供阻塞）  
> 日期：2026-08-04  
> 适用范围：`libkysdk-vector-engine-client` 的 C API 桥接层、MemoryHub Python 调用层、配置、mock、测试与交接文档。  
> 执行方式：**一个新的 Codex 会话只执行一个阶段**；该阶段完成、验证并提交交接记录后，再开启下一会话。

## 1. 问题与目标

当前桥接代码调用的是旧 SDK 接口：

```cpp
VectorDB::ConnectParam(host, port)
```

仓库内当前 SDK 实际只支持：

```cpp
VectorDB::ConnectParam(std::string appId);
VectorDB::ConnectParam(std::string appId, const std::string& host, uint16_t port);
```

`app_id` 为空时，SDK 在连接阶段返回 `APPID_EMPTY`；成功连接后，SDK 会在每个 gRPC 调用上附带 `app_id` 元数据。因此这是 SDK 接口升级造成的确定性编译故障，而不是性能问题。

本迁移的目标是：

1. 真实 C++ SDK 能以当前仓库源码编译通过；
2. `app_id` 从应用配置显式传入，禁止 C++ 桥接层或 Python 层私自硬编码；
3. 真实库、Python ctypes、mock 库和验证脚本保持同一个 C ABI；
4. 空、缺失或不合法的 `app_id` 在应用启动/初始化前失败，而不是进入性能测试后才失败；
5. 保留可重复的 mock 回归测试，并新增真实 SDK 的构建/烟测交接步骤。

## 2. 已确认的事实

| 位置 | 当前状态 | 风险 |
|---|---|---|
| `third_party/.../capi/c_api_bridge.cpp` | 旧三参数连接形式内调用旧的二参 `ConnectParam` | 与当前 SDK 不匹配，C++ 编译失败 |
| `include/.../types/ConnectParam.h` | 构造函数要求首参 `appId` | `app_id` 无法省略 |
| `src/impl/MilvusConnection.cpp` | 空 `AppId()` 返回 `APPID_EMPTY` | 即使绕过编译，空值也无法连接 |
| `src/impl/MilvusConnection.h` | 向 gRPC metadata 写入 `app_id` | 服务端可鉴权、审计、流控或隔离 |
| `memoryhub/storage/vector_engine/_milvus_ctypes.py` | ctypes 仍使用三参数 C ABI | 必须同步变更 |
| `memoryhub/config.py` / `config.example.yaml` | `VectorEngineConfig` 没有 `app_id` | 没有可信配置来源 |
| `third_party/kylin-mock/*` | mock 和验证脚本仍使用三参数 C ABI | 现有测试不能发现真实 ABI 漂移 |
| `docs/retrieval/*` | 多份文档仍描述旧接口 | 会误导后续集成 |

## 3. 目标 ABI 与配置契约

### 3.1 C ABI（迁移后的唯一接口）

```c
int vector_engine_connect(
    vector_engine_t engine,
    const char* app_id,
    const char* host,
    int port
);
```

设计选择：将 `app_id` 放在 `host` 前，和 SDK 的构造函数顺序一致。此变更是 ABI 破坏性变更；本仓库未发布稳定的外部 C API 版本，且所有已知调用方均在仓库内，因此不维护旧三参数符号。

### 3.2 Python 配置契约

```yaml
vector_engine:
  app_id: "<由测试/部署平台提供的非空应用标识>"
  host: "127.0.0.1"
  port: 19530
```

新增字段：

```python
VectorEngineConfig.app_id: str
```

规则：

- 对 `provider == "milvus"`：`app_id` 必须是非空字符串；
- 对 `provider == "milvus_mock"`：测试也必须传入非空值，以验证调用链完整性；mock 不把其用于鉴权；
- 对 `provider == "faiss"`：不消费此字段；
- 不将 `app_id` 写入日志、错误消息、指标 tag 或测试输出；
- 不推断默认值，不使用 collection、用户 ID、包名替代。实际值必须由测试/部署平台确认。

> 注意：只有“字段形态”可先实现；具体 `app_id` 值属于部署输入。若测试方尚未提供，代码应以明确的配置错误停止，而不可临时写成 `memoryhub` 或 `test`。

## 4. 阶段总览

| 阶段 | 会话目标 | 可提交 | 前置条件 |
|---|---|---|---|
| 0 | 确认外部契约和实际 `app_id` | 是（仅记录） | 无 |
| 1 | 锁定新 ABI 的回归测试与配置校验 | 是 | 阶段 0 |
| 2 | 迁移配置与 Python 调用链 | 是 | 阶段 1 |
| 3 | 迁移 C++ 桥接与 mock ABI | 是 | 阶段 2 |
| 4 | 真实 SDK 构建、动态链接与连接烟测 | 否，除非仅补脚本/文档 | 阶段 3、测试环境 |
| 5 | 更新文档、全量回归、交付验收 | 是 | 阶段 4 |

每一阶段必须在独立工作树或干净基线上执行。若工作树含无关改动，不覆盖、不暂存、不重置它们。

---

## 阶段 0：确认外部接口契约（不写业务代码）

### 目标

向测试/部署平台确认 `app_id` 的真实取值与约束，避免把身份标识猜测为固定字符串。

### 必须向测试方确认

1. 性能测试使用的准确 `app_id`；
2. 是否按环境区分（例如测试/预发/生产不同值）；
3. 允许字符集、最大长度、是否区分大小写；
4. `app_id` 是否仅作 metadata，还是服务端鉴权/白名单的必填值；
5. 真实 SDK 的版本、头文件来源、构建命令和动态库依赖；
6. 性能环境可执行的最小连接命令、目标 host/port，以及是否需要额外 TLS/认证配置。

### 交付物

在本文件的“实施记录”中添加一条：日期、SDK 版本/来源、确定的 `app_id` 获取方式。不得把真实敏感标识写入仓库；如其不能公开，记录环境变量名或密钥管理引用。

### 完成标准

- 已得到可配置的 `app_id` 来源；
- 已知真实环境的 SDK 构建和最小连接方式；
- 若未得到值，后续阶段可继续实现“空值失败”的代码和测试，但不得宣称真实性能测试已解除阻塞。

### 新会话交接提示

```
执行 docs/retrieval/2026-08-04_vector_engine_app_id_migration_plan.md 的阶段 1。
先阅读整个方案和当前 git status。不要修改真实 C++ SDK 或 mock；本阶段只添加会先失败的 Python/配置回归测试。
已确认的 app_id 来源：<粘贴阶段 0 结论或“尚未提供”>。
```

---

## 阶段 1：建立红色回归测试和配置校验

### 目标

先在 Python 层建立能捕获本次 ABI 漂移的快速、确定性测试。此阶段结束时，测试应因实现尚未迁移而失败（red），或者若测试只能验证尚未存在的字段，则失败点必须准确指向该缺失。

### 修改范围

- 新增或扩展 `tests/test_vector_engine/` 下的测试；
- 新增或扩展 `tests/test_config_runtime_gate.py`（以现有配置测试为准）；
- 不修改 `memoryhub/` 运行时代码；
- 不修改 `third_party/` 的 C++ 或 mock 实现。

### 必测场景

1. `VectorEngineConfig` 能表达 `app_id`；
2. `provider="milvus"` 且 `app_id` 为空/全空白时，配置加载或创建引擎前抛出稳定错误；
3. `_MilvusCAPI` 对 `vector_engine_connect` 的 ctypes 参数声明应为四项，顺序是 handle、app_id、host、port；
4. `_MilvusCAPI.connect()` 将 app_id UTF-8 编码并按该顺序转发；
5. 用假的 CDLL 函数对象或 monkeypatch 断言调用参数，**不依赖真实 `.so`**；
6. mock 集成测试的预期 ABI 也写成四参数（此时可预期因为 mock 尚未迁移而红）。

### 推荐验证命令

```powershell
.venv\Scripts\python.exe -m pytest tests/test_config_runtime_gate.py tests/test_vector_engine -q
```

若虚拟环境路径不同，使用当前项目 Python，但必须在交接记录中写清实际命令与输出摘要。

### 完成标准

- 存在至少一个测试能因“调用仍为旧三参数 ABI”而失败；
- 失败信息指向 app_id/ABI，而非动态库缺失；
- 测试不访问真实 Milvus；
- 记录精确 red 命令和失败摘要。

### 禁止事项

- 不通过放宽断言使旧实现变绿；
- 不在测试中用 `memoryhub` 作为真实部署 app_id；可使用明确的无敏感 fixture，例如 `test-app-id`；
- 不修改 mock 来让测试提前变绿。

### 新会话交接提示

```
执行 app_id 迁移方案的阶段 2。先运行并确认阶段 1 的 red 测试。
只改 Python 配置、构造链和 ctypes 封装，不改 C++/mock。将配置中的 app_id 明确传至 _MilvusCAPI.connect；保持阶段 1 测试全绿后提交。
```

---

## 阶段 2：迁移配置与 Python 调用链

### 目标

使应用从 YAML/构造参数一直到 ctypes 调用都显式携带 `app_id`，并在到达动态库之前完成校验。

### 预期改动

1. `memoryhub/config.py`
   - 为 `VectorEngineConfig` 增加 `app_id`；
   - 添加最小校验：类型为 `str`、`strip()` 后非空；
   - 校验应与 provider 语义一致；不要让 FAISS 配置因该字段不存在失败；
   - 检查 YAML 合并与环境变量覆盖路径是否能保留该字段；如项目已有向量引擎环境变量约定，再增加 `MEMORYHUB_VECTOR_ENGINE_APP_ID`，否则不要创造不一致的命名规则。
2. `config.example.yaml`
   - 在 `vector_engine` 中说明 `app_id` 必填；只给占位符，不能给可被误用的生产默认值；
   - 注释说明其由部署平台提供，且不属于 collection/user ID。
3. 引擎装配点（预计 `memoryhub/app.py`、`memoryhub/storage/vector_engine/__init__.py`、`memoryhub/storage/vector_engine/milvus_engine.py`）
   - 检查实际参数流；将 `app_id` 传入 `MilvusVectorEngine`；
   - `MilvusVectorEngine` 再传入 `_MilvusCAPI.connect`；
   - 不在中间层生成、转换或记录 app_id。
4. `memoryhub/storage/vector_engine/_milvus_ctypes.py`
   - `vector_engine_connect.argtypes` 改为 `[vector_engine_t, c_char_p, c_char_p, c_int]`；
   - `connect(handle, app_id, host, port)` 使用 `app_id.encode("utf-8")` 并保持与 C ABI 一致的顺序；
   - 对传入空值做防御性错误处理，避免 ctypes 传空指针。

### 验收

```powershell
.venv\Scripts\python.exe -m pytest tests/test_config_runtime_gate.py tests/test_vector_engine -q
.venv\Scripts\python.exe -m ruff check memoryhub tests
```

阶段 1 写出的单测应转绿。此时 mock 集成测试仍可能因 C mock 尚未改为四参数而失败；将该失败如实记录为阶段 3 的待完成项。

### 完成标准

- 配置对象、YAML、装配点、引擎实例与 ctypes 方法的签名均包含 app_id；
- app_id 只通过参数传递，不写入日志；
- Python 单元测试与静态检查通过；
- 不改变非 Milvus provider 的既有行为。

### 新会话交接提示

```
执行 app_id 迁移方案的阶段 3。先确认阶段 2 的 Python 回归通过。
将 C API 统一迁移为 vector_engine_connect(engine, app_id, host, port)，同步修改 C++ 桥接、mock、mock 验证脚本和任何 C API 测试。不得修改 app_id 的配置语义。完成后运行 mock 构建和验证。
```

---

## 阶段 3：迁移 C++ 桥接与 mock ABI

### 目标

真实桥接和 mock 暴露完全相同的四参数 C ABI，桥接层以 `app_id` 构造当前 SDK 的 `ConnectParam`。

### 预期改动

1. `third_party/libkysdk-vector-engine-client-nile-sp2/capi/c_api_bridge.h`

   ```c
   VE_CAPI_EXPORT int vector_engine_connect(
       vector_engine_t engine,
       const char* app_id,
       const char* host,
       int port);
   ```

   注释明确 app_id 为非空 SDK 应用身份标识，不是 collection 或 user ID。

2. `third_party/libkysdk-vector-engine-client-nile-sp2/capi/c_api_bridge.cpp`
   - 使用四参数签名；
   - 先检查 `app_id != nullptr && app_id[0] != '\0'`，在桥接层返回稳定错误并设置 `last_error`；
   - 使用：

     ```cpp
     VectorDB::ConnectParam param(
         app_id,
         host != nullptr ? host : "127.0.0.1",
         static_cast<uint16_t>(port));
     ```

   - 同时检查端口范围 `1..65535`，避免负值或大整数转换成意外的 `uint16_t`；
   - 不在异常/错误消息中回显 app_id；
   - 保持现有 StatusCode 映射策略，新增参数校验返回的错误码须选用 SDK 中现有的参数错误枚举，并以头文件实际定义为准。

3. `third_party/kylin-mock/vector_engine_mock.c`
   - 导出同一四参函数；
   - 要求 app_id 非空并返回非零错误，否则设置 `connected`；
   - mock 内不记录 app_id，不模拟服务端鉴权；
   - host/port 校验与真实桥接保持同一边界语义（至少空 app_id 与端口范围）。

4. `third_party/kylin-mock/verify_mock.py` 及所有直接 ctypes 调用
   - argtypes 与调用统一为四参数；
   - 使用固定的无敏感测试字符串 `b"test-app-id"`；
   - 增加空 app_id 返回非零的断言。

5. 搜索并更新仓库中所有 `vector_engine_connect(` 的调用、声明和代码样例；文档的系统性修订留到阶段 5，但不能保留会被编译或执行的旧调用。

### 必须检查的兼容性

- Python 的 `c_char_p` 顺序必须与 C 头文件逐字匹配；
- mock 的导出符号名不能改变；
- Windows、Linux、macOS 的库文件名和库加载规则不能改动；
- 不把连接成功语义建立在 mock 忽略 app_id 之上；空值必须失败。

### 验收命令

```powershell
.venv\Scripts\python.exe third_party/kylin-mock/build_mock.py
.venv\Scripts\python.exe third_party/kylin-mock/verify_mock.py
.venv\Scripts\python.exe -m pytest tests/test_vector_engine tests/test_search_milvus_mock.py -q
```

若构建依赖（如 zig）缺失，记录完整报错、版本和安装要求；不要伪造“已验证”。在拥有真实 SDK 工具链的环境，额外按阶段 4 构建。

### 完成标准

- mock 构建成功，`verify_mock.py` 全绿；
- 空 app_id 在 mock 和 Python 入口均失败；
- 正常 app_id 能完成 mock 的 connect → collection → insert → search；
- 不再存在可执行的三参数 `vector_engine_connect` 调用。

### 新会话交接提示

```
执行 app_id 迁移方案的阶段 4。不要再改 ABI。
在具备测试方提供的真实 SDK、依赖和网络环境中构建 libkysdk-vector-engine-client-capi，并执行最小连接烟测。收集编译输出、链接依赖和 app_id 非空/为空两种结果；不要运行性能压测。
```

---

## 阶段 4：真实 SDK 构建与连接烟测

### 目标

证明真实 C++ 桥接针对当前 SDK 头文件可编译，且在测试环境中能以平台提供的 app_id 成功连接；本阶段不是性能测试。

### 前置条件

- 已完成阶段 0，并获得 SDK 版本、构建命令、真实 app_id 来源和测试地址；
- 已完成阶段 3；
- 可使用 CMake/C++ 编译器、`KylinAiProto`、gRPC、protobuf、SQLiteCpp、sqlcipher 等 SDK 构建依赖；
- 已获访问测试向量引擎的授权。

### 操作

1. 在 SDK 目录外创建干净构建目录，不提交构建产物；
2. 使用测试方指定的 CMake 配置构建 `kysdk-vector-engine-client-capi`；
3. 保存实际 SDK 版本、编译器版本、CMake 命令和关键输出；
4. 用最小 ctypes 或 SDK 示例进行两次连接：
   - 空 app_id：预期失败，并确认错误为参数校验/`APPID_EMPTY` 等稳定失败；
   - 平台提供的 app_id：预期连接成功；
5. 只查询健康状态或立即 disconnect，不创建测试数据、不执行性能压测，除非测试方明确授权。

### 最小烟测断言

| 场景 | 预期 |
|---|---|
| 编译 C++ 桥接 | 成功，无 `ConnectParam(host, port)` 匹配错误 |
| 加载 C API 动态库 | 成功 |
| 空 app_id | 非零返回且有明确错误，不发生崩溃 |
| 合法 app_id + 合法 host/port | `vector_engine_connect` 返回 0 |
| disconnect/destroy | 返回成功/不泄漏、进程正常退出 |

### 阻塞处理

- 缺 app_id：记录为外部阻塞，不使用猜测值；
- 缺编译依赖：记录缺失包及 CMake 错误，交给环境维护方；
- 连接被服务端拒绝：收集不含 app_id 的错误码/消息，回到阶段 0 与测试方确认白名单或网络；
- 编译接口仍不匹配：保留完整错误，修复仅限桥接对当前 SDK 的适配，并回跑阶段 3。

### 完成标准

- 真实 C++ 桥接构建通过；
- 两组最小烟测结果已记录；
- 成功连接后，性能测试的“编译与初始化阻塞”解除；
- 尚未做性能压测，不报告性能结论。

### 新会话交接提示

```
执行 app_id 迁移方案的阶段 5。阅读阶段 4 的真实构建/烟测记录。
统一更新所有受影响的检索文档、配置示例和 API 示例；运行规定的 Python 全量回归与 mock 验证。检查仓库没有旧三参数调用，生成最终交付说明。
```

---

## 阶段 5：文档同步、全量回归与交付

### 目标

清理旧接口说明，形成可复验交付物，并把性能测试边界明确交还给测试方。

### 文档修改范围

至少检查并更新以下文件中任何可复制执行的旧 API 片段：

- `docs/retrieval/2026-08-02_milvus_c_api_minimal_interface.md`；
- `docs/retrieval/2026-08-02_kylin_vector_engine_sdk_api_signatures.md`；
- `docs/retrieval/2026-08-02_kylin_embedding_vector_engine_integration_plan.md`；
- `docs/retrieval/2026-08-02_kylin_environment_handoff_checklist.md`；
- `third_party/libkysdk-vector-engine-client-nile-sp2/README.md`；
- `third_party/kylin-mock/README.md`；
- `config.example.yaml`。

每处连接样例均应采用：

```c
vector_engine_connect(engine, app_id, host, port);
```

并注明 app_id 的来源和不应记录到日志的要求。

### 验收命令

```powershell
rg -n "vector_engine_connect\([^\n]*host[^\n]*port\)" .
.venv\Scripts\python.exe third_party/kylin-mock/verify_mock.py
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check memoryhub tests
```

第一条搜索的人工判定标准：不得再有三参数声明、调用或可执行示例；四参数接口的文字说明可以存在。若测试环境不能跑全量套件，至少运行阶段 1–3 的定向测试，并明确列出未执行项及原因。

### 最终交付清单

- C API 头文件、实现、ctypes 与 mock ABI 全部统一；
- `VectorEngineConfig.app_id` 已从配置到连接层端到端传递；
- 空值失败与正常值成功均有自动化验证；
- mock 验证与 Python 回归通过；
- 真实 SDK 的构建/烟测结论（或明确的外部阻塞）已记录；
- 文档与配置示例无旧三参数用法；
- 性能测试前置条件已满足，或精确说明还缺少什么。

## 5. 变更风险与回滚

### 主要风险

| 风险 | 控制措施 |
|---|---|
| C ABI 破坏导致遗漏调用方 | 在阶段 3/5 全仓 `rg` 搜索，并用 mock 验证 |
| app_id 被硬编码或泄露 | 配置传入、日志脱敏/不记录、示例用占位符 |
| mock 与真实库再次漂移 | 共同维护同一头文件契约，mock 空值测试纳入回归 |
| 配置校验过早阻断 FAISS 测试 | 校验以实际 provider 为条件，保留既有非 Milvus 行为 |
| 真实环境依赖缺失 | 阶段 4 只记录真实证据，不用 mock 替代真实构建结论 |

### 回滚

不要把生产修复回滚为旧三参数 ABI——当前 SDK 无法编译该接口。若新四参数迁移引入应用侧问题，应：

1. 回滚本次应用代码到上一个可工作的提交；
2. 保留阶段 1 的回归测试和阶段 4 的编译证据；
3. 与测试方确认 SDK 版本或 app_id 配置后，重新执行对应阶段。

## 6. 实施记录

每完成一个阶段，在下面追加一项（不得写入真实敏感 app_id）：

```markdown
### 阶段 N — YYYY-MM-DD

- 执行人/会话：
- 基线提交：
- 修改文件：
- 已执行命令及结果：
- 未执行项与原因：
- 外部输入/阻塞：
- 下一阶段可直接使用的结论：
```


### 阶段 2 — 2026-08-04

- 执行人/会话：Codex 当前会话
- 基线提交：095e19fe5557101aedff03e8702e0416a9eb05d3
- 修改文件：
  - memoryhub/config.py
  - config.example.yaml
  - memoryhub/app.py
  - memoryhub/storage/vector_engine/__init__.py
  - memoryhub/storage/vector_engine/milvus_engine.py
  - memoryhub/storage/vector_engine/_milvus_ctypes.py
  - 相关 Python 测试 fixture：显式使用无敏感值 test-app-id
- 已执行命令及结果：
  - .venv\Scripts\python.exe -m pytest tests/test_vector_engine/test_app_id_migration_phase1.py tests/test_vector_engine/test_milvus_mock_app_id_phase1.py -q --basetemp .pytest-tmp-stage2：8 passed。
  - .venv\Scripts\python.exe -m pytest tests/test_config_runtime_gate.py tests/test_app_production_assembly.py tests/test_vector_engine -q --basetemp .pytest-tmp-stage2-related3：67 passed。
  - .venv\Scripts\python.exe -m pytest tests/test_search_milvus_mock.py tests/test_retrieval/test_milvus_hybrid.py tests/test_sync_service.py -q --basetemp .pytest-tmp-stage2-integration：25 passed。
  - .venv\Scripts\python.exe -m ruff check memoryhub/config.py memoryhub/storage/vector_engine tests/test_vector_engine/test_app_id_migration_phase1.py tests/test_vector_engine/test_milvus_mock_app_id_phase1.py：通过。
  - .venv\Scripts\python.exe -m ruff check memoryhub tests：未通过，仓库现有 lint 问题共 278 项；本阶段未扩大范围清理无关 lint debt。
  - rg 检查确认 Python 侧已无旧三参数调用；third_party/kylin-mock/vector_engine_mock.c 与 third_party/kylin-mock/verify_mock.py 仍保留旧三参数 ABI，按方案留给阶段 3。
- 未执行项与原因：未修改或构建真实 C++ SDK、C++ bridge、mock C 实现和 mock 验证脚本；阶段 4 的真实 SDK 构建/连接烟测未执行。
- 外部输入/阻塞：阶段 0 真实 app_id 仍未提供；配置示例只保留部署平台占位符，测试使用 test-app-id。
- 下一阶段可直接使用的结论：阶段 2 的 config → app.py → factory → MilvusVectorEngine → _MilvusCAPI.connect 已统一携带 app_id，空值会在动态库加载前失败；阶段 3 可直接迁移 C++ bridge、mock ABI、mock 验证脚本及其直接 ctypes 调用。

### 阶段 3 — 2026-08-04

- 执行人：Codex 当前会话
- 基线提交：095e19fe5557101aedff03e8702e0416a9eb05d3
- 修改文件：
  - third_party/libkysdk-vector-engine-client-nile-sp2/capi/c_api_bridge.h
  - third_party/libkysdk-vector-engine-client-nile-sp2/capi/c_api_bridge.cpp
  - third_party/kylin-mock/vector_engine_mock.c
  - third_party/kylin-mock/verify_mock.py
  - docs/retrieval/2026-08-02_kylin_embedding_vector_engine_integration_plan.md
  - docs/retrieval/2026-08-02_kylin_vector_engine_sdk_api_signatures.md
  - docs/retrieval/2026-08-02_milvus_c_api_minimal_interface.md
- 实施结果：真实 C++ bridge、mock 和 mock 验证脚本统一使用 `vector_engine_connect(engine, app_id, host, port)`；bridge 与 mock 均拒绝空 app_id 和 1..65535 之外的端口；错误信息不回显 app_id；mock 保持不记录 app_id。
- 已执行命令及结果：
  - `.venv\\Scripts\\python.exe third_party\\kylin-mock\\build_mock.py`：成功构建 embedding mock 与 vector-engine C API mock DLL。
  - `.venv\\Scripts\\python.exe third_party\\kylin-mock\\verify_mock.py`：28 项检查通过（含空 app_id、非法端口、connect 到 collection/insert/search/disconnect）。
  - `.venv\\Scripts\\python.exe -m pytest tests\\test_vector_engine tests\\test_search_milvus_mock.py -q --basetemp .pytest-tmp-stage3`：42 passed。
  - `.venv\\Scripts\\python.exe -m ruff check third_party\\kylin-mock\\verify_mock.py tests\\test_vector_engine memoryhub\\storage\\vector_engine`：通过。
  - `git diff --check`：通过。
  - `rg -n "vector_engine_connect\\(" .`：可执行实现、调用和代码样例均为四参数；迁移计划中的旧接口描述仅作为历史问题背景保留。
- 未执行项及原因：未构建真实 SDK、未执行真实服务连接烟测；阶段 4 才具备真实 SDK 依赖、测试环境授权、网络地址和平台提供的 app_id。未执行性能压测。
- 外部输入/阻塞：阶段 0 尚未提供真实 app_id；当前仅使用无敏感信息的 `test-app-id` 做 mock 验证。工作区原有阶段 2 未提交改动已保留。
- 下一阶段可直接使用的结论：阶段 3 mock ABI 迁移完成；可在获得真实 SDK 构建依赖、服务地址及 app_id 后进入阶段 4，执行真实 C API 构建和最小连接烟测。

### 阶段 4 — 2026-08-05

- 执行人：Codex 当前会话
- 基线提交：未创建新提交；保留工作区已有阶段 2/3 改动，未重置或覆盖无关变更。
- 修改文件：本次仅追加本实施记录，未修改 ABI、运行时代码或 mock 实现。
- 已执行命令及结果：
  - `cmake -S third_party\\libkysdk-vector-engine-client-nile-sp2 -B D:\\tmp\\xa202612-2-stage4-real-sdk-build -DCMAKE_BUILD_TYPE=Release`：未执行配置，PowerShell 报 `cmake` 命令不存在。
  - 环境探测：`cmake`、`g++`、`pkg-config`、`protoc-gen-grpc`、`clang++` 均缺失；仅发现 `protoc`，不足以构建该 SDK。
  - `wsl.exe --status` / `wsl.exe -l -v`：被系统策略拒绝（`E_ACCESSDENIED`）。Docker Desktop Linux daemon 不可连接，且无可用本地镜像。
  - `.venv\\Scripts\\python.exe third_party\\kylin-mock\\build_mock.py`（设置本地 Zig cache 后）：构建成功。
  - `.venv\\Scripts\\python.exe third_party\\kylin-mock\\verify_mock.py`：28 项检查全部通过，包含空 `app_id` 拒绝、非法端口拒绝和完整 mock connect/collection/insert/search/disconnect 链路。
  - `.venv\\Scripts\\python.exe -m pytest tests\\test_vector_engine tests\\test_search_milvus_mock.py -q`：42 passed。
  - `git diff --check`：通过。
- 未执行项与原因：未构建真实 `libkysdk-vector-engine-client-capi`，未加载真实动态库，未执行真实服务空/合法 `app_id` 两组连接烟测；当前没有 CMake/C++/gRPC/SQLiteCpp/sqlcipher/KylinAiProto 完整构建环境，也没有测试方提供的真实 `app_id`、服务地址和授权网络环境。未运行性能压测。
- 外部输入/阻塞：阶段 0 记录的真实 `app_id` 仍未提供；当前环境变量 `MEMORYHUB_VECTOR_ENGINE_APP_ID`、`VECTOR_ENGINE_APP_ID`、`VECTOR_ENGINE_CAPI_SO`、`MILVUS_HOST`、`MILVUS_PORT` 均未设置。未将任何敏感标识写入仓库。
- 下一阶段可直接使用的结论：阶段 3 的四参数 ABI 与 mock 回归保持绿色；获得 Linux/Kylin SDK 构建工具链、依赖、真实 app_id 来源及 host/port 后，可直接按阶段 4 的 CMake 构建和最小连接烟测继续，不需要再次修改 ABI。

### 阶段 5 — 2026-08-05

- 执行人：Codex 当前会话
- 阅读阶段 4 真实构建/烟测记录：真实 SDK 构建与真实服务连接烟测仍因缺少 CMake/C++/gRPC 等完整工具链、真实 app_id、服务地址和授权网络环境未执行；阶段 4 的 mock 构建、28 项 mock 验证和相关回归已通过。
- 修改范围：
  - 统一更新 `docs/retrieval/` 中 C API、SDK 签名、集成计划、环境交接清单和检索改造方案的 `app_id` 配置与 API 示例；
  - 更新 `config.example.yaml`、`.env.example`、`docs/spec/CONFIGURATION.md`，明确 `MEMORYHUB_VECTOR_ENGINE_APP_ID` 与部署平台占位符；
  - 更新 `third_party/kylin-mock/README.md`，记录四参数 ABI、非空约束和 `test-app-id` fixture；
  - 更新真实烟测、环境自检和真实基准脚本，使 Milvus 调用显式传递 `--app_id`/`MEMORYHUB_VECTOR_ENGINE_APP_ID`；mock 基准固定使用无敏感 `test-app-id`，不打印 app_id；
  - SDK `ConnectParam` 文档已与仓库实际头文件一致：`ConnectParam(appId)` 或 `ConnectParam(appId, host, port)`，移除旧的无 app_id 构造/示例。
- 已执行命令及结果：
  - `.venv\Scripts\python.exe third_party\kylin-mock\build_mock.py`：首次因默认 Zig 临时目录权限失败；将 `ZIG_GLOBAL_CACHE_DIR`/`ZIG_LOCAL_CACHE_DIR` 指向工作区可写目录后重试成功构建两个 mock DLL。
  - `.venv\Scripts\python.exe third_party\kylin-mock\verify_mock.py`：28/28 项检查通过。
  - `.venv\Scripts\python.exe -m pytest -q`：默认 pytest 临时目录权限失败；改用 `.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp-stage5-full` 后 562 passed、6 skipped、101 warnings。
  - `.venv\Scripts\python.exe -m ruff check memoryhub tests`：未通过，仓库既有 lint debt 共 272 项；本次改动相关定向 lint 通过。
  - `.venv\Scripts\python.exe -m ruff check memoryhub\config.py memoryhub\storage\vector_engine evaluation\run_milvus_kylin_benchmark.py evaluation\run_milvus_mock_benchmark.py third_party\kylin-mock\verify_mock.py tests\test_vector_engine tests\test_config_runtime_gate.py tests\test_full_chain_benchmark.py tests\test_retrieval\test_milvus_hybrid.py tests\test_search_milvus_mock.py tests\test_sync_service.py`：通过。
  - `python -m compileall -q scripts evaluation memoryhub tests`：通过。
  - 按阶段 5 规定的 ABI 检索及旧三参数精确模式检索：未发现三参数连接形式（engine、host、port）。
- 未执行项及原因：真实 SDK CMake 构建、动态库加载和真实服务空/合法 app_id 两组连接烟测仍受阶段 4 外部环境阻塞；未运行真实性能压测。
- 外部输入/阻塞：真实 `app_id`、真实 host/port、SDK 依赖和授权网络环境仍未提供；仓库仅保留占位符，测试/mock 使用 `test-app-id`。
- 交付结论：文档、配置示例、API/ctypes/mock 示例已统一到四参数 ABI；Python 全量回归和 mock 验证通过；旧三参数调用清零；阶段 5 可交付，真实 SDK 烟测保持明确未验收状态。