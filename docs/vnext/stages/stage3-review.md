# stage3-review.md

# Stage 3 Final Review — Feedback 闭环独立审查

## 1. Review 定位

本 Review 必须在 Stage 3 所有 Batch 完成后，由新的 Codex 会话独立执行。

Review 会话：

```text
只读
```

不得修改代码。

不得因为：

```text
PROGRESS.md = DONE
```

就直接认定 Stage 3 完成。

必须基于：

- 真实代码
- 真实调用链
- 真实测试
- 真实 Scenario

逐条验证。

---

# 2. Review 前置输入

必须阅读：

```text
docs/vnext/VNEXT_PLAN.md
docs/vnext/stages/stage3-feedback.md
docs/vnext/PROGRESS.md
Stage 2 Closure Final Review
```

确认 Stage 2 已：

```text
READY FOR STAGE 3
```

---

# 3. 核心 Review 问题

Review 必须回答：

1. `USED` 是否真实存在，不只是枚举。
2. USED 是否与 retrieval_id / memory_id 绑定。
3. IN_CONTEXT 是否被错误当作 USED。
4. Feedback Event 是否真实进入系统。
5. Task Success / Failure 是否经过 Attribution。
6. 多 Memory 场景是否保守归因。
7. Recall frequency 是否仍被错误用于 utility 增长。
8. Utility / Stability 是否真实更新。
9. duplicate feedback 是否幂等。
10. EvolutionService 是否真实接入。
11. negative feedback 是否可能直接 hard delete。
12. forget 后是否可能被 feedback 恢复。
13. cross-user / project / tenant feedback 是否隔离。
14. Stage 1 / Stage 2 是否回归。

---

# 4. 必查调用链

Review 必须给出真实链路：

```text
Retrieval
  ↓
Activation
  ↓
Context
  ↓
Agent
  ↓
Usage Feedback
  ↓
USED
  ↓
Outcome
  ↓
Attribution
  ↓
Utility / Stability
  ↓
Evolution
```

如果其中任何一段仍是：

```text
stub
shadow-only
mock-only
not wired
```

必须明确标记。

---

# 5. Activation Review

逐项验证：

| 状态 | 结果 |
|---|---|
| RECALLED | PASS / FAIL |
| SELECTED | PASS / FAIL |
| IN_CONTEXT | PASS / FAIL |
| USED | PASS / FAIL |

必须说明：

- 状态在哪写入
- 如何关联 retrieval_id
- 如何关联 memory_id
- 如何做 idempotency

---

# 6. Feedback Attribution Review

必须至少验证：

- Explicit Positive
- Explicit Negative
- Task Success
- Task Failure
- Multiple Used Memories
- IN_CONTEXT but not USED

重点确认：

```text
Task Success
≠
all context memories positive
```

以及：

```text
Task Failure
≠
all used memories negative
```

---

# 7. Utility / Stability Review

必须验证：

1. old score
2. feedback
3. attribution confidence
4. update weight
5. new score

并检查：

```text
min/max bounds
```

以及：

```text
duplicate feedback
```

是否只更新一次。

---

# 8. Evolution Review

必须验证：

```text
ACTIVE → DORMANT
DORMANT → ACTIVE
```

并检查：

```text
SUPERSEDED
```

是否需要 replacement evidence。

必须确认：

```text
negative feedback
```

不会直接：

```text
hard delete
```

---

# 9. Scope / Safety Review

必须真实测试：

```text
tenant A feedback
不能修改 tenant B
```

```text
user A feedback
不能修改 user B
```

```text
project A feedback
不能修改 project B project-scoped memory
```

同时测试：

```text
forgotten memory
```

不会被 feedback 重新激活。

---

# 10. Scenario Review

逐条输出：

| Scenario | Result | Evidence |
|---|---|---|
| A Positive Explicit | PASS / FAIL / SKIP | |
| B Explicit Correction | PASS / FAIL / SKIP | |
| C Single Used Success | PASS / FAIL / SKIP | |
| D Multi Memory Success | PASS / FAIL / SKIP | |
| E Unrelated Failure | PASS / FAIL / SKIP | |
| F Memory-caused Failure | PASS / FAIL / SKIP | |
| G Repeated Positive | PASS / FAIL / SKIP | |
| H Dormant Reactivation | PASS / FAIL / SKIP | |
| I Forget Protection | PASS / FAIL / SKIP | |
| J Cross Scope | PASS / FAIL / SKIP | |
| K Duplicate Feedback | PASS / FAIL / SKIP | |
| L Illegal USED | PASS / FAIL / SKIP | |

SKIP 不算 PASS。

---

# 11. Regression Review

必须运行：

```text
Stage 1 Formation regression
Stage 2 Retrieval regression
Stage 3 targeted tests
Legacy Retrieval regression
Scope isolation
Forget / Safety critical tests
```

输出精确：

```text
passed
failed
skipped
deselected
```

---

# 12. Final Verdict 规则

只有以下条件全部满足：

- Stage 3 关键 DoD PASS
- A-L 核心 Scenario 真实执行
- 无关键 Scope Leak
- 无 Forget resurrection
- 无 Stage 1 / Stage 2 关键回归
- Feedback 幂等
- Negative feedback 不直接删除
- USED 真实接入

才可以输出：

```text
READY FOR STAGE 4
```

否则：

```text
NOT READY
```

---

# 13. Codex Final Review Prompt

```text
对 MemoryHub vNext Stage 3 做独立 Final Review。

先阅读：

- docs/vnext/VNEXT_PLAN.md
- docs/vnext/stages/stage3-feedback.md
- docs/vnext/stages/stage3-review.md
- docs/vnext/PROGRESS.md
- Stage 2 Closure Final Review

不要修改任何代码。

不要相信 PROGRESS.md 中的 DONE 状态。

基于真实代码、调用链和测试逐条验证：

1. Activation RECALLED / SELECTED / IN_CONTEXT / USED
2. Usage feedback
3. Outcome feedback
4. Feedback attribution
5. Utility update
6. Stability update
7. Idempotency
8. Evolution
9. Negative feedback safety
10. Forget protection
11. Cross-user/project/tenant isolation
12. Stage 1 / Stage 2 regression
13. Scenario A-L

必须明确区分：

PASS
FAIL
PARTIAL
SKIP
NOT RUN

SKIP 不计为 PASS。

最终输出：

# Stage 3 Final Review

## 1. Final Verdict
READY FOR STAGE 4
或
NOT READY

## 2. Stage 3 DoD
逐条 PASS / FAIL / PARTIAL

## 3. Real Feedback Architecture
给出真实调用链

## 4. Activation Verification

## 5. Attribution Verification

## 6. Utility / Stability Verification

## 7. Evolution Verification

## 8. Scope / Safety Verification

## 9. Scenario A-L Results

## 10. Regression

## 11. Test Evidence
精确 passed / failed / skipped / deselected

## 12. Remaining Risks

## 13. Final Recommendation

不要修改代码。
```
