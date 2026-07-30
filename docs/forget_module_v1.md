# 遗忘模块第一版实现总结

## 1. 设计目标

本版遗忘模块覆盖三种遗忘场景：

1. **显式遗忘**：用户主动要求删除某条/某类记忆。
2. **自动遗忘**：系统定时根据健康度对记忆进行降级/归档。
3. **被动遗忘**：检索时降低低健康度记忆的排序权重，使其自然淡出。

设计原则：

- 先跑通链路，再迭代算法复杂度。
- 所有数据库相关操作先以伪代码 + 注释标记，待存储层完善后替换。
- 不物理删除，优先软删除（状态变更），保证可审计、可恢复。

---

## 2. 改动文件清单

| 文件 | 改动内容 |
|------|----------|
| `memoryhub/adapter/schemas.py` | `PreferenceMemory` / `KnowledgeMemory` 新增健康度字段；`ForgetRequest` 新增 `target_memory_ids` 和 `cascade` |
| `memoryhub/storage/models.py` | `PreferenceRow` / `KnowledgeRow` 新增 `health_score`, `stability`, `last_accessed_at`, `access_count_30d` |
| `memoryhub/core/forget/health.py` | 新增 `HealthCalculator`，计算时间衰减 + 使用频率 |
| `memoryhub/core/forget/auto_forget.py` | 新增 `AutoForgetEngine`，按健康度阈值自动归档/降级 |
| `memoryhub/core/forget/forgetter.py` | 新增 `MemoryForgetter`，支持精确 ID、范围、自然语言三种模式 |
| `memoryhub/core/forget/__init__.py` | 模块入口 |
| `memoryhub/core/safety/forget.py` | 改为兼容入口，真实实现指向 `memoryhub.core.forget.forgetter` |
| `memoryhub/core/lifecycle/manager.py` | 生命周期检查引入健康度因子 |
| `memoryhub/retrieval/reranker.py` | 重排序加入健康度因子，实现被动遗忘 |

---

## 3. 显式遗忘实现

### 3.1 入口类

```python
from memoryhub.core.forget import MemoryForgetter

forgetter = MemoryForgetter(llm_client=llm, storage=db, vector_store=vs, cache=cache)
result = forgetter.execute(request)
```

### 3.2 三种模式

| 模式 | 触发条件 | 实现方式 |
|------|----------|----------|
| 精确 ID | `target_memory_ids` 非空 | 直接按 ID 删除 |
| 范围删除 | `target_scope` 非空 | 调用 `_locate_by_scope()`，按 `scope_scene / task_type / app` 批量查询 |
| 自然语言 | `instruction` 非空 | 调用 `_locate_by_keywords()`，基于规则关键词匹配定位 |

### 3.3 意图解析

`parse_intent()` 第一版基于规则实现：

- 根据关键词推断 `memory_type`：
  - 偏好：`偏好`、`喜欢`、`习惯`、`preference` 等
  - 知识：`知识`、`工作流`、`流程`、`模板`、`knowledge` 等
- 提取 `target_keywords`：去停用词、去标点、过滤短词
- 确定 `match_strategy`：`exact` / `scope` / `semantic`

### 3.4 删除流程

```text
用户请求
   │
   ▼
parse_intent → 确定 match_strategy
   │
   
locate_memories → 返回 target_memory_ids
   │
   ▼
delete_memories → 软删除（status='deleted'）
   ├─ 清理向量索引（PSEUDO-FAISS）
   ├─ 清理检索缓存（PSEUDO-CACHE）
   └─ 标记关联冲突记录（PSEUDO-DB）
   │
   ▼
create_audit_log → 写入 forget_history（PSEUDO-DB）
```

### 3.5 关键代码位置

- `memoryhub/core/forget/forgetter.py`

---

## 4. 自动遗忘实现

### 4.1 健康度计算

`HealthCalculator.calculate()` 使用两个核心因子：

```text
health = 0.6 * time_decay + 0.4 * usage_frequency
time_decay = exp(-days / stability)
stability = max(1, base_stability * (1 + access_count_30d / 10))
usage_frequency = min(1, access_count_30d / 5)
score = min(score, confidence)
```

- `time_decay`：基于 Ebbinghaus 遗忘曲线，离上次访问越久衰减越快。
- `usage_frequency`：近期被使用次数越多，记忆越健康。
- `confidence`：置信度作为上限兜底。

