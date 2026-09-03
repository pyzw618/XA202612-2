# MemoryHub vNext Event Gateway

S1-03 freezes the canonical ingress order:

```text
vnext/v1 Envelope
  → identity check
  → Scope check
  → injected Policy processor
  → ALLOW/MASK commit, or REVIEW/REJECT stop
  → tenant-scoped idempotency + Event commit
```

`EventGateway` requires an explicit Policy processor; there is no implicit
allow-by-default implementation. The processor returns the governed event,
so a MASK path persists only its sanitized payload. REVIEW and DROP/REJECT
return a safe status without writing the event body, idempotency row, queue
entry or ordinary log.

The commit transaction writes only the vNext Event extension and
`idempotency_records`. Working, Episode, Candidate and Long-Term changes are
downstream canonical services, avoiding a second state machine in the ingress.
Idempotency is keyed by `(tenant_id, idempotency_key)` and stores only a request
hash plus event/trace references; raw payload is never copied into the record.
An unchanged payload on a `MASK` result is rejected fail-closed. If concurrent
submissions race on a unique key, the losing transaction is rolled back and
reconciled as `IDEMPOTENT` or `CONFLICT`; it is not surfaced as a storage error.

The legacy `EventIngestionService` remains a compatibility path until S1-08
assembles the full Canonical Write Service. REST/MCP/CLI/SDK adapters must use
the assembled service before the vNext flag is enabled.
