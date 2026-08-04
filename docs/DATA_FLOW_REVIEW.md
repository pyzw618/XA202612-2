# MemoryHub 数据流通审查报告

> 审查范围：`memoryhub/` 后端、`console/`、API、存储、检索、遗忘、生命周期与安全写入链路  
> 首次审查：2026-08-01  
> 最近更新：2026-08-03  
> 状态说明：✅ 已修复；🟡 部分修复；🔴 已确认未修复；⚪ 环境阻塞/暂不验证

## 1. 当前结论

主要事件与记忆链路已推进到可回归验证的闭环：

1. `/events` 对事件重新质量评分，并强制经过 `SafetyWriteGate`；ALLOW/MASK 才能进入普通事件库，REVIEW/REJECT 不进入普通存储。
2. 相同 `event_id + source_hash` 按幂等成功处理但不重复抽取，同 ID 不同 hash 被拒绝。
3. 首次安全事件触发 preference、knowledge 与 facts 抽取；knowledge 会按 owner/session/task_type 回读完整安全轨迹，完成准入、排序、工具链提取、语义归并和原位演进；facts 经 `FactIngestionAdapter` 和 `FactMemoryPipeline` 完成准入、归一化、冲突处理、持久化和索引同步。
4. preference/knowledge 使用 `MemoryWriteService`，facts 使用 `FactIndexService`，同步 SQLite、FAISS/Milvus、BM25、runtime lookup 与搜索缓存。
5. 主搜索和上下文查询返回 preference、knowledge 与 facts，并按 `user_id`、项目作用域、类型和置信度过滤；成功命中回写访问统计。
6. 显式遗忘覆盖 preference、knowledge 与 facts；默认级联清理共享索引、lookup、cache、EvidenceStore、关联 conflict，facts 同时清理用户范围内孤立实体。
7. 自动遗忘已纳入三类记忆；preference/knowledge 的状态或层级变化通过统一写服务同步 SQLite、索引、lookup 和 cache，归档后保留持久化 Evidence；facts 的 ISO 时间与 `observed_at` 可参与健康度计算。
8. facts 可复用主应用 LLM client；缺少外部 API key 时仍可启动，外部调用失败不会伪装为正常“无事实”。
9. preference、knowledge、facts 抽取失败会持久化为仅引用安全事件的任务，支持租约恢复、指数退避、死信、显式重跑和用户隔离查询；错误状态仅保存稳定错误码。

facts 的主事件、检索和遗忘链路，以及三类抽取失败的持久化重试/死信链路已经闭环。系统仍不能称为强事务闭环：**跨事件库、各记忆库、审计、Evidence 与向量索引的全局事务/补偿协议仍未实现；当前重试由显式 API 驱动，尚未启用后台调度循环。**

## 2. 主要数据通路状态

