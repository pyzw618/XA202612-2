# MemoryHub vNext Trace Contract

## Scope

The observability trace is a redacted diagnostic projection, not an Authority
store. It contains identifiers, hashes, classifications, scores and timing;
it must never contain raw memory body, event payload, claim, excerpt, query or
embedding data.

## Five correlated chains

| Category | Typical span kinds | Mandatory associations |
|---|---|---|
| `FORMATION` | EVENT, WORKING, EPISODE, CANDIDATE, CONSOLIDATION | `trace_id`, `event_id`, optional `task_id`/`candidate_id` |
| `EVOLUTION` | EVOLUTION, LEGACY | `trace_id`, `event_id`, `candidate_id`, `memory_id` |
| `RETRIEVAL` | RETRIEVAL | `trace_id`, `query_id`, optional `task_id`, selected memory IDs only where already governed |
| `FORGET` | FORGET outcome | `trace_id`, `request_id`, hashed affected-memory list; always redacted |
| `INFRASTRUCTURE` | INFRASTRUCTURE | `trace_id`, safe operation IDs and outcome only |

Tenant and user IDs are mandatory on every span. Diagnostics must filter both
before returning a chain. Parent span IDs provide ordering where an upstream
span is available; `trace_id` is the cross-system join key.

## Sampling and retention

Normal successful traces are deterministically sampled from `sha256(trace_id)`
at the configured 10% rate, so a replay selects the same trace. High/critical
risk, failed/denied/error, and all Forget traces are sampled at 100%.

Normal sampled traces retain for 7 days. Mandatory/elevated traces retain for
30 days. `TraceStore.purge_expired()` removes only expired diagnostic spans;
it never affects Authority, Evidence, Lineage, Outbox or projection records.

## Redaction invariant

`TraceSpan` validates nested `ids`, `hashes` and `classification` mappings and
rejects content-bearing fields (`content`, `text`, `payload`, `claim`,
`excerpt`, `raw_query`, `query`, `embedding`). Inputs needing correlation are
represented by stable IDs or SHA-256 hashes. Dashboard and diagnostics default
to redacted data and must require management authorization for access.
