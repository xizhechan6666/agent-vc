# Agent VC

Agent VC is a completed OKX.AI A2MCP-style paid report service for Agent founders.

It evaluates early Agent projects like a lightweight VC committee: founder questions, scoring, investment memo, improvement plan, optional Agent wallet verification, and a server-side candidate gate for 100 USDT early support.

Live service:

```text
https://agent-vc-4a3m.onrender.com
```

## Current Product Flow

1. A founder or Agent Client submits an Agent project.
2. `/interview` can generate three investor follow-up questions.
3. The paid Agent Client calls `/evaluate`.
4. x402 returns HTTP 402 until the caller pays through **OKX Agent Payments Protocol**.
5. After payment replay, the service generates the real report, stores it, applies duplicate and quota rules, and returns JSON plus `report_url`.
6. The user reads the full HTML report at `/agent/reports/{report_token}`.

## Surfaces

The browser page and the Agent Client endpoint are intentionally different.

Human web page:

```text
GET /
```

- Product introduction.
- Project draft form.
- Paid-call instructions.
- Complete report generation is reserved for the paid Agent Client flow.
- No database write.
- No investment quota decision.

Paid Agent endpoint:

```text
POST /evaluate
```

- x402-protected when `X402_ENABLED=1`.
- Generates the real JSON report.
- Saves the evaluation.
- Returns a private tokenized HTML report link.
- Applies duplicate checks and investment quota.

`POST /demo/evaluate` is restricted by default and returns 403 unless explicitly enabled for controlled internal testing.

Owner-only preview endpoints are available only when `OWNER_ACCESS_TOKEN` is set. They skip x402 for development, require the `X-Agent-VC-Owner-Token` header, and are excluded from public quota counting:

```text
POST /owner/interview
POST /owner/evaluate
POST /owner/simulate
```

## Public Endpoints

```text
GET  /health
GET  /schema
GET  /a2mcp.json
GET  /openapi.json
GET  /integration-check
POST /interview
POST /evaluate
POST /demo/evaluate
GET  /agent/reports/{report_token}
```

`/integration-check` is the safest quick sanity check. It returns x402 status, paid endpoint, report URL template, schema availability, and LLM configuration status without exposing secrets.

## A2MCP Registration

Register this as an API/A2MCP service, not A2A.

Use:

```text
serviceName: Agent VC Investment Diagnosis
serviceType: A2MCP
fee: 5
endpoint: https://agent-vc-4a3m.onrender.com/evaluate
```

Only one OKX.AI service should be listed for Agent `#5814`: `Agent VC Investment Diagnosis`. The older duplicate service `Investment Memo` was removed.

The service manifest is available at:

```text
https://agent-vc-4a3m.onrender.com/a2mcp.json
```

It includes `inputSchema` and `outputSchema` so a compatible Agent Client can collect the right request fields and display the returned report data.

## x402 Payment

Production payment configuration should use the official OKX Payment SDK path so a paid replay is settled before the report is returned:

```bash
X402_ENABLED=1
X402_PRICE=5
X402_MODE=sdk
X402_NETWORK=eip155:196
X402_ASSET=0x779ded0c9e1022225f8e0630b35a9b54be713736
X402_ASSET_NAME=USDT
X402_SCHEME=exact
X402_SYNC_SETTLE=1
OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_PASSPHRASE=...
```

Unauthenticated calls to `/evaluate` return HTTP 402 with a compact `PAYMENT-REQUIRED` header. `POST /evaluate` is the paid business call that returns the report after settlement. `GET /evaluate` and `HEAD /evaluate` also return a payment challenge in production so OKX.AI marketplace validators do not confuse the endpoint with a free probe. Full request and response schemas remain available through `/a2mcp.json` and `/openapi.json`.

The service challenge is configured for X Layer (`eip155:196`) and the OKX-supported USDT contract used by A2MCP service registration. The amount is `5000000`, representing 5 units with 6 decimals. `X402_MODE=sdk` uses OKX's facilitator with synchronous settlement. The older `X402_MODE=okx` compatibility path only validates payment authorization fields locally and does not settle funds; do not use it for production charging.

Official SDK variables:

```bash
X402_ENABLED=1
X402_MODE=sdk
X402_PRICE=5
X402_NETWORK=eip155:196
X402_SCHEME=exact
X402_PAY_TO=0x...
OKX_API_KEY=...
OKX_SECRET_KEY=...
OKX_PASSPHRASE=...
OKX_BASE_URL=https://web3.okx.com
X402_SYNC_SETTLE=1
```

In `sdk` mode, the FastAPI app uses OKX's Seller SDK (`okxweb3-app-x402`) with `OKXFacilitatorClient`, `PaymentMiddlewareASGI`, and `ExactEvmScheme`. This is the preferred production path for official x402 v2 wrapping, payment verification, and synchronous settlement. The service requires the three OKX API credentials in Render; startup intentionally fails if they are missing.

## Response Contract

Paid `/evaluate` returns JSON with:

```json
{
  "request_id": 1,
  "report_token": "...",
  "report_url": "https://agent-vc-4a3m.onrender.com/agent/reports/{report_token}",
  "investment_gate": {},
  "client_summary": {
    "chat_summary": "...",
    "result_first_message": "...",
    "founder_next_action": "...",
    "shareable_text": "...",
    "report_url": "..."
  },
  "sync": {},
  "report": {}
}
```

Agent Clients should show `client_summary` in chat and offer `report_url` for the full HTML report.

## Investment Gate

The LLM only makes a raw recommendation. Final candidate status is controlled by deterministic server rules.