| 通路 | 状态 | 当前核验结果 |
|---|---|---|
| `POST /api/memory/events` → events | ✅ | quality + SafetyWriteGate + 幂等/碰撞判定已接入；Gate 不可用时失败关闭。 |
| Event → preference | ✅ | 抽取、PreferenceUpdater、版本链、SQLite/索引/Evidence/cache 同步已接通。 |
| Event → knowledge | ✅ | 按 `(user_id, session_id, task_type)` 回读已安全持久化的完整有序轨迹；普通事件不误升格，标准 `tool_calls` 可进入工具链；重复轨迹按语义原位演进并幂等写入。 |
| Event → fact | ✅ | 仅首次安全事件经 FactIngestionAdapter 提取并提交；重复事件不重复抽取，调用失败计数并幂等入队。 |
| 抽取失败 → retry/dead letter | ✅ | preference/knowledge/facts 失败任务持久化，支持到期 claim、运行租约、指数退避、死信、owner 查询和显式重跑；重试仅回读已通过 Gate 的事件。 |
| `POST /api/memory/search` / `/context` | ✅ | preference/knowledge/facts 统一进入主检索；具备用户隔离、项目事实可见性、单值项目事实覆盖全局事实、缓存和访问统计。 |
| `POST /api/memory/feedback` | ✅ | 接口不变；校验所有权并兼容 preference/knowledge，knowledge confirm 更新成功/总使用次数，update/reject 同步数据库、向量、BM25、lookup、cache。 |
| `POST /api/memory/forget` | ✅ | preference/knowledge/facts 均校验 owner 并软删除；默认级联清理运行时索引及关联数据。 |
| 冲突列表/解决 | ✅ | `result_id`、真实命中、`user_id` 存储/查询/解决隔离已补齐。 |
| 生命周期/自动遗忘 | ✅ | preference/knowledge 的 level/status 通过 `MemoryWriteService` 持久化并同步移入/移出运行时索引；归档保留 Evidence，显式删除才级联删除 Evidence；facts 同步主索引。 |
| 安全写入 Gate | ✅ | startup 装配 Gate；缺审计/隔离密钥或规则服务时写路径失败关闭。 |
| 控制台 live 模式 | 🟡 | 偏好表格兼容 `text`，详情和 conflict 调用传递 `user_id`；console 模型仍有部分旧字段。 |

## 3. 原问题复核矩阵

| 编号 | 状态 | 2026-08-03 复核结果 |
|---|---|---|
| B1 | ✅ | startup 创建并注入 EventRepository。 |
| B2 | ✅ | `/events` 已串联 quality、SafetyWriteGate、事件持久化和 preference/knowledge/facts 抽取。 |
| B3 | ✅ | feedback 校验所属用户并同步运行时索引。 |
| B4 | ✅ | EventNormalizer 补齐 Schema 1.1、source_hash、quality、turn_id、tool_calls、redactions。 |
| B5 | ✅ | conflict resolve 保存 result_id 并返回真实命中。 |
| B6 | ✅ | startup 按配置装配 OpenAI/Ollama LLM client；facts 复用该 client。 |
| B7 | ✅ | 后端偏好正文统一使用 `PreferenceMemory.text`；控制台 live 读取已兼容。 |
| B8/B9 | ✅ | 遗忘调用真实 delete/status update，并同步索引、lookup、cache。 |
| B10/B11 | ✅ | PreferenceExtractor/updater 的 prompt 和 LLMResponse.content 契约已修复。 |
| B12 | ✅ | preference、knowledge 与 facts 抽取均接入事件入口。 |
| B13 | 🟡 | 主偏好冲突演进已修复并持久化；`core/conflict` 其他重复/桩式实现仍需清理。 |
| B14/B15 | ✅ | AutoForget/LifecycleManager 使用正确仓储；facts 生命周期状态可持久化并同步索引。 |
| B16 | ✅ | preference、knowledge 与 facts 的访问次数和最近访问时间均已持久化。 |
| B17 | 🔴 | Simulator 中未实现方法仍需单独处理。 |
| B19 | 🟡 | 控制台关键 live 路径已兼容 `text`；模型层仍有旧 `content` 字段。 |
| B20 | 🟡 | 核心仓储、索引、LLM、Gate、抽取及持久化重试/死信已装配；后台定时调度与跨存储补偿协议仍未实现。 |
| B21 | ✅ | facts 已接入 startup、主事件、主检索/上下文、访问统计、用户/项目隔离、显式遗忘与自动遗忘。 |
| B25 | 🟡 | 主要搜索/写入/详情/feedback 错误已脱敏；仍建议继续做全 API 审计。 |
| B27 | ✅ | accepted/rejected 反映质量、Gate、幂等/碰撞决策；基础设施失败返回稳定错误。 |
| B28 | ✅ | EventRepository 完整 round-trip Schema 1.1。 |
| B30 | ✅ | MemoryWriteService 与 FactIndexService 分别统一同步记忆和 facts 的运行时索引。 |
| B31 | ✅ | SafetyWriteGate 已接入真实写路径。 |
| B33 | ✅ | EvidenceStore、conflicts 与 facts 已纳入遗忘级联；facts 删除后清理共享索引和孤立实体。 |

