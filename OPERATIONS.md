# Agent VC Operating State

This document describes the current completed product state. It replaces the old build plan.

## Live Service

Production URL:

```text
https://agent-vc-4a3m.onrender.com
```

Primary paid Agent endpoint:

```text
POST https://agent-vc-4a3m.onrender.com/evaluate
```

Public checks:

```text
https://agent-vc-4a3m.onrender.com/
https://agent-vc-4a3m.onrender.com/health
https://agent-vc-4a3m.onrender.com/integration-check
https://agent-vc-4a3m.onrender.com/a2mcp.json
https://agent-vc-4a3m.onrender.com/openapi.json
```

## Product Boundary

Agent VC has two separate surfaces:

1. Human web page
   - Used for product explanation, project draft collection, and paid-call instructions.
   - Does not generate a free full report.
   - Does not write to the investment database.
   - Does not consume investment quota.

2. Paid Agent Client endpoint
   - `POST /evaluate`.
   - Protected by x402 when `X402_ENABLED=1`.
   - Generates the real JSON report.
   - Writes the evaluation to SQLite.
   - Applies duplicate checks and quota gating.
   - Returns `report_url` pointing to `/agent/reports/{report_token}`.

`POST /demo/evaluate` is intentionally disabled by default. It returns 403 unless `DEMO_EVALUATE_ENABLED=1`.

## A2MCP And x402 Flow

Use A2MCP, not A2A, for this product. This is a fixed-price report service, not a negotiated task workflow.

Expected flow:

1. Agent Client sends `POST /evaluate` with a JSON body matching `inputSchema`.
2. Server returns HTTP 402 when no valid payment proof is present.
3. The 402 response includes `PAYMENT-REQUIRED` with x402 v2 requirements and Bazaar discovery metadata.
4. Agent Client asks the user to confirm payment through **OKX Agent Payments Protocol**.
5. After payment signing, Agent Client replays the same request with the returned payment authorization header.
6. Server verifies payment, runs the evaluator, saves the report, and returns JSON.
7. Agent Client can display `client_summary` in chat and give the user `report_url` for the full HTML report.

The returned JSON includes:

- `request_id`
- `report_token`
- `report_url`
- `investment_gate`
- `client_summary.chat_summary`
- `client_summary.result_first_message`
- `client_summary.founder_next_action`
- `client_summary.shareable_text`
- `report`

## Current Pricing And Incentives

- Assessment fee: 5 USDT.
- Candidate support amount: 100 USDT.
- Selected projects may also receive up to 500 USDT worth of promotion and founder personal-brand support.

Payment does not guarantee investment support. The LLM can only produce a raw recommendation. Final candidate status is controlled by server-side quota, duplicate checks, and manual review.

## Quota And Anti-Abuse Rules

Default production values:

```bash
INVESTMENT_WINDOW_SIZE=20
INVESTMENT_MAX_PER_WINDOW=1
INVESTMENT_MINIMUM_SCORE=88
```

Meaning:

- At most 1 investment candidate per 20 paid evaluations.
- The report must score at least 88.
- Duplicate project or submitter submissions on the same UTC date do not trigger candidate status.
- Manual review is still required before any payout.

The LLM must never directly trigger payout.

## Wallet Verification

Agent wallet verification is optional. It feeds `verification_bonus` and confidence notes, but it is not required to complete the assessment.

Current implementation:

- Accepts `agent_wallet_address`, `wallet_chain`, and `wallet_signature`.
- Supports X Layer-style EVM wallet addresses.
- Creates an OKLink X Layer explorer URL.
- Distinguishes unverified submitted addresses from ownership-supported addresses.
- Does not claim full transaction forensics yet.

Deeper transaction graph analysis should be added only after the X Layer indexing/API source is confirmed.

## Network Configuration

Current working x402 config:

```bash
X402_PRICE=$5.00
X402_NETWORK=eip155:84532
X402_SCHEME=exact
```

The current x402 Python SDK provides a default USDC asset for `eip155:84532`. X Layer identity and Agent wallet verification remain X Layer-oriented, but the payment network should not be switched to `eip155:196` until the OKX x402 facilitator and supported X Layer stablecoin contract are confirmed.

## Required Environment Variables

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
SERVICE_FEE_USDT=5
X402_ENABLED=1
X402_PAY_TO=0xc964dcc547cf0ce07716babb4eb2f4a2f09bf16c
X402_PRICE=$5.00
X402_NETWORK=eip155:84532
X402_SCHEME=exact
DEMO_EVALUATE_ENABLED=0
```

Never commit API keys.

## Verification Commands

Syntax and schema:

```bash
.venv/bin/python -m py_compile server.py app.py agent_vc/*.py
```

Unpaid x402 challenge:

```bash
curl -i -X POST https://agent-vc-4a3m.onrender.com/evaluate \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

Expected result:

- HTTP 402.
- `PAYMENT-REQUIRED` header exists.
- Decoded payload has `x402Version: 2`.
- `accepts[0].amount` is `5000000`.
- `accepts[0].network` is `eip155:84532`.
- `extensions.bazaar.info.input.method` is `POST`.

Paid replay must be tested from a supported Agent Client with an authenticated Agentic Wallet and sufficient supported stablecoin balance.
