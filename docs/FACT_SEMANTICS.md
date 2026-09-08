# FACT 语义增强

FACT 仍以 `KnowledgeMemory(knowledge_type=FACT)` 为正式记录，统一通过现有
`MemoryWriteService`、Authority、Evidence、Lineage 和索引投影保存。新增的
`fact_entities`、`fact_predicates`、`fact_bindings` 表只保存语义标识和关系绑定，
不复制事实正文。

写入 FACT 时，`FactSemanticService` 先在租户和用户范围内解析主体、谓词和客体。
精确匹配或唯一高置信包含匹配会复用实体；多个候选返回
`DECISION_REQUIRED`，不会自动注册未经确认的别名。谓词由内置关系本体提供别名、
逆关系、对称性、基数、互斥、自反和成环约束。

关系冲突在写入前检测。重复事实补充证据，多值关系共存，单值、互斥、类型和环
冲突进入 `PENDING` 并在 `extra_payload.fact_decision_task` 保存待裁决信息。待裁决
事实不会进入正常检索；`/api/memory/facts/proposals` 可在重启后恢复任务，
`/api/memory/facts/decide` 和 Agent 决策路由使用相同的统一写入服务。

多租户请求通过现有 `X-MemoryHub-Tenant` 请求头绑定；缺少该头时保留兼容的
默认租户读取。MCP `memoryhub_decide_facts` 暴露实体、谓词、客体选择和
`expected_version`，裁决时会重新归一化并校验任务版本。

旧 FACT 行没有语义绑定时，第一次检测会尝试幂等补全；无法确定实体或关系时保留
原记录并等待人工处理。当前只实现结构化关系检测，不实现有效时间区间、否定事实
语义或来源可信度裁决。

迁移脚本 `scripts/migrate_fact_semantics.py` 默认只读扫描，只有显式 `--apply`
才创建语义绑定；它不改动原有 `memory_id`、证据和历史状态。
