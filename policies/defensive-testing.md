# Optional defensive testing policy

Consuming repositories choose whether to adopt these scenarios and which are
applicable. This policy does not activate a check or require enforcement. The
repository owns the real invariant, test data, expected response, test command,
and any documented exception. Keep tests behavioral rather than searching for
implementation text or merely executing lines.

| Boundary | Positive and negative scenarios to select |
| --- | --- |
| Authentication and authorization | Anonymous, expired-session, wrong-role, and permitted callers; sensitive routes reject privilege escalation |
| Tenant/resource access | A valid foreign resource ID cannot cross tenant boundaries in reads, writes, exports, jobs, or downloads |
| Input validation | Missing, malformed, oversized and boundary values; unknown fields where prohibited; safe error responses |
| Integrations and jobs | Timeouts, bounded retries, duplicate/out-of-order events, idempotency conflicts, and cancellation |
| Persistence and concurrency | Concurrent updates preserve invariants; failed transactions do not leave partial state; migrations work against representative prior data |
| Error handling and diagnostics | Public failures conceal internals; logs redact secrets and unnecessary personal data; correlation context survives failures |
| Resource consumption | Pagination, uploads, archive expansion, query cost, queue concurrency, and request sizes have defined limits |
| SDK contracts | Serialization round trips, malformed payloads, version compatibility, and representative consuming-app builds |

Exercise the actual route, service, database, job, or client boundary needed to
prove the behavior. A unit test of an isolated access helper does not establish
end-to-end isolation. Where practical, demonstrate that removing the defensive
condition makes the regression test fail. Do not report a case as covered
because a file, scanner rule, prompt, or review checklist exists.

See [error handling](error-handling.md), [testing](testing.md), and the
[runnable recipes](../docs/standards/optional-quality-checks.md). Static rules
and AI reviews can supplement these tests; their presence does not prove the
runtime guarantee.
