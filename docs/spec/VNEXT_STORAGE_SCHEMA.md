# MemoryHub vNext Storage Schema

S1-01 adds the Authority-side task and retrieval tables without treating the
legacy short/mid tables as vNext state:

| Table | Authority responsibility | Main safety key |
|---|---|---|
| `working_states` | current task state and CAS version | tenant/user/task unique |
| `task_episodes` | resumable episode snapshot | tenant/user indexes, status check |
| `episode_events` | append-only episode stream | tenant/episode/sequence unique |
| `memory_candidates` | formation staging only | candidate status/formation checks |
| `memory_activations` | retrieval activation audit | tenant/user/query/memory/version unique |
| `retrieval_logs` | trace-safe retrieval summary | tenant/user/query/trace indexes |
| `idempotency_records` | request deduplication | tenant/idempotency key unique |

Every new Authority table carries `tenant_id`, `user_id`, a vNext version field
and appropriate status/version checks. Candidate rows are explicitly marked
`formation_status=CANDIDATE`; they are not ordinary retrieval authority rows.

S6-03 adds three additive observability tables. They are diagnostic projections,
not Authority data:

| Table | Contents | Retention rule |
|---|---|---|
| `observability_traces` | Redacted spans plus indexed trace/task/event/memory/query IDs, tenant, category, status and expiry | Normal sampled success 7 days; error, denied, high-risk Policy, Forget and evaluation traffic 30 days |
| `observability_metrics` | Full-count aggregate counters with bounded numeric timing samples and the same correlation dimensions | Aggregate rows are retained during diagnostic cleanup; they are never sampled away |
| `observability_audits` | Redacted Forget/management/Dashboard access audit with actor, target, correlation IDs, status and expiry | Elevated audit retention, independently purgeable |

`Database.init_schema()` creates these tables and their lookup indexes through
the same additive `create_all()` plus `_ensure_compatible_schema()` migration
path. Existing databases receive missing columns and indexes only; no Authority,
Evidence, Lineage, Outbox or Projection row is deleted. Trace and Audit purge
operates only on expired diagnostic rows, while Metric aggregate counts remain
available across restarts.

`Database.init_schema()` is additive and idempotent: `create_all()` creates new
tables, `_ensure_compatible_schema()` adds missing columns/indexes to existing
SQLite databases, and no legacy table is dropped or rewritten. Existing event,
evidence, lineage and outbox rows retain nullable compatibility columns while
new vNext services must supply tenant/user and version values.

Rollback is feature-flag based: set `vnext.mode=legacy`, stop using the new
tables, and retain them for inspection/retry. Dropping tables or deleting old
columns is deliberately outside this migration and requires a separately
approved, backed-up release step.
