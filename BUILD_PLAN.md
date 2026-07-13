# Agent VC Build Plan

## Current State

Implemented now:

- `POST /interview`: creates VC-style investor questions.
- `POST /evaluate`: creates a structured investment diagnosis report.
- Hard quota gate: the report can recommend investment, but the server decides candidate status.
- SQLite persistence: saved under `data/agent_vc.sqlite3`.
- OpenAI-compatible LLM client: DeepSeek is the default endpoint.
- Local fallback: works without an API key for integration testing.

## Correct Build Order

1. Tune the report brain.
   - Edit `agent_vc/prompt.py`.
   - Test with real OKX.AI Agent examples.
   - Do not touch payments until the report is worth buying.

2. Configure the LLM.
   - Set `LLM_API_KEY`.
   - Optional: set `LLM_BASE_URL` and `LLM_MODEL`.
   - Verify `/health` returns `"llm_configured": true`.

3. Add the x402 payment gate.
   - Wrap `POST /evaluate`.
   - Unpaid requests should return HTTP 402 with payment requirements.
   - Paid requests should verify the payment first, then run `evaluate_project`.
   - Keep the report logic unchanged.

4. Deploy behind HTTPS.
   - The OKX.AI A2MCP listing needs a public HTTPS URL.
   - Store LLM and payment secrets in environment variables.

5. Register and list.
   - Install Onchain OS skills in a compatible agent client.
   - Log in/create Agentic Wallet.
   - Register as ASP.
   - Create an A2MCP service pointing at the public `/evaluate` endpoint.

6. Add payout later.
   - Keep payout disabled in v1.
   - Never let the LLM trigger payout directly.
   - Only a server-side quota gate plus manual review should enable 100U candidate payout.

## Local Commands

```bash
cd /Users/xizhe/agent-vc
python3 app.py
```

```bash
curl -s http://127.0.0.1:8787/interview \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

```bash
curl -s http://127.0.0.1:8787/evaluate \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

## Environment

```bash
export LLM_API_KEY='...'
export LLM_BASE_URL='https://api.deepseek.com/chat/completions'
export LLM_MODEL='deepseek-chat'
export INVESTMENT_WINDOW_SIZE=20
export INVESTMENT_MAX_PER_WINDOW=1
```
