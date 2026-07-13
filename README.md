# Agent VC

Agent VC is a small HTTP service for an OKX.AI A2MCP-style fixed-price report product.

The product flow is:

1. A founder submits an Agent project.
2. Agent VC generates investor questions.
3. The founder answers.
4. Agent VC returns a structured investment diagnosis report.
5. A hard quota gate decides whether the project enters the 100U investment candidate pool.

The report engine is independent from payments and listing. x402 / **OKX Agent Payments Protocol** should wrap the `/evaluate` endpoint later as a payment gate, without changing the report logic.

## Run Locally

```bash
cd /Users/xizhe/agent-vc
python3 app.py
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Generate VC questions:

```bash
curl -s http://127.0.0.1:8787/interview \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

Generate a report:

```bash
curl -s http://127.0.0.1:8787/evaluate \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

## LLM Configuration

The service supports OpenAI-compatible chat completions. DeepSeek is the default endpoint.

```bash
export LLM_API_KEY='...'
export LLM_BASE_URL='https://api.deepseek.com/chat/completions'
export LLM_MODEL='deepseek-chat'
python3 app.py
```

If no API key is set, the service returns a local fallback report. That is useful for integration tests, but not for final product quality.

On this local macOS Python install, HTTPS certificate verification may fail because the OpenSSL cert store is empty. `start_with_key.sh` sets `LLM_SSL_VERIFY=0` for local development. On a real server, install certificates and set `LLM_SSL_VERIFY=1`.

To avoid saving the key in shell history, you can start the service with:

```bash
chmod +x start_with_key.sh
./start_with_key.sh
```

## Investment Quota

The LLM can only recommend investment. Final candidate status is controlled by hard server-side rules:

```bash
export INVESTMENT_WINDOW_SIZE=20
export INVESTMENT_MAX_PER_WINDOW=1
```

Default rule: at most 1 investment candidate per 20 paid evaluations, and only if `total_score >= 85`.

## Endpoints

- `GET /health`
- `GET /schema`
- `GET /a2mcp.json`
- `GET /openapi.json`
- `POST /interview`
- `POST /evaluate`

`POST /evaluate` input shape:

```json
{
  "project": {
    "name": "Agent name",
    "agent_url": "OKX.AI URL or Agent ID",
    "one_liner": "One sentence pitch",
    "target_user": "Who pays",
    "problem": "Problem",
    "solution": "Solution",
    "pricing": "Pricing",
    "traction": "Sales, reviews, tasks, usage, testimonials",
    "differentiation": "Why not ChatGPT/Doubao/Codex/existing agents",
    "founder_pitch": "Why this deserves investment",
    "risks": "Known weak spots"
  },
  "answers": [
    {
      "question": "Investor question",
      "answer": "Founder answer"
    }
  ]
}
```

## Next Build Steps

1. Tune the prompt with 5-10 real Agent examples.
2. Add x402 payment middleware around `/evaluate`.
3. Deploy behind HTTPS.
4. Register the public URL as an OKX.AI A2MCP service.
5. Add a payout workflow later; never let the LLM trigger payouts directly.

Deployment notes are in `DEPLOY.md`.
