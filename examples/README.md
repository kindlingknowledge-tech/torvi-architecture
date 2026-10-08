# Examples

Short excerpts that show the patterns described in [`docs/`](../docs). They are simplified from production code — configuration, retries, logging and most error handling are trimmed — and are **not deployable**.

| File | Pattern |
|---|---|
| `webhook_pipeline.py` | Ordered inbound checks before any model call; server-set session attributes |
| `tool_access_control.py` | Tool-side authorisation using session attributes; internal function router |
| `payment_transaction.py` | Four-item DynamoDB transaction: idempotency, append-only payment, guarded ledger update, audit |