### 4.2 自动遗忘策略

`AutoForgetEngine.run()` 扫描所有 `active` 记忆：

| 健康度区间 | 动作 |
|-----------|------|
| `< 0.2` | 归档（`status='archived'`） |
| `0.2 ~ 0.4` | 降级（`long → mid → short`） |
| `0.4 ~ 0.6` | 标记为待审查（`status='pending'`） |
| `>= 0.6` | 保持活跃 |

### 4.3 关键代码位置

- `memoryhub/core/forget/health.py`
- `memoryhub/core/forget/auto_forget.py`
- `memoryhub/core/lifecycle/manager.py`

---

## 5. 被动遗忘实现

### 5.1 实现方式

在 `Reranker.rerank()` 中，将原始分数、相关性、场景匹配度、新鲜度、健康度融合：

```text
final_score = 0.5 * 原始分数
            + 0.2 * 相关性
            + 0.1 * 场景匹配
            + 0.1 * 新鲜度
            + 0.1 * 健康度
```

- 健康度低的记忆自然被排到后面。
- 不删除任何数据，对用户无感知。

### 5.2 已实现的辅助方法

- `_compute_relevance_score(query, content)`：关键词 Jaccard 重叠度
- `_compute_scope_score(result, request)`：`scene/task_type/app` 字段匹配度
- `_compute_freshness_score(result)`：基于 `updated_at` 的时间衰减

### 5.3 关键代码位置

- `memoryhub/retrieval/reranker.py`

---

## 6. API 路由实现

### 6.1 已实现端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/memory/forget` | `POST` | 接收 `ForgetRequest`，调用 `MemoryForgetter.execute()` |
| `/api/memory/forget/history` | `GET` | 返回用户遗忘操作历史（目前返回空列表，待 DB 完成后接入） |

### 6.2 使用示例

```python
import requests

requests.post("/api/memory/forget", json={
    "user_id": "default",
    "instruction": "忘掉我关于周报格式的偏好",
    "target_memory_ids": [],
    "target_scope": None,
    "cascade": True,
})
```

### 6.3 关键代码位置

- `memoryhub/adapter/api.py`

---

## 7. 数据模型变更

### 7.1 Pydantic Schemas

```python
class PreferenceMemory(BaseModel):
    ...
    health_score: float = 1.0
    stability: float = 1.0
    last_accessed_at: datetime | None = None
    access_count_30d: int = 0

class KnowledgeMemory(BaseModel):
    ...
    health_score: float = 1.0
    stability: float = 1.0
    last_accessed_at: datetime | None = None
    access_count_30d: int = 0

class ForgetRequest(BaseModel):
    user_id: str = "default"
    instruction: str = ""
    target_memory_ids: list[str] = []
    target_scope: SceneScope | None = None
    cascade: bool = True
```

### 7.2 SQLAlchemy ORM

```python
class PreferenceRow(Base):
    ...
    health_score = Column(Float, default=1.0, index=True)
    stability = Column(Float, default=1.0)
    last_accessed_at = Column(DateTime, nullable=True)
    access_count_30d = Column(Integer, default=0)

class KnowledgeRow(Base):
    ...
    health_score = Column(Float, default=1.0, index=True)
    stability = Column(Float, default=1.0)
    last_accessed_at = Column(DateTime, nullable=True)
    access_count_30d = Column(Integer, default=0)
```

---

## 8. 待替换的伪代码

所有数据库相关操作都以 `# PSEUDO-DB:`、`# PSEUDO-FAISS:`、`# PSEUDO-CACHE:` 标记，例如：

```python
# PSEUDO-DB: 从数据库读取所有 status = active 的记忆（preferences + knowledge）
active_memories = []

# PSEUDO-DB: UPDATE preferences/knowledge SET status='archived', health_score=? WHERE memory_id=?

# PSEUDO-FAISS: self.vector_store.delete(memory_id)

# PSEUDO-CACHE: self.cache.invalidate(memory_id)
```

---

## 9. 未完成工作清单

### 9.1 显式遗忘

