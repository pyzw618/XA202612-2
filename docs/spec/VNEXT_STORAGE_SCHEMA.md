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

Every new table carries `tenant_id`, `user_id`, a vNext version field and
appropriate status/version checks. Candidate rows are explicitly marked
`formation_status=CANDIDATE`; they are not ordinary retrieval authority rows.

`Database.init_schema()` is additive and idempotent: `create_all()` creates new
tables, `_ensure_compatible_schema()` adds missing columns/indexes to existing
SQLite databases, and no legacy table is dropped or rewritten. Existing event,
evidence, lineage and outbox rows retain nullable compatibility columns while
new vNext services must supply tenant/user and version values.

Rollback is feature-flag based: set `vnext.mode=legacy`, stop using the new
tables, and retain them for inspection/retry. Dropping tables or deleting old
columns is deliberately outside this migration and requires a separately
approved, backed-up release step.
