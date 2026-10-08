# Torvi — Architecture

> **A society that runs itself.**
> A WhatsApp-first AI assistant for Indian housing societies, built serverless on AWS with an LLM that never makes authorisation decisions.

**Live architecture site:** https://architecture.torvi.in  ·  **Product:** https://torvi.in  ·  **Author:** [Eswara Krishna Akurathi (KK)](https://krishnakumarakurathi.com)

This repository is the public reference for how Torvi is designed: the architecture, the decisions behind it, the security model, and short code excerpts that show the key patterns. The production code lives in a private repository.

---

## The problem

Indian housing societies run their finances on Excel sheets and WhatsApp groups. Residents ask the secretary "how much do I owe?" and wait. Secretaries chase payments by hand and keep the ledger by hand.

Torvi lets residents ask in plain language — English, Hindi, Telugu or a mix — on the WhatsApp they already use. No app, no login. Admins get a separate web console for the work that doesn't belong in chat.

```
Resident:  "What are my dues?"
Torvi:     "September dues: ₹2,500 pending for Flat 301."

Resident:  "mera paisa gaya?"
Torvi:     "✅ ₹2,500 received on 14 Sep."
```

**Pilot:** an 11-flat society in Hyderabad, live since April 2026, with five years of ledger history migrated from Excel.

---

## Architecture at a glance

```
 Resident (WhatsApp)                           Admin (browser)
        │                                             │
        ▼                                             ▼
 Meta WhatsApp Cloud API                     admin.torvi.in (React SPA)
        │ HTTPS webhook                              │ WhatsApp OTP → Cognito JWT
        ▼                                             ▼
 ┌──────────────────────────────┐            API Gateway (JWT authorizer)
 │ Webhook Lambda               │                     │
 │  1 HMAC signature check      │                     ▼
 │  2 Message dedup             │            admin-api Lambda
 │  3 Rate limit                │             · role + society re-read per call
 │  4 Injection filter          │             · one transaction per write:
 │  5 Unknown-number block      │               payment + ledger + idempotency + audit
 │  6 Role + flat from DynamoDB │                     │
 └──────────────┬───────────────┘                     │
                │ session attributes (server-set)     │
                ▼                                     │
 Amazon Bedrock Agent (Claude Haiku 4.5)              │
   │ ReAct loop · read-only tools                     │
   ├── getDues / getHistory ── role + flat check ─┐   │
   └── Knowledge Base (vendors, bye-laws)         ▼   ▼
                                          DynamoDB (ap-south-1)
                                          ledger · payments · audit log
```

| Layer | Technology |
|---|---|
| Channel | WhatsApp Cloud API (Meta) |
| AI | Amazon Bedrock Agents — Claude Haiku 4.5, Bedrock Knowledge Base (RAG) |
| Compute | AWS Lambda, Python 3.12 |
| Data | Amazon DynamoDB (on-demand, PITR) |
| Admin auth | Amazon Cognito custom auth with WhatsApp OTP |
| Admin UI | React + Vite on Cloudflare Pages |
| Region | AWS ap-south-1 (Mumbai) — all resident data stays in India |

---

## Design principles

1. **The LLM is never the security boundary.** Identity, role and flat are resolved server-side and passed to tools as session attributes. Every tool checks them in code before touching data. A prompt injection can at worst produce a polite refusal. → [ADR-002](docs/decisions.md#adr-002)
2. **Writes leave the chat.** Payments and expenses are recorded in an authenticated admin console, not through the LLM. WhatsApp is read-only for residents. → [ADR-018](docs/decisions.md#adr-018)
3. **Money is append-only.** Every payment and reversal is its own record; the ledger is a derived view. Idempotency, optimistic concurrency and the audit entry commit in one transaction. → [ADR-020](docs/decisions.md#adr-020)
4. **Privacy by architecture, not policy.** Message content is never stored. Data is classified into tiers before encryption is designed. Everything runs in-region. → [ADR-013, 016](docs/decisions.md#adr-013)
5. **Serverless-first, scale to zero.** No servers to run for a pilot; cost tracks usage.

---

## Repository contents

| Path | What's there |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Components, request lifecycle, data model, multi-tenancy |
| [`docs/security.md`](docs/security.md) | Defence in depth: webhook, tools, admin console, data protection |
| [`docs/decisions.md`](docs/decisions.md) | Architecture Decision Records with context and consequences |
| [`examples/`](examples) | Short, simplified excerpts of the key patterns (not deployable) |
| [`data/sunrise-residency/`](data/sunrise-residency) | Fully synthetic sample data for a fictional society |
| [`site/`](site) | Source of architecture.torvi.in (static, Cloudflare Pages) |

---

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | WhatsApp ↔ Bedrock agent, dues and history tools, 9-layer inbound security | Live |
| 1.5 | Admin console (OTP login, payments, expenses, month close, analytics), audit log | Built, in parallel run |
| 2 | Meeting minutes from voice notes (Transcribe → summary → broadcast) | Designed |
| 3 | UPI collections and AutoPay, automated reminders | Designed |

---

## About

Torvi is built by [Eswara Krishna Akurathi (KK)](https://krishnakumarakurathi.com), a platform solutions architect working on enterprise agentic AI for banking and financial services. Torvi Technologies is an MSME registered in Hyderabad.

For a walkthrough of the full system or access to the private code, reach out via [torvi.in](https://torvi.in).

© 2026 Torvi Technologies. Documentation and excerpts are shared for reference; see [LICENSE](LICENSE).
