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

The service manifest is available at:

```text
https://agent-vc-4a3m.onrender.com/a2mcp.json
```

It includes `inputSchema` and `outputSchema` so a compatible Agent Client can collect the right request fields and display the returned report data.

## x402 Payment

Current working production configuration:

```bash
X402_ENABLED=1
X402_PRICE=5
X402_MODE=okx
X402_NETWORK=eip155:196
X402_ASSET=0x779ded0c9e1022225f8e0630b35a9b54be713736
X402_ASSET_NAME=USDT
X402_SCHEME=exact
```

Unauthenticated calls to `/evaluate` return HTTP 402 with a `PAYMENT-REQUIRED` header. The header contains x402 v2 requirements and Bazaar discovery metadata.

The service challenge is configured for X Layer (`eip155:196`) and the OKX-supported USDT contract used by A2MCP service registration. The amount is `5000000`, representing 5 units with 6 decimals. `X402_MODE=okx` returns the challenge immediately and verifies the replayed `PAYMENT-SIGNATURE` locally so OKX Agent Client calls do not depend on the generic x402.org facilitator.

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
