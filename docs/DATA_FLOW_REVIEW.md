# MemoryHub 数据流通审查报告

> 审查范围：`memoryhub/` 后端、`console/`、API、存储、检索、遗忘、生命周期与安全写入链路  
> 首次审查：2026-08-01  
> 最近更新：2026-08-04
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

facts 的主事件、检索和遗忘链路，以及三类抽取失败的持久化重试/死信链路已经闭环。当前 pending-index 已有后台 upsert/delete 补偿，覆盖 preference/knowledge/facts 的运行时投影；系统仍不能称为强事务闭环：**事件库、各记忆库、审计、Evidence、BM25/FAISS 与向量索引之间仍没有统一的全局事务协议。抽取失败重试和 pending-index 补偿均已支持后台 worker，但 retry 指标尚未持久化到外部监控系统。**

## 2. 主要数据通路状态

| 通路 | 状态 | 当前核验结果 |
|---|---|---|
| `POST /api/memory/events` → events | ✅ | quality + SafetyWriteGate + 幂等/碰撞判定已接入；Gate 不可用时失败关闭。 |
| Event → preference | ✅ | 抽取、PreferenceUpdater、版本链、SQLite/索引/Evidence/cache 同步已接通。 |
| Event → knowledge | ✅ | 按 `(user_id, session_id, task_type)` 回读已安全持久化的完整有序轨迹；普通事件不误升格，标准 `tool_calls` 可进入工具链；重复轨迹按语义原位演进并幂等写入。 |
| Event → fact | ✅ | 仅首次安全事件经 FactIngestionAdapter 提取并提交；重复事件不重复抽取，调用失败计数并幂等入队。 |
| 抽取失败 → retry/dead letter | ✅ | preference/knowledge/facts 失败任务持久化，支持到期 claim、运行租约、指数退避、死信、owner 查询和显式重跑；重试仅回读已通过 Gate 的事件。 |
| `POST /api/memory/search` / `/context` | ✅ | preference/knowledge/facts 统一进入主检索；Milvus 路径按 user_id/status fail-closed 过滤，具备项目事实可见性、单值项目事实覆盖全局事实、缓存和访问统计。 |
| `POST /api/memory/feedback` | ✅ | 接口不变；校验所有权并兼容 preference/knowledge，knowledge confirm 更新成功/总使用次数，update/reject 同步数据库、向量、BM25、lookup、cache。 |
| `POST /api/memory/forget` | ✅ | preference/knowledge/facts 均校验 owner 并软删除；默认级联清理运行时索引及关联数据。 |
| 冲突列表/解决 | ✅ | `result_id`、真实命中、`user_id` 存储/查询/解决隔离已补齐。 |
| 生命周期/自动遗忘 | ✅ | preference/knowledge 的 level/status 通过 `MemoryWriteService` 持久化并同步移入/移出运行时索引；归档保留 Evidence，显式删除才级联删除 Evidence；facts 同步主索引。 |
| 安全写入 Gate | ✅ | startup 装配 Gate；缺审计/隔离密钥或规则服务时写路径失败关闭。 |
| 控制台 live 模式 | ✅ | console PreferenceMemory 与 live/mock 偏好列表已统一使用 `text`；Evidence/版本历史仍保留各自的 `content` 语义。 |

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
| B13 | ✅ | `core/conflict` detector/resolver 已实现确定性检测、owner/scope 隔离、自动决策和可选持久化；PreferenceUpdater 主链继续复用现有版本演进。 |
| B14/B15 | ✅ | AutoForget/LifecycleManager 使用正确仓储；facts 生命周期状态可持久化并同步索引。 |
| B16 | ✅ | preference、knowledge 与 facts 的访问次数和最近访问时间均已持久化。 |
| B17 | ✅ | Simulator 已补齐 Schema 1.1 source_hash/quality、完整 session/turn/tool/completion 轨迹，并支持可选 client 驱动。 |
| B19 | ✅ | console PreferenceMemory、mock 数据和列表渲染已统一使用 `text`；版本/证据条目中的 `content` 保持向后兼容。 |
| B20 | 🟡 | preference/knowledge/facts 已有统一 active upsert/inactive delete 补偿，删除状态可清理 Evidence/conflict，BM25/FAISS 也纳入投影；跨事件库、审计日志和多存储全局事务仍未实现。 |
| B21 | ✅ | facts 已接入 startup、主事件、主检索/上下文、访问统计、用户/项目隔离、显式遗忘与自动遗忘。 |
| B25 | 🟡 | 当前 API 错误均返回稳定 code 或通用消息，新增 facts/retry 路径未回显异常原文；仍建议继续做安全审计与认证 header 全覆盖。 |
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
| N17 | ✅ | Hybrid/MilvusRetriever 均保留调用方传入的空字典；Milvus owner/status 过滤同时恢复，启动空 lookup 与后续写入共享引用已回归测试。 |
| N18 | ✅ | 三类可选抽取失败仅计数、进程退出后不可恢复；已新增 `extraction_tasks`、幂等任务键、租约恢复、指数退避、死信、稳定错误码和显式管理 API。 |
| N19 | ✅ | 同一 `/events` 请求内重复 `event_id` 过去可能在批量落库前重复进入 Gate/抽取；已增加批内 pending 幂等判定。 |
| N20 | ✅ | knowledge 过去只使用本次请求中的新事件，同一 session 跨请求会被拆成多组知识；已新增 owner/session/task_type 完整安全轨迹回读并按 occurred_at/turn_id/event_id 排序。 |
| N21 | ✅ | 普通安全事件可能被误升格为 case/template；已增加知识信号准入、完成态判定、最少步骤与结果约束。 |
| N22 | ✅ | Schema 1.1 `MemoryEvent.tool_calls` 未进入知识工具链；已按 sequence 排序并仅接纳 success/partial 工具调用。 |
| N23 | ✅ | knowledge 缺少语义去重和演进，跨批次会持续新增；已新增 `KnowledgeUpdater`，按 owner/type/scope/名称/内容/步骤相似度合并，版本和 Evidence 原位演进；仅证据集合不重叠的独立执行增加使用计数与支持置信度，同一轨迹跨请求补全不重复计数。 |
| N24 | ✅ | knowledge LLM 必需路径异常可能被吞掉；已统一抛出稳定 `KnowledgeExtractionError`，由现有 extraction retry/dead-letter 链持久化处理。 |
| N25 | ✅ | knowledge scene 查询会把空 task_type 当作严格条件，名称搜索和使用统计缺少 owner 边界；空 scope 改为可选过滤，名称搜索/计数增加兼容的可选 owner 条件。 |
| N26 | ✅ | knowledge 索引文本统一复用 `MemoryWriteService.index_text/index_metadata`，包含 steps、tools、template_body、user_id、status；补偿路径已回归测试。 |
| N27 | ✅ | 生命周期状态变更会设置 pending_index；active 记录执行 upsert，inactive 记录执行 delete，删除失败保留 lookup tombstone 并等待补偿；归档 Evidence 保留。 |
| N28 | ✅ | EvidenceStore 追加写导致重试或原位演进重复记录；统一写入改为重写当前去重后的 Evidence 集合。 |
| N29 | ✅ | 同伴提交引入 `MemorySyncService` 后与主链 `MemoryWriteService` 并存；当前显式写入、主事件写入和 pending 补偿已统一复用主写服务/索引文本契约，并共享 lookup/BM25/FAISS。 |
| N30 | ✅ | inactive 记忆可能被 pending upsert 复活；补偿按 active upsert 与 archived/deleted delete 分流，状态变更会进入 pending。 |
| N31 | ✅ | 生产 Milvus 检索缺少 user_id/status 过滤；已下推过滤参数并在 SQLite lookup 回表后再次 fail-closed 校验。 |
| N32 | ✅ | `MemorySyncService` knowledge 文本遗漏 steps/tools/template_body；已复用 `MemoryWriteService` 的统一文本和 metadata 契约。 |
| N33 | ✅ | 显式写入和 startup repair 不更新 runtime lookup、BM25/访问统计；显式服务已接入统一写服务，开发 FAISS 路径也执行完整投影同步。 |
| N34 | ✅ | development 启动时先以 `keyword_search=None` 装配 writer/fact index，后续才创建 BM25；已前移 KeywordSearcher 装配并注入所有写入服务。 |
| N35 | ✅ | KnowledgeRepository 重复 `update_status` 覆盖 owner 安全实现，MemoryForgetter 未传 knowledge owner；已删除重复方法、恢复 owner 校验并在级联成功后清除 pending。 |
| N36 | 🟡 | preference/knowledge/facts 的 pending 删除和 tombstone 已统一；Evidence/conflict 删除随 deleted 状态重试，审计日志保持 append-only。跨事件库/审计/多存储事务仍不是原子协议。 |
| N37 | ✅ | 抽取 retry 增加可配置后台 worker、批量限制、lease 过期恢复、原子条件 claim 和运行指标接口；显式 API 仍保持不变。 |
| N38 | 🟡 | KnowledgeUpdater 增加可配置 name/content/steps 权重、等价/歧义阈值、owner-scoped 冲突审计和离线评测样本；仍未引入 embedding 聚类。 |
| N39 | ✅ | facts 增加 pending_index/index_version、Evidence/事实冲突审计表、启动/后台补偿和独立 facts/evidence/conflict 管理 API。 |
| N40 | ✅ | `core/conflict` 的 NotImplemented 桩已替换为确定性检测/解决策略；重复冲突记录按 conflict_id 幂等更新。 |
| N41 | ✅ | FastAPI 生命周期已迁移到 lifespan，Simulator 生成可被 Schema 1.1/Gate 接受的完整轨迹。 |
| N42 | 🟡 | Knowledge 提取已加入事件去重、owner/session/task 轨迹隔离、因子化置信度、结构化 LLM 兜底和不可变版本快照；仍未引入 embedding 聚类及线上质量监控。 |