## 4. 新发现并已修复的问题

| 编号 | 状态 | 说明 |
|---|---|---|
| N8 | ✅ | PreferenceRepository 丢失 payload/is_global/quality/extract_source/root_id/tags/extra_payload；已补齐 ORM、转换和兼容迁移。 |
| N9 | ✅ | Evidence datetime 写 JSON 失败；已统一使用 JSON mode 序列化。 |
| N10 | ✅ | PreferenceUpdater merge 修改并归档同一对象；已改为新版本对象并建立 parent/root/version。 |
| N11 | ✅ | QualityScorer 对未来时间戳可能返回 freshness > 1；已限幅。 |
| N12 | ✅ | conflict 缺少 user_id；已补齐 schema、ORM、迁移、仓储、API 与控制台参数。 |
| N13 | ✅ | facts/Entity 缺少 user_id，归一化和 S+P 冲突可跨用户串数据；已增加 owner 字段、用户范围实体 ID、查询/更新边界及旧库迁移。 |
| N14 | ✅ | facts 绑定独立远程客户端且 import 可能下载模型；已支持注入主 LLM、无凭据启动，并限制 sentence-transformers 仅加载本地缓存。 |
| N15 | ✅ | facts 未进入主索引、访问统计和项目覆盖语义；已新增 FactIndexService、FactMemory 响应模型和项目覆盖过滤。 |
| N16 | ✅ | facts 不参与显式/自动遗忘，健康度不能处理 ISO 时间；已接入 owner 校验、索引级联、孤立实体清理和自动生命周期。 |
| N17 | ✅ | Hybrid/MilvusRetriever 对空 lookup 使用 `or {}` 会断开共享引用，导致启动后新写 facts/记忆不可见；已保留调用方传入的空字典。 |
| N18 | ✅ | 三类可选抽取失败仅计数、进程退出后不可恢复；已新增 `extraction_tasks`、幂等任务键、租约恢复、指数退避、死信、稳定错误码和显式管理 API。 |
| N19 | ✅ | 同一 `/events` 请求内重复 `event_id` 过去可能在批量落库前重复进入 Gate/抽取；已增加批内 pending 幂等判定。 |
| N20 | ✅ | knowledge 过去只使用本次请求中的新事件，同一 session 跨请求会被拆成多组知识；已新增 owner/session/task_type 完整安全轨迹回读并按 occurred_at/turn_id/event_id 排序。 |
| N21 | ✅ | 普通安全事件可能被误升格为 case/template；已增加知识信号准入、完成态判定、最少步骤与结果约束。 |
| N22 | ✅ | Schema 1.1 `MemoryEvent.tool_calls` 未进入知识工具链；已按 sequence 排序并仅接纳 success/partial 工具调用。 |
| N23 | ✅ | knowledge 缺少语义去重和演进，跨批次会持续新增；已新增 `KnowledgeUpdater`，按 owner/type/scope/名称/内容/步骤相似度合并，版本和 Evidence 原位演进；仅证据集合不重叠的独立执行增加使用计数与支持置信度，同一轨迹跨请求补全不重复计数。 |
| N24 | ✅ | knowledge LLM 必需路径异常可能被吞掉；已统一抛出稳定 `KnowledgeExtractionError`，由现有 extraction retry/dead-letter 链持久化处理。 |
| N25 | ✅ | knowledge scene 查询会把空 task_type 当作严格条件，名称搜索和使用统计缺少 owner 边界；空 scope 改为可选过滤，名称搜索/计数增加兼容的可选 owner 条件。 |
| N26 | ✅ | knowledge 索引文本只包含 name/content；已统一加入 steps、tools、template_body，startup、API fallback 和统一写服务使用同一文本契约。 |
| N27 | ✅ | knowledge 生命周期归档只改 SQLite，运行时索引仍可命中；repository 关联统一写服务后，归档/待审查/层级变化同步索引、lookup、cache，归档 Evidence 保留。 |
| N28 | ✅ | EvidenceStore 追加写导致重试或原位演进重复记录；统一写入改为重写当前去重后的 Evidence 集合。 |

