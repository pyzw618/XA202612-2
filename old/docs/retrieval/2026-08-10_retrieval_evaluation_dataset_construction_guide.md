# MemoryHub 检索评测数据构建指南

> 配套文档：`2026-08-10_retrieval_performance_evaluation_plan.md`  
> 目标：构建可复现、可人工复核的知识检索 dev/test/latency 数据集  
> 核心原则：测试集用于客观验收，不能为了达到 Recall@5 ≥85% 而反向修改样本

---

## 1. 最终需要交付的文件

建议目录：

```text
evaluation/datasets/
├── memoryhub_knowledge_retrieval_v1_dev.json
├── memoryhub_knowledge_retrieval_v1_test.json
├── memoryhub_retrieval_latency_v1.json
├── memoryhub_retrieval_dataset_schema_v1.json
├── memoryhub_retrieval_annotation_guideline_v1.md
├── memoryhub_retrieval_annotation_records_v1.jsonl
└── SHA256SUMS.txt
```

各文件用途：

| 文件 | 用途 |
|---|---|
| `*_dev.json` | 调整检索权重、阈值和索引参数 |
| `*_test.json` | 冻结后的最终 Recall/NDCG 验收集 |
| `*_latency.json` | 不重复的冷查询性能测试集 |
| `*_schema_v1.json` | 自动校验字段、枚举和必填项 |
| `*_annotation_guideline_v1.md` | 标注标准和正反例 |
| `*_annotation_records_v1.jsonl` | 两名标注者的独立判断及裁决结果 |
| `SHA256SUMS.txt` | 冻结数据集和规范的完整性校验值 |

原始材料如包含真实用户信息、密码、API Key、内部地址或其他敏感数据，不得进入评测数据集和 Git 仓库。

---

## 2. 推荐规模与分布

### 2.1 开发集

- 500～1,000 条记忆；
- 100～200 条查询；
- 允许用于调参；
- 可以混合人工样本和模板生成样本。

### 2.2 最终测试集

- 总索引规模：10,000 条记忆；
- 核心人工整理知识：至少 500 条；
- 独立查询：建议 300～500 条；
- 每条查询直接相关记忆：1～5 条；
- test 集冻结后禁止继续用于调参。

### 2.3 知识类型建议

| 类型 | 核心知识占比 | 示例 |
|---|---:|---|
| workflow | 40% | 周报生成流程、代码发布流程 |
| case | 30% | 某次故障排查、历史任务执行案例 |
| template | 30% | 周报模板、评审清单、邮件模板 |

另外加入 preference、fact、旧版本、archived、deleted 和跨用户知识作为干扰项。

### 2.4 查询难度建议

| 难度 | 占比 | 说明 |
|---|---:|---|
| exact | 15% | 查询包含标题或关键术语 |
| semantic | 35% | 同义改写，不直接复制记忆原文 |
| hard-negative | 25% | 存在词面相似但语义不相关的干扰项 |
| cross-domain | 15% | 同一关键词出现在不同场景或项目中 |
| no-answer | 10% | 索引中不存在相关知识 |

至少覆盖中文、英文、中英混合、口语表达、缩写和少量合理错别字。

---

## 3. 数据来源

数据可来自以下三类来源。

### 3.1 人工编写的典型任务

根据比赛场景整理常见桌面 Agent 任务，例如：

- 办公：周报、会议纪要、日程、邮件、文档整理；
- 开发：代码评审、构建、发布、故障排查；
- 系统：软件安装、文件检索、系统设置；
- 知识复用：历史案例、工作流和模板调用。

人工样本质量最高，应作为核心 test 集主要来源。

### 3.2 脱敏后的历史案例

如果使用真实历史任务，必须先：

1. 删除姓名、电话、证件号、地址和账号；
2. 将组织名、项目名、服务器地址替换成虚构值；
3. 删除密码、Token、Cookie、API Key和私钥；
4. 由第二人复核脱敏结果；
5. 记录来源类别，不保留可反向识别用户的信息。

### 3.3 模板生成的扩容和干扰数据

模板生成适合把索引规模扩展到10,000条，但不能替代人工标注的核心知识和查询。

模板生成时应：

- 固定随机种子；
- 保存生成器版本和参数；
- 避免简单复制查询关键词；
- 生成跨用户、跨项目、旧版本和近似主题干扰项；
- 生成后做去重和敏感信息扫描。

---

## 4. 构建记忆记录

每条知识记忆至少包含：

