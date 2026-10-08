# Architecture Decision Records

A selection of Torvi's decisions, each with the context that forced it. Status: **Implemented**, **Accepted** (decided, scheduled) or **Superseded**.

| ID | Decision | Status |
|---|---|---|
| [ADR-001](#adr-001) | No hard-coded society — resolve tenant from identity | Implemented |
| [ADR-002](#adr-002) | Enforce roles in Lambda code, not only in the prompt | Implemented |
| [ADR-003](#adr-003) | Per-society table isolation | Accepted |
| [ADR-005](#adr-005) | Hash phone numbers as keys | Superseded by ADR-013 |
| [ADR-007](#adr-007) | Society owns its data; defined exit terms | Accepted |
| [ADR-008](#adr-008) | One tools Lambda with an internal router | Implemented |
| [ADR-012](#adr-012) | Keep the vector store in-region | Accepted |
| [ADR-013](#adr-013) | PII vault: tokenisation + KMS + field-level encryption | Accepted |
| [ADR-015](#adr-015) | Capture consent at first interaction | Accepted |
| [ADR-016](#adr-016) | Classify data before designing encryption | Implemented |
| [ADR-018](#adr-018) | Admin writes move to a web console; WhatsApp is read-only | Implemented |
| [ADR-019](#adr-019) | Admin login with WhatsApp OTP via Cognito custom auth | Implemented |
| [ADR-020](#adr-020) | Append-only payments; ledger is a derived view | Implemented |
| [ADR-021](#adr-021) | Explicit `adjustment` and month lifecycle on the ledger | Implemented |
| [ADR-022](#adr-022) | Resolve role and society server-side on every request | Implemented |
| [ADR-023](#adr-023) | Compute analytics on read (v1) | Implemented |

---

<a id="adr-001"></a>
### ADR-001 · No hard-coded society — resolve tenant from identity
**Context.** An early build read the society ID from an environment variable. That ties one deployment to one society.
**Decision.** Society is resolved from the authenticated identity on every request.
**Consequence.** Onboarding a society is data, not a deployment.

<a id="adr-002"></a>
### ADR-002 · Enforce roles in Lambda code, not only in the prompt
**Context.** A system prompt saying "only admins may record payments" can be talked around by prompt injection or simply ignored by the model.
**Decision.** The webhook sets `role` and `flat_no` as Bedrock session attributes from the database. Every tool checks them as its first statement and exits before any data access if they don't allow the action.
**Consequence.** Defence in depth: the prompt and the code enforce independently, and only the code is relied on. Aligned with OWASP LLM Top 10 (excessive agency, insecure output handling).

<a id="adr-003"></a>
### ADR-003 · Per-society table isolation
**Context.** A shared table relies on every query getting its filter right, forever.
**Decision.** Each society can have its own tables, selected through a resolver.
**Consequence.** A missing filter can't leak across tenants. Offboarding is a table delete. DynamoDB table limits are far above the expected society count.

<a id="adr-005"></a>
### ADR-005 · Hash phone numbers as keys — *Superseded*
**Context.** Raw phone numbers were the identity table's partition key.
**Decision (original).** Store HMAC-SHA256(phone) as the key.
**Why superseded.** Further research showed hashing is weak protection for a low-entropy value like a phone number, AWS guidance discourages it for PII keys, and DPDP Rules 2025 expect encryption. Caught before any code was written. Replaced by ADR-013.

<a id="adr-007"></a>
### ADR-007 · Society owns its data; defined exit terms
**Decision.** 90 days' notice, full export within 24 hours, deletion within 30 days. Payment records archived for 7 years as required by Indian accounting and GST rules. Same terms apply if Torvi shuts down.
**Consequence.** Export and offboarding are product features, not support tickets.

<a id="adr-008"></a>
### ADR-008 · One tools Lambda with an internal router
**Context.** One Lambda per tool multiplies deployments, IAM roles, log groups and cold starts.
**Decision.** A single tools Lambda dispatches on `event["function"]`. Long-running jobs (broadcasts, media transcription) stay separate because their timeouts differ.
**Consequence.** Shared warm pool, one place for shared helpers like session parsing.

<a id="adr-012"></a>
### ADR-012 · Keep the vector store in-region
**Context.** Society documents (bye-laws, vendor lists) can contain personal data.
**Decision.** Consolidate retrieval on Bedrock Knowledge Bases with a vector store in ap-south-1.
**Consequence.** All resident data, including embeddings, stays in India.

<a id="adr-013"></a>
### ADR-013 · PII vault: tokenisation + KMS + field-level encryption
**Decision.**
1. KMS customer-managed key with rotation, every decrypt logged in CloudTrail.
2. A vault table holds the phone number encrypted (AES-256-GCM) under an opaque token, with an HMAC index used only for lookup.
3. All other tables reference the token, never the phone.
4. Financial fields encrypted client-side with the AWS Database Encryption SDK.

**Consequence.** The raw phone is decrypted in memory only to send a WhatsApp reply or to export on offboarding — both audited.

<a id="adr-015"></a>
### ADR-015 · Capture consent at first interaction
**Decision.** First contact shows a short privacy notice and waits for explicit agreement; the timestamp is stored with the identity record.
**Consequence.** Evidence of consent for DPDP compliance, designed in rather than retrofitted.

<a id="adr-016"></a>
### ADR-016 · Classify data before designing encryption
**Decision.** Tier 1 critical PII (phone, message content) → encrypt and tokenise. Tier 2 financial (balances, amounts, mode) → field-level encryption. Tier 3 non-PII (flat number alone, month, status) → plaintext for queries.
**Consequence.** Controls match risk; query performance isn't sacrificed where it doesn't need to be.

<a id="adr-018"></a>
### ADR-018 · Admin writes move to a web console; WhatsApp is read-only
**Context.** Recording payments by chat meant an LLM sat in the middle of every financial write — the largest prompt-injection surface in the system. Chat is also a poor fit for tables, bulk entry and charts.
**Decision.** Payments, reversals, expenses, month close, residents and export move to an authenticated console. After a two-week parallel run, write tools are removed from the agent.
**Consequence.** The agent becomes read-only. A new deployable (SPA + API).

<a id="adr-019"></a>
### ADR-019 · Admin login with WhatsApp OTP via Cognito custom auth
**Context.** SMS OTP in India requires DLT registration; admins already live on WhatsApp.
**Decision.** Cognito custom auth with define/create/verify triggers; the code is sent as a WhatsApp authentication template. Admin-created users only, strict attempt and send limits, no enumeration.
**Consequence.** Cognito handles signing, refresh and revocation. Trade-off accepted: admin phone numbers are also held in Cognito.

<a id="adr-020"></a>
### ADR-020 · Append-only payments; ledger is a derived view
**Context.** The first version updated a balance in place and kept only the last transaction ID. Retries could double-count, and history was lossy.
**Decision.** Every receipt and reversal is its own item. The ledger update, an idempotency marker and the audit entry are written in one `TransactWriteItems`, conditioned on the ledger's previous `amount_received`.
**Consequence.** Retries are no-ops, races fail safely, reversals are new entries, and a 7-year record exists by construction.

<a id="adr-021"></a>
### ADR-021 · Explicit `adjustment` and month lifecycle
**Context.** Five years of Excel didn't reconcile cleanly: carry-forward broke at a society-wide re-baseline and in a few individual rows.
**Decision.** Store the difference in an explicit `adjustment` field rather than rewriting history. Months move open → payments → expenses → close (equal split to the paisa) → next month opens.
**Consequence.** One invariant holds for every row; closed months are immutable.

<a id="adr-022"></a>
### ADR-022 · Resolve role and society server-side on every request
**Decision.** The token proves only who the caller is. Role, status and society are re-read from the database on each call; no custom claims.
**Consequence.** Removing an admin takes effect on their next request.

<a id="adr-023"></a>
### ADR-023 · Compute analytics on read (v1)
**Context.** About 50 ledger rows per society per year.
**Decision.** Aggregate in the API (collection efficiency, ageing buckets, expense mix, month-on-month flags) and chart client-side. No warehouse.
**Consequence.** Zero extra infrastructure. Revisit with a precomputed summary at ~10 societies.
