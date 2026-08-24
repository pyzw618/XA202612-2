# FCT 专项验收测试结果记录

对应 `docs/0811功能性测试/TEST_PLAN.md` 6.6 事实记忆(FCT-01~05)。本次聚焦 **FCT-01 事实抽取**,新增 LLM 不可用时的确定性规则降级抽取,测试补在 `tests/test_fact/test_extractor.py::TestTripleExtractorRuleFallback`。

## 执行结果

- 运行命令:`pytest tests/test_fact/test_extractor.py -q`
- 结果:**14 passed**,0 failed,1 skipped(2026-08-11)
- facts 目录回归:`pytest tests/test_fact -q` → **52 passed,1 skipped**
- 全量回归:`pytest tests/ -q` → **693 passed,2 skipped,1 failed**
  - 唯一失败 `tests/test_sync_service.py::test_compensation_task_scans_and_syncs` 为后台补偿线程(interval 0.5s)的时序偶发问题,与本改动无关,单测隔离复跑 3/3 通过。

### FCT-01 降级抽取(8 用例)

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| FCT-01a | 1 | 通过 | 中文属性句 `X的Y是Z` 抽取,宾语类型判为 Person |
| FCT-01b | 1 | 通过 | 中文位置句 `X位于Y`,宾语类型判为 Location |
| FCT-01c | 1 | 通过 | 中文成立句 `X成立于Y`,宾语类型判为 Date |
| FCT-01d | 1 | 通过 | 英文 `X is the Y of Z` 主语/宾语互换(Z 为主语),宾语判为 Person |
| FCT-01e | 1 | 通过 | 英文 `located in` / `founded in` 多句共存不串词,标点正确剥离 |
| FCT-01f | 1 | 通过 | 降级置信度固定 0.7(保守) |
| FCT-01g | 1 | 通过 | 无规则可匹配时返回空并设置 `last_error`,propose() 可上报至 extraction_failures |
| FCT-01h | 1 | 通过 | 空文本不产生错误 |
| 链路验证 | - | 通过 | `FactMemoryPipeline.ingest()` 无 LLM 时正常 propose/commit,事实落库(见修改内容第 2 项) |

## 修改内容

### 新增:LLM 不可用时的事实抽取降级(FCT-01)

1. **`memoryhub/core/fact/extractor.py` — `TripleExtractor.extract()` 三级降级**
   原实现:无 LLM client 时直接捕获异常返回 `[]`,**不设置 `last_error`**,导致 `propose()` 静默丢弃事实——无 API key 的本地环境客观事实完全无法写入。现逻辑:
   - 空文本 → `[]`(不产生错误);
   - LLM 成功且有结果 → 直接返回;
   - LLM 无结果(空输出)→ 回退规则抽取;
   - LLM 抛异常 → 回退规则抽取;**仅当规则也无结果**才设置 `last_error`,使失败经 `propose()` 计入 extraction_failures,不静默吞掉。

2. **`memoryhub/core/fact/extractor.py` — 新增 `_rule_extract()` + `_RULE_PATTERNS`**
   确定性中英文模式(刻意保守,仅匹配带明确谓词锚点的陈述句,避免噪声三元组):
   - 中文:`X的(负责人|创始人|…|地址|邮箱|电话)是/为 Y`、`X位于/坐落于 Y`、`X成立于/创建于 Y`;
   - 英文:`X is the (ceo|founder|…) of Y`(主语/宾语互换)、`X is located/based in Y`、`X was founded/established in Y`;
   - 捕获组做句末标点剥离(`.。！？!?；;，,`)、英文模式 `re.IGNORECASE`、`is the X of` 句式自动交换主宾语;
   - 每条证据取匹配片段原文,置信度固定 0.7。

3. **`memoryhub/core/fact/extractor.py` — 新增 `_guess_entity_type()` 轻量实体类型启发式**
   日期(`19xx/20xx 年`、`yyyy-mm-dd`)、组织(公司/集团/大学/研究院/corp/inc 等关键词)、地点(市/省/区/国/city 等关键词或谓词含 `位于/located/based`)、人物(谓词为 负责人/ceo/founder 等),其余 Other。仅用于降级路径,不影响 LLM 路径的实体归一化。

### 测试实现(新增 1 类)

- `tests/test_fact/test_extractor.py` 新增 `TestTripleExtractorRuleFallback` 共 8 用例(FCT-01a~h)。
- 既有 `TestTripleExtractorParsing` / `TestTripleExtractorIntegration`(需真实 API key,跳过)不受影响;
- 既有 `tests/test_fact/test_pipeline_proposal.py` 使用 `FakeExtractor`,不受降级逻辑影响。

### 状态

- 修改文件 `memoryhub/core/fact/extractor.py`(未提交)。
- 新增测试用例写入既有文件 `tests/test_fact/test_extractor.py`(未提交)。
- 与既有回归语义对齐:LLM 路径行为完全不变,仅在"无 LLM / LLM 空输出"时新增回退;两者皆失败时 `last_error` 上报行为与 EVT-07 extraction_failures 约定一致。