## 5. `/events` 当前语义

- 相同 `event_id` 且相同 `source_hash`：按幂等成功计入 accepted，不覆盖旧事件、不重复抽取。
- 相同 `event_id` 但不同 `source_hash`：计入 rejected。
- quality rejected、Gate REVIEW/REJECT：计入 rejected，不进入普通事件库。
- Gate/审计/隔离或持久化基础设施异常：请求返回稳定错误，写路径失败关闭。
- preference/knowledge/facts 抽取失败不会回滚已安全接收的事件；响应返回 `extraction_failures`、`retry_tasks_enqueued`、`retry_queue_failures`。
- 失败任务只保存安全事件 ID 集合、owner、抽取类型、尝试次数、租约/退避时间和稳定错误码，不保存事件正文、prompt、API key 或异常原文。
- `GET /api/memory/extraction/tasks` 按用户查询状态；`POST /api/memory/extraction/tasks/run` 显式执行到期任务；`POST /api/memory/extraction/tasks/{task_id}/retry` 可由 owner 重置死信。

## 6. 仍未完成/后续优先级

1. **P1：** 设计跨事件库、各记忆库、Evidence、审计和向量索引的补偿/最终一致性协议。
2. **P1：** 为持久化抽取任务补充受控后台调度、并发 worker 原子 claim 和运行指标；当前显式执行 API 已可用。
3. **P1：** 为 knowledge 的语义合并补充可配置阈值、冲突审计和离线评测数据集；当前规则/字符串相似度已能完成幂等演进，但尚非 embedding/学习型聚类。
4. **P1：** 为 facts 补充独立管理 API、冲突审计记录和更完整的 Evidence 关联；当前已覆盖主事件/检索/遗忘链。
5. **P1：** 清理 `core/conflict` 重复或桩式实现。
6. **P1：** 完成 console models 的 `text/content` 最终统一。
7. **P2：** 实现 Simulator 未完成方法。
8. **P2：** 将 FastAPI `on_event` 迁移到 lifespan。

## 7. 验证结果

未运行 `tests/test_knowledge/test_knowledge_api.py`（按用户要求，该文件用于真实 LLM 知识提取调用测试，且保留用户原有修改）。

knowledge 专项与相关链路：

```text
tests/test_knowledge/test_knowledge_data_flow.py: 8 passed
tests/test_data_flow_regressions.py + tests/test_extraction_retry.py
+ tests/test_knowledge/test_knowledge_ingestion_adapter.py: 30 passed
合计: 38 passed
```

排除真实 LLM 测试和本机缺失的 Milvus mock DLL 测试后，项目测试结果：

```text
451 passed, 5 skipped, 61 warnings
```

静态与编译验证：

```text
knowledge/ingestion/memory_write 新增及重构文件 ruff check: passed
python -m py_compile（knowledge 相关修改文件）: passed
git diff --check: passed
```

完整测试执行结果为 `452 passed, 5 skipped`，另有 `4 failed, 17 errors`；失败/错误均来自缺失
`third_party/kylin-mock/build/libkysdk-vector-engine-client-capi-mock.dll`，不是 knowledge 重构回归。

## 8. 环境阻塞

- Milvus mock 原生测试仍需要 `third_party/kylin-mock/build/libkysdk-vector-engine-client-capi-mock.dll`；当前缺失导致对应 4 个失败、17 个 setup error。
- facts 测试集中有 1 项真实外部 LLM/环境测试被跳过；主链使用 fake/mock 完成回归，不依赖外部凭据。
