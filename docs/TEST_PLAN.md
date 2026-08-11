# Kylin-MemoryHub 测试计划

> 版本: v1.0
> 日期: 2026-08-11
> 适用对象: 测试人员
> 依据文档: `docs/INTERFACE.md`、`docs/ARCHITECTURE.md`、`docs/SAFETY_MODULE_TECHNICAL.md`、
> `docs/CONFIGURATION.md`、`docs/DATA_FLOW_UPDATE.md`、`docs/forget_module_v1.md`、
> `docs/前端功能规划.md`、`docs/麒麟数据库原生化过程.md`

---

## 1. 项目概述

MemoryHub 是银河麒麟 OS 上 AI Agent 的端侧记忆系统,包含:**事件接入 → 质量评分 → 安全过滤 →
偏好/知识/事实抽取 → 混合检索(向量+BM25+元数据) → SQLite + 向量引擎 + 证据链持久化**,
以及遗忘模块、管理控制台(PyQt6)、Agent 集成(opencode / Claude Code / 千问)与评测模块。

## 2. 测试目标

1. 验证 10 个 REST 端点组的功能正确性与契约一致性;
2. 重点验证安全模块的 8 项核心能力(规则库/扫描/决策/脱敏/审计/隔离/写入门禁/用户规则);
3. 验证记忆写入 → 检索 → 遗忘全链路闭环;
4. 验证持久化与重启恢复、向量引擎(Milvus/FAISS)切换;
5. 验证前端控制台 7 个页面与后端 API 的对接;
6. 验证麒麟原生 SDK 链路与评测指标。

## 3. 测试环境

| 项目 | 配置 |
|------|------|
| 操作系统 | 银河麒麟 OS(生产目标);开发环境可用 Windows/Linux |
| Python | >= 3.11(当前环境 3.12) |
| 依赖 | `pip install -r requirements.txt`(含 faiss-cpu、rank-bm25、jieba、fastapi、sqlalchemy、cryptography) |
| 服务启动 | `uvicorn memoryhub.app:app --host 127.0.0.1 --port 8010` |
| 接口文档 | `http://127.0.0.1:8010/docs` |
| LLM | 可选(Ollama 本地 / OpenAI 兼容 API),无 key 时系统应可启动 |
| Embedding | 开发用 mock;麒麟 SDK 需真实 `.so` 与 Milvus gRPC(端口 19530) |

**必需安全密钥**(由环境变量注入,不入库不入仓):

- `MEMORYHUB_AUDIT_HMAC_KEY` — 审计 HMAC
- `MEMORYHUB_QUARANTINE_KEY` — REVIEW 隔离 AES-256-GCM
- `MEMORYHUB_USER_RULE_KEY` — 用户规则 matcher 主密钥(Base64,32 字节)

生产模式(`MEMORYHUB_RUNTIME_MODE=production`)禁止 mock/fallback。

## 4. 当前基线(回归基线)

| 指标 | 结果 |
|------|------|
| 测试命令 | `.venv/bin/python -m pytest tests -q` |
| 收集用例 | 592 |
| 通过 | 590 |
| 跳过 | 2(需真实 API key:`RUN_LLM_API_TESTS=1` + `DASHSCOPE_API_KEY`) |
| 警告 | 1(httpx 弃用提示,非功能性) |
| 耗时 | 约 82 s |

测试覆盖主要模块:`tests/test_safety_*`(约 5000 行,安全占比最大)、
`test_data_flow_regressions`、`test_fact/`、`test_knowledge/`、`test_vector_engine/`、
`test_retrieval/`、`test_search_*`、`test_milvus_hybrid_retriever`、`test_extraction_retry` 等。

---

## 5. 测试策略

| 测试类型 | 手段 | 优先级 |
|----------|------|--------|
| 单元测试 | pytest(已有 592 用例,作为回归基线) | P0 |
| API 契约测试 | FastAPI TestClient / curl 对全部端点做正向+异常用例 | P0 |
| 安全专项测试 | 手工构造恶意/边界输入,验证失败关闭 | P0 |
| 集成测试 | 写→检索→遗忘端到端、模拟重启恢复 | P1 |
| 前端功能测试 | PyQt6 控制台 7 页面手动操作 | P1 |
| 性能测试 | evaluation/metrics 延迟基准、并发写入 | P2 |
| 麒麟原生测试 | 真实 .so + Milvus 部署验收 | P2(视环境就绪) |

