# Error Handling And Observability Standard

Use this standard for production-facing repositories. Keep it practical: the
goal is diagnosable failures without leaking sensitive data or turning normal
user interruptions into noisy incidents.

## Core Rules

- Do not use force-unwrapping, panic-style shortcuts, or equivalent runtime
  crash paths for recoverable production failures.
- Avoid silent `catch {}`, broad `except`, or ignored promise rejections on
  stateful paths unless the failure is intentionally ignorable and documented.
- Throw or return typed/domain errors from service, transport, and integration
  layers when practical.
- Catch at feature, route, job, app-state, or UI boundaries.
- Distinguish cancellation, validation, permission, not-found, provider failure,
  and unexpected internal failure.

## User-Facing Errors

- Use calm, non-technical copy.
- Do not expose stack traces, SQL, provider payloads, environment names,
  credential names, tokens, or internal exception text.
- Tell the user what happened and what they can do next when action is possible.

## Operator-Facing Diagnostics

Unexpected recoverable failures and 5xx paths should log structured context:

- `request_id` or correlation id when available.
- `feature`, `route`, `job`, or `action`.
- Safe entity ids when useful.
- Provider/integration name when applicable.
- Outcome such as `recoverable`, `service_failure`, `validation_failed`, or
  `internal_error`.

Never log secrets, access tokens, auth artifacts, invite codes, raw customer
payloads, private files, or unnecessary PII.

## API Expectations

- Validation/auth/permission/not-found paths should return typed 4xx responses.
- Unexpected server failures should return safe public response bodies and log
  details internally.
- API responses should include or propagate a request id where practical.

## Client Expectations

- Cancellation should usually return quietly.
- Local persistence corruption should prefer log + recover over silent failure.
- State-loss paths should record enough context to reconstruct the failure.
- UI should map domain errors to safe user messages at the presentation layer.

## Review Checklist

- [ ] No silent stateful failures.
- [ ] No secrets, tokens, customer data, or private payloads in logs.
- [ ] User-facing errors are calm and non-technical.
- [ ] Unexpected failures carry request/action/context metadata.
- [ ] Cancellation is not treated as an incident.
- [ ] Tests or smoke checks cover changed error paths when practical.