Default rules:

```bash
INVESTMENT_WINDOW_SIZE=20
INVESTMENT_MAX_PER_WINDOW=1
INVESTMENT_MINIMUM_SCORE=88
```

Meaning:

- 5 USDT assessment fee.
- Up to 1 candidate per 20 paid evaluations.
- Candidate support amount is 100 USDT.
- Selected projects may also receive up to 500 USDT worth of project promotion and founder personal-brand support.
- Duplicate project or submitter submissions on the same UTC date do not trigger candidate status.
- Manual review is required before any payout.

The LLM must never directly trigger payout.

## Optional Wallet Verification

`agent_wallet_address`, `wallet_chain`, and `wallet_signature` are optional.

Current implementation:

- Validates X Layer-style EVM addresses.
- Adds an OKLink X Layer explorer link.
- Adds a conservative verification bonus when evidence exists.
- Marks unverified submitted addresses as weak evidence.
- Does not claim full transaction forensics.

Deeper transaction graph analysis should be added only after a reliable X Layer indexer/API source is confirmed.

## Local Development

Install:

```bash
pip install -r requirements.txt
```

Run the production FastAPI entrypoint locally:

```bash
uvicorn server:app --host 127.0.0.1 --port 8787
```

For a quick no-x402 local smoke test:

```bash
X402_ENABLED=0 uvicorn server:app --host 127.0.0.1 --port 8787
```

Generate follow-up questions:

```bash
curl -s http://127.0.0.1:8787/interview \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

Generate a local report in a controlled no-x402 development run:

```bash
curl -s http://127.0.0.1:8787/evaluate \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

## Environment

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
SERVICE_FEE_USDT=5
X402_ENABLED=1
X402_PAY_TO=0xc964dcc547cf0ce07716babb4eb2f4a2f09bf16c
X402_PRICE=5
X402_MODE=okx
X402_NETWORK=eip155:196
X402_ASSET=0x779ded0c9e1022225f8e0630b35a9b54be713736
X402_ASSET_NAME=USDT
X402_SCHEME=exact
DEMO_EVALUATE_ENABLED=0
OWNER_ACCESS_TOKEN=use-a-private-random-token-in-render
```

Keep API keys in environment variables only.

## Owner Preview

Use owner preview when you need to simulate the Agent Client interaction without paying x402 during development.

```bash
curl -s https://agent-vc-4a3m.onrender.com/owner/simulate \
  -H 'Content-Type: application/json' \
  -H "X-Agent-VC-Owner-Token: $OWNER_ACCESS_TOKEN" \
  --data @sample_request.json
```

If `answers` is empty, `/owner/simulate` returns the follow-up questions and a conversation-style preview. If `answers` is present, it returns the final JSON, `client_summary`, and tokenized HTML `report_url`.

Do not commit `OWNER_ACCESS_TOKEN`. Set it only in the deployment environment.

## Candidate Database

Every completed `/evaluate` and `/owner/evaluate` call is saved to durable Supabase Postgres in production. Local SQLite is only a development fallback when `DATABASE_URL` is not configured.

Saved fields include:

- Raw submitted `project` fields.
- Follow-up `answers`.
- x402 payer wallet when available.
- Contact hint.
- Score, recommendation, duplicate flag, investment gate result, and report URL.
- Source: `agent_client` or `owner_preview`.

Owner-only dashboard:

```text
https://agent-vc-4a3m.onrender.com/owner/dashboard
```

Owner-only exports:

```bash
curl -s "https://agent-vc-4a3m.onrender.com/owner/evaluations?limit=100" \
  -H "X-Agent-VC-Owner-Token: $OWNER_ACCESS_TOKEN"
```

```bash
curl -L "https://agent-vc-4a3m.onrender.com/owner/evaluations.csv?limit=500&owner_token=$OWNER_ACCESS_TOKEN" \
  -o agent-vc-evaluations.csv
```

The optional `DB_SYNC_WEBHOOK_URL` hook can still mirror rows to Google Sheets, Airtable, Notion, or another database. If `DB_SYNC_SECRET` is set, the app sends `Authorization: Bearer <secret>`.

### Durable Report Storage

Production is configured for Supabase Postgres through `DATABASE_URL`. Without it, the app falls back to local SQLite, which can disappear when a free Render instance restarts or redeploys.

Recommended setup:

1. Create a Supabase project or Render Postgres database.
2. Copy its Postgres connection string.
3. Set these Render environment variables:

```bash
DATABASE_URL=postgresql://...
DATABASE_SSLMODE=require
```

After deployment, verify:

```bash
curl -s https://agent-vc-4a3m.onrender.com/integration-check
```

Expected storage section:

```json
{
  "storage": {
    "backend": "postgres",
    "durable": true,
    "database_url_configured": true,
    "ok": true
  }
}
```

When Postgres is enabled, `report_token`, report JSON, user submissions, answers, payer wallet, and dashboard exports survive Render restarts and redeploys.

## Verification

```bash
.venv/bin/python -m py_compile server.py app.py agent_vc/*.py
```

```bash
curl -i -X POST https://agent-vc-4a3m.onrender.com/evaluate \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

Expected unpaid production result:

- HTTP 402.
- `PAYMENT-REQUIRED` header exists.
- Decoded x402 payload has `x402Version: 2`.
- Amount is `5000000`.
- Network is `eip155:196`.
- Asset is `0x779ded0c9e1022225f8e0630b35a9b54be713736`.
- Bazaar input method is `POST`.

More operational details are in `OPERATIONS.md`; deployment details are in `DEPLOY.md`.