通过标准:所有 P0 用例通过;P1 缺陷率 ≤ 0(阻断类);无敏感信息(密钥/原文)泄漏。

---

## 6. 详细测试范围与用例

### 6.1 安全模块专项(SEC,最高优先级)

依据:`SAFETY_MODULE_TECHNICAL.md`、`SAFETY_RULE_LIBRARY.md`、`CONFIGURATION.md`

| 编号 | 测试项 | 关键步骤/输入 | 期望结果 |
|------|--------|---------------|----------|
| SEC-01 | 规则库加载与完整性 | 加载内置 catalog `kylin-memoryhub.safety@1.0` | digest 一致;版本不存在/摘要不符直接失败,不回退 |
| SEC-02 | 溯源矩阵 | 抽查 API Key/身份证/IP 规则的 `standard_ref` | 法律/国标/RFC/策略来源可追溯 |
| SEC-03 | 递归扫描范围 | 事件携带 text/payload 深层嵌套/tool_calls/redactions 敏感串 | 全字段命中;事件不被修改 |
| SEC-04 | 扫描预算超限 | 超深嵌套(>64)、超大字段(>65536 字符)、超节点数 | 抛稳定 `SafetyScanError`,不含原文 |
| SEC-05 | Unicode 绕过 | 全角字符、零宽字符、NFKC 组合的敏感串 | 命中;span 正确反投影到原始位置 |
| SEC-06 | 决策聚合 | 多 Finding 混合等级/动作 | 固定优先级 REJECT>REVIEW>MASK>ALLOW |
| SEC-07 | 覆盖不能削弱 | rule/level override 配置为更宽松动作 | 取更严格者;普通覆盖不得 ALLOW |
| SEC-08 | 有限期例外 | 仅低风险上下文标识(IPv4)可配置 ALLOW 例外 | 有效期内生效,过期/缺失字段拒绝;凭据不可放行 |
| SEC-09 | 脱敏与复检 | MASK 动作后检查残留 | 无残留、二次脱敏幂等;有残留升级 REVIEW |
| SEC-10 | 结果认证 | 跨实例/手工构造 SafetyResult 输入 Gate | HMAC/attestation 不匹配即失败关闭 |
| SEC-11 | 审计哈希链 | 追加记录、删除尾部、修改中段 | 截断/篡改被检出;链断裂失败关闭 |
| SEC-12 | 审计轮转与保留 | 触发轮转、清理后 verify | 保留后仅验证从 anchor 开始的后缀 |
| SEC-13 | REVIEW 隔离 | HIGH+REVIEW 事件进入隔离区 | 磁盘仅存 AES-256-GCM 密文;到期拒绝解密;特权读取不得直接改 ALLOW |
| SEC-14 | 写入 Gate 强制 | 审计追加失败/回执无效时继续写 | 全部阻断,只抛稳定错误码,不泄漏输入 |
| SEC-15 | 用户规则 CRUD | 创建 literal/regex 规则、更新、软删除 | matcher 永不回显;乐观并发 409;软删除 |
| SEC-16 | 用户规则生效 | `mask_match` / `drop_event` 两种 effect | mask 固定 `[REDACTED_USER_DEFINED]` 且同快照复检;drop 整条 REJECT |
| SEC-17 | 用户规则安全边界 | 身份缺失/不一致、密钥缺失 | 503/403;provider 失败关闭不降级 |
| SEC-18 | 错误与日志无原文 | 触发各类扫描/审计异常,检查响应与日志 | 仅稳定错误码;无敏感原文/密钥 |
| SEC-19 | 生产配置门禁 | production 模式配置 mock/faiss/milvus_mock | 启动被拒;fail_closed/strict_permissions/fsync 不可关闭 |

### 6.2 事件写入链路(EVT)