```json
{
  "id": "know_001",
  "user_id": "user_001",
  "memory_type": "knowledge",
  "knowledge_type": "workflow",
  "name": "项目周报生成流程",
  "content": "根据日历、项目记录和文件整理本周周报",
  "steps": ["查日历", "收集项目文件", "整理进展", "生成 Markdown"],
  "tools": ["calendar", "file_search", "document_writer"],
  "template_body": "",
  "scope": {
    "scene": "office",
    "task_type": "office.weekly_report",
    "app": "agent"
  },
  "project_id": "project_a",
  "status": "active",
  "version": 1
}
```

构建要求：

- ID全局唯一且稳定；
- workflow至少包含2个有效步骤；
- case包含任务背景、执行过程和结果；
- template包含可替换变量或明确结构；
- `user_id`、scope和project不能全部使用同一个值，否则无法验证隔离；
- archived/deleted记录必须保留为干扰项，但不能被检索为有效结果；
- 新旧版本必须建立清晰关联，并标明哪个版本为active。

---

## 5. 构建查询

### 5.1 先选目标，再写查询

每条有答案查询按以下顺序构建：

1. 从记忆池选择1～5条真正需要召回的目标；
2. 明确用户、场景、项目和期望记忆类型；
3. 用自然语言重新表述需求；
4. 不直接复制目标记忆标题或全文；
5. 为查询加入至少一个合理干扰项；
6. 标注难度和语言。

禁止先写大量查询，再通过当前系统返回结果反向决定 relevant IDs。

### 5.2 查询记录示例

```json
{
  "query_id": "q_001",
  "user_id": "user_001",
  "query_text": "按之前的方式生成这周周报",
  "context": {
    "scene": "office",
    "task_type": "office.weekly_report",
    "app": "agent"
  },
  "project_id": "project_a",
  "memory_types": ["knowledge"],
  "difficulty": "semantic",
  "language": "zh-CN",
  "relevance": {
    "know_001": 3,
    "know_017": 1
  },
  "notes": "know_001为可直接执行的流程；know_017仅主题相似"
}
```

### 5.3 Mixed查询单独标注

对于“按上次方式生成周报”这类同时需要偏好和知识的查询，不要把它混入 knowledge-only 主指标。建议增加：

```json
{
  "memory_types": ["preference", "knowledge"],
  "expected_by_type": {
    "preference": ["pref_001"],
    "knowledge": ["know_001"]
  }
}
```

报告时分别计算 preference recall、knowledge recall和两类均命中的joint success rate。

### 5.4 无答案查询

无答案查询的 `relevance` 为空，但不能在 Recall计算中自动记为满分。它们应单独用于计算：

- 空结果正确率；
- 误召回率；
- 高置信错误结果比例。

---

## 6. 相关性标注

使用0～3级相关性：

| 等级 | 定义 |
|---:|---|
| 0 | 无关或因用户/scope/project/status不匹配而不可用 |
| 1 | 主题相关，但不能直接满足当前请求 |
| 2 | 可以部分满足请求，或是有用的补充知识 |
| 3 | 直接相关，可以完整回答或执行请求 |

指标口径：

- Recall relevant集合：等级≥2；
- NDCG：使用完整0～3级标注；
- owner/scope/project错误的记忆即使文本完全一致也标0；
- archived/deleted和被新版本替代的记录通常标0。

### 标注流程

1. 为每条查询建立候选池：目标候选、BM25候选、向量候选和随机负例；
2. 两名标注者独立评分，不查看系统最终融合分数；
3. 计算 weighted Cohen's Kappa；
4. 分歧样本由第三人裁决；
5. 保存两份原始评分和最终评分；
6. Kappa过低时先修订标注规范，再重新标注。

建议一致性目标：weighted Cohen's Kappa ≥0.75。

---

## 7. 干扰项构造

每条核心查询至少加入以下一种干扰：

- 同关键词、不同含义；
- 同主题、不同项目；
- 同内容、不同用户；
- 旧版本与新版本；
- active与archived/deleted；
- workflow与template标题近似；
- 中英文名称不同但语义相同；
- 包含敏感词但与查询任务无关。

示例：目标是“公司 Wi-Fi连接流程”，干扰项可以包括家庭Wi-Fi偏好、Wi-Fi密码安全规则和其他用户的公司网络配置。

---

## 8. 数据清洗与自动校验

冻结前必须执行以下检查：

### 8.1 结构检查