## 5. `/events` 当前语义

- 相同 `event_id` 且相同 `source_hash`：按幂等成功计入 accepted，不覆盖旧事件、不重复抽取。
- 相同 `event_id` 但不同 `source_hash`：计入 rejected。
- quality rejected、Gate REVIEW/REJECT：计入 rejected，不进入普通事件库。
- Gate/审计/隔离或持久化基础设施异常：请求返回稳定错误，写路径失败关闭。
- preference/knowledge/facts 抽取失败不会回滚已安全接收的事件；响应返回 `extraction_failures`、`retry_tasks_enqueued`、`retry_queue_failures`。
- 失败任务只保存安全事件 ID 集合、owner、抽取类型、尝试次数、租约/退避时间和稳定错误码，不保存事件正文、prompt、API key 或异常原文。
- `GET /api/memory/extraction/tasks` 按用户查询状态；`POST /api/memory/extraction/tasks/run` 显式执行到期任务；`POST /api/memory/extraction/tasks/{task_id}/retry` 可由 owner 重置死信。

## 6. 仍未完成/后续优先级

1. **P0：** 将现有 preference/knowledge/facts 的局部最终一致性补偿扩展为跨事件库、Evidence、审计、BM25/FAISS 和向量索引的统一 outbox/事务协议，解决各存储之间仍非全局原子的问题。
2. **P1：** 为抽取 retry 增加多进程数据库锁/指标持久化和失败告警；当前已有受控后台 worker、原子条件 claim 和内存指标。
3. **P1：** 将 knowledge 语义合并从规则/字符串相似度继续演进为 embedding 聚类或学习型合并，并补充多语言样本、规模化阈值标定和线上质量监控；当前已有可配置阈值、冲突审计、离线评测、因子化置信度和版本快照，但尚非 embedding/学习型聚类。
4. **P1：** 为 facts 补充实体/谓词管理和可视化冲突解决 API；当前已有 facts、Evidence、conflict 查询/删除接口和主事件/检索/遗忘链。
5. **P1：** 将 `core/conflict` 的规则检测与 PreferenceUpdater/FactConflict 统一为一个可配置策略层。
6. **P1：** 将 console 其他记忆类型和 mock 数据也迁移到统一的字段适配器，避免 UI 直接读取原始 dict。
7. **P2：** 为 Simulator 增加真实 HTTP client 集成回归和失败重试场景。
8. **P2：** 为 lifespan 增加 worker 启停与异常恢复集成测试。

## 7. 验证结果

未运行 `tests/test_knowledge/test_knowledge_api.py`（按用户要求，该文件用于真实 LLM 知识提取调用测试）。

2026-08-04 数据流修复相关测试：

```text
tests/test_data_flow_merge_regressions.py: 8 passed
data-flow/knowledge/retry/retrieval/facts/app 组合回归: 99 passed, 1 skipped
python -m compileall -q memoryhub console: passed
```

环境无关测试集合：

```text
529 passed, 5 skipped, 1 deselected
```

完整测试尝试（排除真实 LLM 测试）：

```text
527 passed, 5 skipped, 14 failed, 28 errors
```

失败/错误集中在缺失的 Kylin embedding 和 Milvus native mock DLL、benchmark/milvus-mock 集合，以及依赖该 mock 的稳定超时用例；当前未发现由本轮 Python 数据流修改导致的回归。

## 8. 环境阻塞

- 当前仓库没有任何 `.dll/.so/.dylib` mock 构建产物；Kylin embedding mock 和 Milvus mock 原生集成测试均无法启动。
- facts 测试集中有 1 项真实外部 LLM/环境测试被跳过；主链使用 fake/mock 完成回归，不依赖外部凭据。