依据:`INTERFACE.md` 5.1、`DATA_FLOW_UPDATE.md`

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| EVT-01 | Schema 1.1 校验 | 缺字段/非法枚举/未知顶层字段的事件 | 422,仅白名单化错误 |
| EVT-02 | Schema 1.0 兼容 | 旧格式(含 payload 内 tool_result)读入 | 正常迁移读取,新写强制 1.1 |
| EVT-03 | 质量评分 | 构造完整度/新鲜度不同的 5 组输入 | 4 因子公式正确;accepted/review/rejected 判定正确 |
| EVT-04 | 幂等去重 | 重复 event_id / 相同 source_hash | 不重复触发下游;accepted 计数正确 |
| EVT-05 | 安全门禁 | 含敏感串的事件写入 | REJECT/REVIEW 不入普通存储;MASK 只存脱敏副本 |
| EVT-06 | 抽取编排 | user_feedback/user_behavior/task_trajectory 事件 | 仅首次安全事件触发偏好/知识/事实抽取 |
| EVT-07 | 抽取失败重试 | 强制抽取失败、查询 extraction/tasks | 幂等入队、退避、死信、重试成功 |
| EVT-08 | 批量事件 | 一次提交 N 条混合事件 | accepted/rejected/event_ids 一致;半成功可恢复 |

### 6.3 偏好记忆(PRE)

依据:`INTERFACE.md` 1.4、3.2、`DATA_FLOW_UPDATE.md`

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| PRE-01 | 规则抽取 | "以后都用 X"/"默认使用 X"/"不要记住 X" | 正确映射 7 类 PreferenceType |
| PRE-02 | LLM 抽取 | 隐式偏好文本(有 key 时) | 结构化输出;失败时系统可用 |
| PRE-03 | 置信度计算 | explicit_feedback vs single_behavior | 来源权重/时间衰减/一致性因子正确 |
| PRE-04 | 版本链 | 连续更新同一条偏好 | 旧版 archived、version+1、parent/root 正确 |
| PRE-05 | 全局兜底 | 无场景偏好时检索 | 降级命中 is_global=true 偏好 |
| PRE-06 | 证据链 | 每次抽取生成 Evidence | 含 event_id/weight/decision,JSON 可读 |
| PRE-07 | 用户隔离 | 两个 user_id 各建偏好 | 互不可见;检索按用户隔离 |

### 6.4 冲突处理(CON)

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| CON-01 | 冲突检测 | scope 重叠+同类型+语义矛盾 | 产生 ConflictRecord |
| CON-02 | 自动解决矩阵 | 显式反馈→override;互补→merge;异 scope→coexist;无法判断→pending | 决策与原因正确 |
| CON-03 | 手动解决 | 对 pending 调用 resolve 接口 | 更新 decision/reason/resolved_at |
| CON-04 | 证据标记 | 冲突消解后查证据链 | Evidence.decision 已标记 |
| CON-05 | 用户隔离 | 跨用户冲突查询/解决 | 按 user_id 命中,不越权 |

### 6.5 知识记忆(KNO)

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| KNO-01 | 工作流抽取 | task_trajectory 事件序列 | 提取 steps/tools |
| KNO-02 | 案例抽取 | 单次任务轨迹 | case 知识 name+content |
| KNO-03 | 模板构建与渲染 | case→template、传入 variables | render 输出正确 |
| KNO-04 | 必填字段校验 | workflow 缺 steps / template 缺 body | 422 或校验失败 |

### 6.6 事实记忆(FCT)

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| FCT-01 | 事实抽取 | 事件进入 facts 管线 | 自动 propose/commit;错误进 extraction_failures |
| FCT-02 | 事实冲突 | 同一实体 S+P 冲突 | 按 owner 限定处理 |
| FCT-03 | 检索隔离 | 跨用户/项目检索 | 用户隔离;项目单值覆盖全局事实 |
| FCT-04 | 遗忘联动 | 显式/自动遗忘 facts | 软删除+索引/cache 清理+孤立实体清理 |
| FCT-05 | 旧库迁移 | 无 user_id 旧 facts 库 | 加法迁移成功 |

### 6.7 遗忘模块(FOR)

依据:`forget_module_v1.md`

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| FOR-01 | 精确 ID 删除 | target_memory_ids 指定 | 软删除(status=deleted)+审计记录 |
| FOR-02 | 范围删除 | target_scope 指定 | 按 scene/task_type/app 批量定位删除 |
| FOR-03 | 自然语言 | instruction="忘掉周报格式偏好" | 规则关键词定位;级联清理 |
| FOR-04 | 级联一致性 | 删除后检查 SQLite/向量/缓存/证据/conflicts/facts | 全部同步清理 |
| FOR-05 | 自动遗忘 | 构造低健康度记忆触发 AutoForgetEngine | <0.2 归档、0.2~0.4 降级、0.4~0.6 待审查 |
| FOR-06 | 被动遗忘 | 检索含低健康度记忆 | 排序权重下降但数据保留 |
| FOR-07 | 遗忘历史 | 多次遗忘后 GET /forget/history | 记录完整(user 隔离) |

