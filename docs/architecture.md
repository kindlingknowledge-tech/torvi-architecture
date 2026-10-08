# Architecture

## 1. Context

| Actor | Channel | Can do |
|---|---|---|
| Resident | WhatsApp | Ask about own dues, payment history, common expenses, vendor contacts |
| Admin (secretary, treasurer) | WhatsApp + admin console | Everything a resident can, plus record payments and expenses, close months, manage residents, view analytics |
| Operator (Torvi) | AWS console | Infrastructure only. No routine access to society financial data |

External systems: Meta WhatsApp Cloud API, Amazon Bedrock, and (planned) a UPI payment gateway.

## 2. Components

### Resident path (WhatsApp)

| Component | Responsibility |
|---|---|
| **Webhook Lambda** | Single entry point behind a Lambda Function URL. Verifies Meta's HMAC signature, deduplicates retries, rate-limits, filters known prompt-injection phrases, resolves the sender's flat and role from DynamoDB, then invokes the agent. Returns 200 to Meta quickly. |
| **Bedrock Agent** | Claude Haiku 4.5 running a ReAct loop. Chooses tools, interprets results, replies in the resident's language. Receives `flat_no`, `role` and `society_id` as session attributes set by the webhook — never from the message text. |
| **Tools Lambda** | One Lambda with an internal router (`event["function"]`) for all agent tools. Every function checks role and flat from session attributes as its first step. |
| **Knowledge Base** | Bedrock KB over society documents (vendor directory, bye-laws, summaries). Financial data is deliberately *not* in the KB — it comes from DynamoDB through access-controlled tools. |

### Admin path (web console)

| Component | Responsibility |
|---|---|
| **React SPA** | Payments, expenses, month close, residents, analytics. Static on Cloudflare Pages with a per-deploy CSP. |
| **Cognito (custom auth)** | Passwordless login: a one-time code is sent through a WhatsApp authentication template. Admin-created users only. |
| **API Gateway + admin-api Lambda** | JWT authorizer on every route. The Lambda re-reads role, status and society from the database on every request, so revocation is immediate. |

### Data stores (DynamoDB, ap-south-1)

| Table | Key | Purpose |
|---|---|---|
| `ledger` | `flat_no` / `month` | Monthly balance per flat — the derived read model |
| `payments` | `society#flat` / `paid_at#id` | Append-only receipts and reversals (source of truth for money) |
| `expenses` | `society_id` / `month#category#id` | Monthly society expenses |
| `audit-log` | `society_id` / `ts#event_id` | Append-only; the API role has no update or delete permission |
| `phone-mapping` | phone (→ token, planned) | Identity: flat, role, society, consent |
| `message-dedup` | message or window key | Dedup, rate-limit counters, idempotency markers — all with TTL |

## 3. Request lifecycle — resident message

```
1. Meta POSTs the message to the webhook (HTTPS, signed).
2. Webhook verifies X-Hub-Signature-256 (HMAC-SHA256, constant-time compare). Bad → 403.
3. Conditional put of message_id (24h TTL). Already seen → 200, stop.
4. Atomic counter per phone per hour. Over limit → polite reply, stop.
5. Injection phrase filter. Match → generic reply, stop (agent never called).
6. Phone lookup. Unknown number → "ask your secretary to register you", stop (zero AI cost).
7. First message ever → welcome message.
8. invoke_agent(sessionAttributes = {flat_no, role, society_id}) — set by server.
9. Agent calls getDues → tool compares requested flat to session flat; resident asking
   for another flat gets access_denied before any query runs.
10. Reply sent through WhatsApp Cloud API with retry on 429/5xx.
```

Message text is processed in memory only and never persisted (GOV-002).

## 4. Request lifecycle — admin records a payment

```
1. Admin signs in: phone → WhatsApp OTP (5-min expiry, 3 attempts) → Cognito access token.
2. POST /payments with an Idempotency-Key header.
3. Authorizer validates the JWT; admin-api re-reads role, status, society_id.
4. Server-side validation: amount bounds, mode, reference for non-cash, month is open.
5. One TransactWriteItems call:
     • Put idempotency marker (bound to a hash of the request)
     • Put payment item
     • Update ledger row, conditioned on its previous amount_received
     • Put audit entry
6. Retry with the same key and body → same result. Same key, different body → 422.
```

## 5. Ledger model

```
balance = opening_balance + total_expenses − amount_received + adjustment
```

* Positive balance means the flat owes; negative means paid in advance.
* Next month's `opening_balance` = this month's `balance`.
* A month is `open` or `closed`. Closing splits each expense category equally across flats to the paisa (leftover paise go to the first flats) and opens the next month. Closed months are immutable; corrections are reversals or adjustments in the open month.
* Migrating five years of hand-kept Excel surfaced rows where carry-forward didn't reconcile. Instead of rewriting history, the difference is stored explicitly in `adjustment` (ADR-021).

## 6. Multi-tenancy

* `society_id` comes only from the server-side identity lookup — never from request input or token claims.
* Table names go through a resolver `table_for(society_id, kind)`. The pilot maps to shared tables; new societies can map to per-society tables (ADR-003) with no code change. An unknown society gets 403, never a default.
* Outbound notifications are filtered by society as well as flat.

## 7. Operations

* Infrastructure for the admin console is defined in AWS SAM; tables use PITR, SSE and `DeletionPolicy: Retain`.
* 90-day retention on every log group. Logs carry masked phone numbers (last three digits) and never OTPs or message bodies.
* CloudWatch alarms → SNS for OTP abuse, WhatsApp send failures, API error and 4xx spikes.
* Billing alarm on the account.
