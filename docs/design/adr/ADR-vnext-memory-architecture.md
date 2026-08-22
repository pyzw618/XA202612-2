# ADR-vnext-memory-architecture

- Status: Accepted for vNext implementation
- Date: 2026-08-22
- Scope: S0-02; applies to S0-S5 vNext work
- Version: `vnext/v1`

## Context

The repository already has a working legacy path, but it is not yet the
vNext architecture described by the execution plan:

- `memoryhub/adapter/schemas.py` is the current shared v1 DTO module and
  still exposes legacy `MemoryLevel` values for compatibility.
- `memoryhub/core/memory_write.py` and
  `memoryhub/core/domain_writer.py` provide the existing transactional
  preference/knowledge write path with Evidence, Lineage and Projection
  Outbox records.
- `memoryhub/adapter/service.py` provides a persistent vertical slice and
  `memoryhub/adapter/api.py` can select an application retriever or a
  service fallback.
- `memoryhub/retrieval/hybrid.py` and
  `memoryhub/retrieval/milvus_hybrid.py` are channel implementations, not
  independent business authorities.
- SQLite/SQLAlchemy rows are durable records; vector, BM25 and cache data
  are derived and must be replaceable. Legacy short/mid tables remain
  compatibility storage until the vNext migration is complete.

Without an explicit boundary, a new endpoint could write a long-term row or
an index directly, while a projection or retrieval path could become a
second source of truth. That would make shadow comparison, rollback,
tenant isolation and Forget verification non-deterministic.

## Decision

### 1. Authority and Projection

The Authority Store is the only source of durable business truth. It owns
identity, tenant/user scope, content version, lifecycle/evolution status,
Evidence, Lineage, idempotency and Forget tombstones.

Vector, BM25, cache and other retrieval artifacts are Projections. They may
be deleted and rebuilt from Authority. A Projection MUST carry the target
`memory_id` and `content_version`; an older projection event MUST NOT
overwrite a newer version or revive a deleted object.

During migration, the existing Preference/Knowledge repositories remain the
legacy Authority adapter. New vNext tables and repositories become the
vNext Authority implementation behind the same application service. No
second Authority write store is introduced.

### 2. Canonical Write Path

All production writes follow this sequence:

```text
REST/MCP/CLI/SDK/worker adapter
  -> request normalization and identity/scope binding
  -> Policy/Safety gate
  -> idempotency check
  -> Canonical Write Service
  -> Working/Episode/Candidate domain transitions
  -> Authority transaction (business object + Evidence + Lineage + Outbox)
  -> asynchronous Projection
```

The existing `MemoryWriteService`/`DomainMemoryWriter` is reused and
extended as the long-term commit boundary. Compatibility adapters may
translate old DTOs, but they must not reproduce extraction, conflict,
promotion or projection algorithms.

### 3. Canonical Retrieval Path

All search and context requests follow one application service:

```text
REST/MCP/CLI/SDK adapter
  -> MemoryRetrievalRequest normalization
  -> Intent Router and Retrieval Planner
  -> authorized multi-channel recall
  -> fusion/rerank
  -> Authority validity and Scope conflict resolution
  -> Context budget and Context Builder
  -> Activation/Retrieval Trace
```

`HybridRetriever` and `MilvusHybridRetriever` remain infrastructure/channel
implementations. They cannot decide lifecycle, Forget, tenant or Scope
authority on their own. A compatibility endpoint may adapt the response
shape, but must call the same Retrieval Service.

### 4. Layer and dependency rules

The intended dependency direction is:

```text
interfaces/adapters -> application services -> domain contracts
                                      -> infrastructure ports
infrastructure implementations -> infrastructure ports
```

The following calls are explicitly forbidden in production code:

| Caller | Forbidden dependency/call | Required alternative |
|---|---|---|
| REST/MCP/CLI/SDK handler | direct long-term repository save, Vector/BM25 query, or prompt/context assembly | Canonical Write/Retrieval Service |
| Retrieval implementation | mutate Authority, Candidate, Evolution or Forget state | return typed candidates; application service records Activation/Trace |
| Reflection/model adapter | write Long-Term Authority or Projection | return validated Candidate with model metadata |
| Projection/Repair worker | infer or rewrite Authority from index contents | read Authority, then project/delete the checked version |
| Dashboard/diagnostic read | bypass tenant/actor authorization or expose raw sensitive正文 | authorized management service with redaction/audit |
| Compatibility adapter | copy business algorithms or create a second writer | translate DTO and delegate |
| Domain module | import FastAPI, SQLAlchemy repositories or concrete vector SDKs | domain contracts and ports |

Event, Evidence and Trace payloads are subject to Policy before persistence;
ordinary Trace records use IDs, hashes, classifications and scores rather
than unredacted正文.

### 5. Compatibility, rollout and rollback

The rollout modes are ordered and independently switchable:

1. `legacy`: old result path; vNext disabled.
2. `shadow`: vNext computes and records differences only.
3. `dual-read`: Authority single-write; old and vNext retrieval are read for
   comparison; old result is returned.
4. `canary`: 5%/25%/50% reads return vNext after safety gates pass.
5. `vnext`: all reads return vNext; old read compatibility window remains.

Rollback switches read/Formation behavior back to a previously validated
path. It does not delete or rewrite correct Authority data. If a Projection
is invalid, rebuild it from Authority and switch an index alias; if a Schema
change is involved, use the migration's compatibility read and rollback
procedure. Policy leakage, cross-tenant results, deleted/superseded content
in Context, or Forget residuals are automatic stop conditions.

### 6. Versioning and review gate

All vNext contracts use `vnext/v1`. `schema_version` describes wire/schema
shape; `content_version` describes business content changes. Any change to
Scope precedence, status meaning, Authority ownership or API semantics
requires a new ADR entry and corresponding contract/migration evidence.

This ADR is reviewed against the repository facts above by
`tests/test_vnext_architecture_adr.py` and remains the boundary reference
for S0-03 through S5-10.

## Consequences

Positive consequences:

- Authority remains recoverable when indexes, cache or workers fail.
- REST, MCP, CLI and SDK can converge without duplicated business logic.
- Shadow, dual-read, canary and rollback have a stable ownership model.
- Security and Forget checks occur before derived data can become visible.

Costs and constraints:

- Existing legacy paths need adapters and staged migration.
- Projection reads may be partially degraded while Authority checks or
  rebuilds run.
- A task is not complete if it only adds an endpoint or index without
  updating the canonical application service and evidence.

## Rejected alternatives

- **Vector DB as Authority:** rejected because it cannot provide the required
  version, lineage, tombstone and transactional semantics.
- **One writer per interface:** rejected because it creates divergent
  versions and makes rollback unsafe.
- **Direct Reflection-to-Long-Term:** rejected because a model output lacks
  the required Evidence, Policy, Scope and promotion decision.
- **Big-bang legacy replacement:** rejected because the plan requires
  reversible shadow, dual-read and canary rollout.