| 序号 | 待完成项 | 说明 |
|------|----------|------|
| 1 | 自然语言 LLM 解析 | `parse_intent()` 目前是规则实现，需接入 LLM 提取更准确的主题、时间范围、置信度阈值 |
| 2 | 语义检索定位 | `_locate_by_keywords()` 目前是基础关键词匹配，需接入 `embed() → FAISS search` |
| 3 | scope 范围查询 | `_locate_by_scope()` 已预留 SQL 模板，待 DB 完成后替换伪代码 |
| 4 | 候选确认机制 | 自然语言删除前应先返回候选列表，用户确认后再执行 |
| 5 | 物理删除任务 | 软删除后需要定时任务做物理清理 |
| 6 | 版本链处理 | 删除记忆时，其 `parent_id` 链上的后续版本是否一并删除，需要提示用户 |
| 7 | 证据链清理 | `events` 表中引用该记忆的证据摘要需要清理或标记 |
| 8 | 冲突记录清理 | `conflicts` 表中关联记录需要标记为 `cleaned` |

### 9.2 自动遗忘

| 序号 | 待完成项 | 说明 |
|------|----------|------|
| 1 | 定时任务调度 | `AutoForgetEngine.run()` 需要被 APScheduler / cron 调用 |
| 2 | 访问统计更新 | 检索/使用命中时需要更新 `last_accessed_at` 和 `access_count_30d` |
| 3 | 健康度持久化 | `health_score` 计算后需要写回数据库 |
| 4 | 完整多因子模型 | 引入冲突惩罚、用户反馈、内容质量等因子 |
| 5 | FSRS/SM-2 接入 | `stability` 目前只是简单放大系数，可替换为间隔重复算法 |

### 9.3 被动遗忘

| 序号 | 待完成项 | 说明 |
|------|----------|------|
| 1 | `SearchResult.metadata` 注入 | `health_score`、`updated_at`、`scope` 等需要从数据库/检索层注入到 `SearchResult.metadata` |
| 2 | 相关性算法升级 | `_compute_relevance_score()` 目前是基础 Jaccard，可替换为 LLM 打分或交叉编码器 |
| 3 | 权重调优 | `rerank()` 中 0.5/0.2/0.1/0.1/0.1 的权重需要根据评测数据调优 |

### 9.4 基础设施

| 序号 | 待完成项 | 说明 |
|------|----------|------|
| 1 | 数据库实现 | 所有 `# PSEUDO-DB:` 需要替换为 `SQLAlchemy` 查询/更新 |
| 2 | FAISS 向量删除 | 所有 `# PSEUDO-FAISS:` 需要替换为真实的 `VectorStore.delete()` |
| 3 | 缓存失效 | 所有 `# PSEUDO-CACHE:` 需要替换为真实的 `cache.invalidate()` |
| 4 | 依赖注入 | `_get_forgetter()` 目前是 PSEUDO-INIT，待全局依赖容器完成后替换 |
| 5 | 健康度查询接口 | 文档中提到的 `POST /api/memory/health` 尚未实现 |
| 6 | 组件启动初始化 | `app.py` 的 `startup()` 还没有实例化 `MemoryForgetter`、`AutoForgetEngine` |
| 7 | 测试覆盖 | 显式遗忘、自动遗忘、被动遗忘均缺少单元测试和集成测试 |

### 9.5 生命周期管理

| 序号 | 待完成项 | 说明 |
|------|----------|------|
| 1 | `LifecycleManager` 具体实现 | `classify`、`should_promote`、`promote`、`should_expire`、`expire`、`run_lifecycle_check` 仍是 `NotImplementedError` |
| 2 | 健康度与生命周期联动 | `run_lifecycle_check()` 需要实际读取 DB、计算健康度、执行升级/降级/归档 |

---

## 10. 后续迭代方向

1. **自然语言遗忘**：接入 LLM 意图解析 + 语义检索，返回候选列表供确认。
2. **多因子健康度**：引入冲突惩罚、用户反馈、内容质量等更多因子。
3. **FSRS/SM-2 间隔重复**：将 `stability` 替换为类 FSRS 模型，动态调整复习间隔。
4. **物理删除任务**：增加定时任务，将软删除超过一定期限的记忆物理清理。
5. **访问统计**：在检索/使用命中时更新 `last_accessed_at` 和 `access_count_30d`。
6. **评测闭环**：针对遗忘模块设计评测指标（误删率、召回率、健康度准确性）并跑通测试。