- ID不存在重复；
- query引用的memory ID全部存在；
- 枚举值合法；
- workflow/case/template必填字段完整；
- `user_id`、scope、project和status字段齐全；
- test查询不与dev查询重复。

### 8.2 内容检查

- 完全重复和高相似重复检测；
- 查询不得直接复制目标全文；
- relevant数量为1～5，无答案查询除外；
- 每个分组达到最低样本量；
- 检查异常长文本、空文本和乱码；
- 扫描API Key、密码、Token、私钥和个人信息。

### 8.3 指标检查

- 不允许空relevant查询在Recall中自动得1分；
- Recall@K、Precision@K、MRR、NDCG使用固定单元测试验证；
- 输出按类型、难度、语言和scope的样本分布；
- 生成数据集统计摘要供人工复核。

建议提供统一命令：

```bash
python evaluation/validate_retrieval_dataset.py \
  --dataset evaluation/datasets/memoryhub_knowledge_retrieval_v1_test.json \
  --schema evaluation/datasets/memoryhub_retrieval_dataset_schema_v1.json \
  --report evaluation/results/dataset_validation_report.json
```

该命令是目标接口；如果脚本尚未存在，应由评测开发同学先实现并增加自动测试。

---

## 9. dev/test/latency拆分与冻结

### 9.1 拆分原则

- 同一任务模板的近似改写尽量放在同一split，避免泄漏；
- 同一历史案例的不同版本不能跨dev/test；
- 先按任务族分组，再做分层拆分；
- test集比例建议30%～40%，且各知识类型和难度分布稳定；
- latency集使用独立查询文本，不与正式质量查询完全相同。

### 9.2 冻结步骤

1. 完成结构、内容、敏感信息和标注校验；
2. 固化数据集版本号；
3. 记录生成器Git commit和随机种子；
4. 生成SHA-256；
5. 将test集设为只读或纳入评测发布包；
6. 后续任何修改都必须提升版本号并重新生成校验值。

Linux示例：

```bash
sha256sum \
  evaluation/datasets/memoryhub_knowledge_retrieval_v1_dev.json \
  evaluation/datasets/memoryhub_knowledge_retrieval_v1_test.json \
  evaluation/datasets/memoryhub_retrieval_latency_v1.json \
  > evaluation/datasets/SHA256SUMS.txt
```

---

## 10. 延迟查询集构建

延迟集用于制造稳定冷查询，不能只重复同一批文本。

建议准备至少10,000条查询，来源如下：

- 40%：在质量查询基础上生成语义等价但文本不同的改写；
- 20%：短查询；
- 20%：中长查询；
- 10%：中英混合；
- 10%：无答案或长尾查询。

要求：

- 查询文本尽量唯一；
- 预热查询与正式查询分开；
- 每条查询携带完整user/context/project/memory_types；
- cold阶段不得提前调用正式查询；
- vector_hot和result_hot阶段可复用同一查询，但必须独立报告。

---

## 11. 构建工作分工

| 工作 | 建议负责人 | 交付物 |
|---|---|---|
| 场景和任务清单 | 产品/业务 | 任务覆盖表 |
| 核心知识编写 | 业务+开发 | 500条核心知识 |
| 扩容和干扰生成 | 评测开发 | 生成器、参数、种子 |
| 查询编写 | 业务+测试 | 300～500条质量查询 |
| 双人标注 | 两名独立标注者 | 原始标注JSONL |
| 分歧裁决 | 第三名复核者 | 最终relevance |
| 清洗和校验 | 评测开发 | 校验脚本和报告 |
| 冻结发布 | 评测负责人 | 数据集、SHA-256、版本说明 |

---

## 12. 完成标准 Checklist

- [ ] dev/test/latency三个数据集齐全；
- [ ] test集至少包含300条独立查询；
- [ ] 核心知识覆盖workflow/case/template；
- [ ] 每条有答案查询包含1～5个等级≥2的相关项；
- [ ] 无答案查询已单独标记；
- [ ] owner/scope/project/status干扰项齐全；
- [ ] 两名标注者独立完成标注；
- [ ] 一致性指标和分歧裁决已记录；
- [ ] 没有dev/test任务族泄漏；
- [ ] 敏感信息扫描通过；
- [ ] schema和引用完整性校验通过；
- [ ] 数据集版本、生成参数、Git commit和SHA-256已记录；
- [ ] test集冻结后未再用于调参；
- [ ] 数据集统计摘要经第二人复核。
