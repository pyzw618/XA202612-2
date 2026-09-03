# MemoryHub vNext Golden Fixtures

Golden fixture version: `vnext/golden/v1`.

`tests/fixtures/vnext/golden_scenarios.json` freezes the contract cases needed
before implementation work begins:

| Case | Contract assertion |
|---|---|
| `normal` | `vnext/v1` retrieval request and Authority-checked mode |
| `conflict` | Two scoped Candidate claims remain `REVIEW` and are not promoted |
| `sensitive` | Sensitive event is `REVIEW` and carries only a `content_ref` |
| `duplicate` | Same event/idempotency retry creates no new evidence |
| `expired_version` | Old API version fails closed with `VERSION_CONFLICT` |
| `deleted` | `DELETED` Long-Term content is excluded from ordinary retrieval |
| `degraded_response` | Partial response exposes degraded channel and warning |

The tests validate every case with the public vNext Pydantic/API contracts. The
fixture contains no real secret or raw sensitive content. Changes require a new
fixture version and an updated SHA-256 entry in `SHA256SUMS.txt`.