### 6.8 检索链路(RET)

依据:`INTERFACE.md` 5.2、`ARCHITECTURE.md` 3/8、`DATA_FLOW_UPDATE.md`

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| RET-01 | 混合加权 | 构造三路可区分数据 | final=0.6V+0.3K+0.1M 正确 |
| RET-02 | 向量引擎 | FAISS 与 Milvus/milvus_mock 切换 | 结果一致;app_id 缺失时报错 |
| RET-03 | BM25 关键词 | 精确词查询 | 命中;jieba 分词正确 |
| RET-04 | scope/置信度过滤 | context 与 min_confidence | 不相关场景与低置信度被过滤 |
| RET-05 | 重排序 | 相关性/scope/新鲜度/健康度因子 | 排序合理 |
| RET-06 | LRU 缓存 | 同请求二次查询、TTL 过期、失效 | 命中直接返回;invalid 后重查 |
| RET-07 | /context | 查询并注入 | 返回可拼接 prompt 文本,含偏好/流程 |
| RET-08 | 访问统计 | 检索命中 | last_accessed_at/access_count_30d 更新 |
| RET-09 | 空库/空查询 | 无数据或空 query | 返回空结果不报错 |

### 6.9 生命周期(LIF)

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| LIF-01 | 层级分类 | 不同质量/次数事件 | SHORT/MID/LONG 判定正确 |
| LIF-02 | 升级条件 | 出现次数≥2 且 quality≥0.4;≥5 且 confidence≥0.7 且≥3 天 | 按阈值升级 |
| LIF-03 | 过期归档 | 构造超期记忆 | archived,不再参与检索 |

### 6.10 持久化与恢复(PER)

| 编号 | 测试项 | 关键步骤 | 期望结果 |
|------|--------|----------|----------|
| PER-01 | SQLite 表结构 | 建库后检查 8 张业务表+新扩展列 | 与 INTERFACE.md 6.1 一致 |
| PER-02 | 重启恢复 | 写入→重建进程→查询 | 数据不丢;FAISS/证据链可加载 |
| PER-03 | 证据链 JSONL | 写入/追加/删除 | 每 memory_id 一个文件,行格式正确 |
| PER-04 | 向量落盘 | 保存/加载 FAISS 索引 | id_map/reverse_map 一致 |

---

## 7. REST API 契约测试(API)

覆盖全部端点:正向(200/201/204)、参数校验(422)、身份(403/503)、
不存在(404)、乐观并发(409)、稳定错误码。列表:

| 方法 | 路径 | 测试要点 |
|------|------|----------|
| GET | `/api/memory/health` | 200,服务状态 |
| POST | `/api/memory/events` | 见 EVT |
| POST | `/api/memory/search` / `/context` | 见 RET |
| GET | `/api/memory/preferences[/{id}[/versions]]` | 列表/详情/版本链,scene/status 过滤 |
| GET | `/api/memory/knowledge[/{id}]` | 列表/详情,type 过滤 |
| GET | `/api/memory/conflicts`;POST `/{id}/resolve` | 列表/手动解决 |
| POST | `/api/memory/feedback` | confirm/update/reject 三种动作 |
| POST | `/api/memory/memories/preference`、`/knowledge` | 手工新增记忆 |
| POST | `/api/memory/forget`;GET `/forget/history` | 见 FOR |
| GET | `/api/memory/facts`、`/facts/conflicts`、`/facts/{id}`、`/facts/{id}/evidence`;DELETE `/facts/{id}` | 事实管理 |
| GET/POST | `/api/memory/extraction/tasks`、`/metrics`、`/run`、`/{task_id}/retry` | 重试闭环 |
| CRUD | `/api/memory/safety/user-rules` | 见 SEC-15~17 |
| POST | `/api/memory/evaluate/{task_name}`;GET `/evaluate/reports` | 评测运行与报告 |

