# SEC 专项验收测试结果记录

对应 `docs/0811功能性测试/TEST_PLAN.md` 6.1 安全模块专项(SEC-01~19),实现为 `tests/test_sec_acceptance.py`。

## 执行结果

- 运行命令:`pytest tests/test_sec_acceptance.py -q`
- 结果:**53 passed**,0 failed,0 skipped(2026-08-11 全量复跑通过)
- 覆盖:19 个 SEC 项,53 个用例,全部通过

| 编号 | 用例数 | 结果 | 关键断言 |
|------|-------|------|----------|
| SEC-01 | 3 | 通过 | `load_builtin_rule_set(version="1.0")` 加载内置 catalog;规则带 `standard_ref`(RuleSourceLink);规则来源可追溯 |
| SEC-02 | 2 | 通过 | 递归扫描 text/payload 深层嵌套/tool_calls 均命中;事件本身不被修改 |
| SEC-03 | 3 | 通过 | id_card 走校验器(有效 `11010519491231002X`);api_key 需 `api_key=xxx` 形式;credential_field 命中 payload/password 等字段名 |
| SEC-04 | 3 | 通过 | 超深/超大/超节点数抛稳定错误码 `scan.limit.max_depth` / `max_field_chars` / `max_total_bytes` / `max_nodes`,不含原文 |
| SEC-05 | 2 | 通过 | 全角/零宽字符/NFKC 组合均命中,span 反投影正确 |
| SEC-06 | 2 | 通过 | 决策优先级 REJECT>REVIEW>MASK>ALLOW |
| SEC-07 | 2 | 通过 | 覆盖不能削弱;普通覆盖不得 ALLOW |
| SEC-08 | 3 | 通过 | 仅低风险(IPv4)上下文可配 ALLOW 例外;过期/缺字段拒绝;凭据不可放行 |
| SEC-09 | 1 | 通过 | MASK 后无残留;二次 scan → ALLOW 且 `sanitized_event` 逐字节一致(幂等) |
| SEC-10 | 2 | 通过 | SafetyResult 含 attestation;跨实例/手工构造不匹配即失败关闭 |
| SEC-11 | 2 | 通过 | 追加/截尾/改中段均被哈希链检出 |
| SEC-12 | 1 | 通过 | 轮转+时间老化后 `enforce_retention()` 生成 anchor,verify 从 anchor 校验后缀 |
| SEC-13 | 3 | 通过 | REVIEW 事件进隔离区,磁盘仅 AES-256-GCM 密文;到期拒绝解密;错 key 拒绝解密 |
| SEC-14 | 3 | 通过 | 审计追加失败/回执无效时写操作全部阻断,只抛稳定错误码 |
| SEC-15 | 2 | 通过 | CRUD 完整(含软删除);matcher 永不回显;stale revision 冲突拒绝 |
| SEC-16 | 2 | 通过 | `mask_match` 在写入管线内脱敏;`drop_event` 整条 REJECT 不落库 |
| SEC-17 | 3 | 通过 | matcher 密文存储、view 无明文;错 master_key 打开后规则不可读(fails-closed);文件服务往返一致 |
| SEC-18 | 2 | 通过 | 各类异常仅返回稳定错误码,无敏感原文/密钥 |
| SEC-19 | 8 | 通过 | production 模式配置 mock/faiss/milvus_mock 启动被拒;strict_permissions/fsync 等不可关闭 |

## 修改内容

### 测试实现:`tests/test_sec_acceptance.py`(新增,19 个 Test 类)

按真实实现 API 编写,修复过程中对齐到的关键事实:

1. **规则库**:`load_builtin_rule_set(version="1.0")` 为 keyword-only 参数;内置规则是 `RuleDefinition`,溯源字段为 `.standard_ref`(RuleSourceLink: source_id/role/locator)。
2. **例外(exemption)**:`SafetyPolicyException` 的 `field_paths` 位于 `SafetyExceptionScope` 内而非顶层;`expires_at` 必须晚于真实运行时间(报告 `scanned_at` 用真实 now,非测试固定时钟,用 `2099-01-01`);高危规则 ALLOW 例外在构造 `SensitiveDetector` 时即抛 `ValueError`。
3. **审计**:段文件名为 `safety-audit-{index:08d}.jsonl`;`enforce_retention()` 无参数,按构造时 `retention_days`;anchor 由"时间老化(os.utime) + enforce_retention"生成,之后 `verify().anchored` 才为 True。
4. **隔离区**:`ReviewQuarantineStore.put()` 的 `audit_id` 为必填 keyword-only,测试改为经 `SafetyWriteGate(...).route()` 触发 REVIEW 获得 `audit_id`;明文检查需 rglob 全部文件(密文文件为二进制)。
5. **用户规则**:`delete_rule()` 需 `expected_revision`;`UserRuleView` 无 `matcher` 字段(写-only,用 `hasattr` 断言);`ADVANCED_REGEX` 构造 `UserRuleService` 需 `allow_advanced_regex=True`。
6. **fails-closed**:错误 master_key 打开 sqlite 服务不抛异常,而是 `list_rules()` 返回空、`get_rule` 抛 `UserRuleError`。
7. **脱敏幂等**:二次扫描期望 ALLOW + `sanitized_event.model_dump(json)` 完全一致,而非再次 MASK。

### 状态

- `tests/test_sec_acceptance.py` 当前为未跟踪新增文件(尚未提交)。