## 8. 前端控制台测试(CONSOLE)

依据:`前端功能规划.md`。PyQt6 桌面应用,启动 `console/main.py`,手工验证:

| 编号 | 页面 | 测试要点 |
|------|------|----------|
| CS-01 | Dashboard | 总览卡片计数正确,接口正常 |
| CS-02 | 偏好管理 | 列表/筛选/详情/版本链/状态修改 |
| CS-03 | 知识管理 | 列表/筛选/详情(步骤、工具链、成功率) |
| CS-04 | 冲突处理 | 卡片展示、手动选择 4 种决策生效 |
| CS-05 | 检索测试 | 输入/场景选择/结果+延迟展示 |
| CS-06 | 遗忘管理 | 自然语言遗忘、目标确认、历史记录 |
| CS-07 | 评测报告 | 4 项指标卡片、历史报告 |
| CS-08 | 异常容错 | 后端未启动时页面友好报错不崩溃 |

## 9. 集成与端到端(E2E)

| 编号 | 场景 | 步骤 | 期望 |
|------|------|------|------|
| E2E-01 | 记忆学习闭环 | 写 feedback → 检索召回 | 召回 Markdown 偏好 |
| E2E-02 | 冲突覆盖闭环 | 先 Markdown 后 Word | pref_001 archived,新版本 active |
| E2E-03 | 遗忘闭环 | 学习→遗忘→再检索 | 不再召回;forget_history 有记录 |
| E2E-04 | 千问 Agent | `examples/run_qwen_agent.py` 两轮执行 | 第二轮 memory_context 含第一轮偏好 |
| E2E-05 | opencode/Claude 集成 | 按 `opencode-integration`、`claudecode-integration` 文档验证 | 事件自动沉淀、检索回灌 |
| E2E-06 | 麒麟原生链路 | 真实 .so+Milvus 部署 | embedding/向量全链路走麒麟 SDK |
| E2E-07 | 重启不丢 | 写入→重启服务→检索 | 记忆恢复 |

## 10. 性能与并发(PERF)

| 编号 | 测试项 | 方法 | 预期 |
|------|--------|------|------|
| PF-01 | 检索延迟 | `evaluation/metrics/latency_benchmark.py` | 记录基线,满足目标预算 |
| PF-02 | 全链路基准 | `evaluation/metrics/full_chain_benchmark.py` | 写→检索→遗忘整链耗时 |
| PF-03 | 并发写入 | 多线程并发 POST /events | 无死锁、数据一致(WAL) |
| PF-04 | 大规模检索 | 数据集构建指南(`docs/retrieval/2026-08-10_*`) | 延迟/召回率指标 |
| PF-05 | 评测脚本 | `evaluation/run_retrieval_eval.py`、milvus benchmark 脚本 | 指标可复现 |

## 11. 缺陷分级与退出标准

| 级别 | 定义 | 处理 |
|------|------|------|
| 阻断(S1) | 安全门禁失效、数据丢失、服务无法启动、原文/密钥泄漏 | 必须修复后回归 |
| 严重(S2) | 核心功能(P0 范围)错误、接口契约破坏 | 本版本修复 |
| 一般(S3) | 非核心功能缺陷、体验问题 | 可下一版本 |
| 轻微(S4) | 文案/样式/优化建议 | 视情况处理 |

**测试完成条件:**
1. 全部 P0 用例通过(安全 19 项 + 事件 8 项 + API 契约);
2. 阻断级缺陷 0,严重缺陷全部关闭;
3. 回归基线保持 ≥ 590 通过、2 跳过;
4. 无敏感信息泄漏类缺陷。

## 12. 交付物

1. 本测试计划;
2. 测试用例明细表(可按编号扩展为用例管理工具格式);
3. 缺陷记录(编号+级别+复现步骤);
4. 测试报告(通过率、覆盖模块、性能数据、遗留问题)。

## 13. 执行清单(建议顺序)

1. 运行回归基线:`pytest tests -q`(目标 590 passed, 2 skipped);
2. 启动服务(port 8010),冒烟:health + events + search;
3. 按 6.1 安全专项 → 6.2 事件 → 6.3~6.9 核心模块 → 7 API 契约;
4. 前端 8 项(8 章)→ 端到端 7 项(9 章);
5. 性能与评测(10 章);
6. 汇总报告。
