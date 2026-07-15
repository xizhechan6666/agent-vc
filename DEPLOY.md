# Deploy And Register Agent VC

This document describes the current production deployment and OKX.AI registration values.

## Production URLs

```text
Web page:        https://agent-vc-4a3m.onrender.com/
Paid endpoint:  https://agent-vc-4a3m.onrender.com/evaluate
Manifest:       https://agent-vc-4a3m.onrender.com/a2mcp.json
Health:         https://agent-vc-4a3m.onrender.com/health
Integration:    https://agent-vc-4a3m.onrender.com/integration-check
OpenAPI:        https://agent-vc-4a3m.onrender.com/openapi.json
```

Use `/integration-check` before review or live demonstration. It returns a no-secret status object confirming the paid endpoint, x402 status, report URL template, LLM status, and Agent Client response contract.

## Required Environment Variables

Set these on the cloud host:

```bash
HOST=0.0.0.0
PORT=8787
PUBLIC_BASE_URL=https://agent-vc-4a3m.onrender.com

LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
LLM_SSL_VERIFY=1

SERVICE_FEE_USDT=5
INVESTMENT_WINDOW_SIZE=20
INVESTMENT_MAX_PER_WINDOW=1
INVESTMENT_MINIMUM_SCORE=88

DEMO_EVALUATE_ENABLED=0

X402_ENABLED=1
X402_PAY_TO=0xc964dcc547cf0ce07716babb4eb2f4a2f09bf16c
X402_PRICE=5
X402_MODE=okx
X402_NETWORK=eip155:196
X402_ASSET=0x779ded0c9e1022225f8e0630b35a9b54be713736
X402_ASSET_NAME=USDT
X402_ASSET_VERSION=1
X402_ASSET_DECIMALS=6
X402_SCHEME=exact
X402_MAX_TIMEOUT_SECONDS=300
```

Keep API keys in environment variables only. On Render, `LLM_API_KEY`, `DB_SYNC_WEBHOOK_URL`, and `DB_SYNC_SECRET` are marked `sync: false`.

## Render Deployment

`render.yaml` deploys the FastAPI entrypoint:

```text
uvicorn server:app --host 0.0.0.0 --port 8787
```

The included Render plan is `free`. Free services can sleep when idle and local SQLite storage is not durable. Upgrade the instance and attach durable storage before relying on it for long-running production accounting.

## OKX.AI A2MCP Registration

Register an API/A2MCP service, not an A2A task service.

Use the values from:

```text
https://agent-vc-4a3m.onrender.com/a2mcp.json
```

Current registration values:

```json
{
  "serviceName": "Agent VC Investment Diagnosis",
  "serviceDescription": "① 通过 x402 付费后，对 OKX.AI Agent 项目进行 VC 式追问、评分和投资委员会诊断。\n② 返回结构化 JSON、投资/奖励门控结果、数据库同步状态，以及独立 HTML 报告链接 report_url。\n③ 网页端用于产品介绍和项目信息整理；完整研报、入库和 100 USDT 支持筛选仅通过付费 Agent Client 端点完成。",
  "serviceType": "A2MCP",
  "fee": "5",
  "endpoint": "https://agent-vc-4a3m.onrender.com/evaluate"
}
```

The manifest also includes `inputSchema` and `outputSchema`. A compatible Agent Client should use those schemas to collect the project fields and display `client_summary` plus `report_url`.

## x402 Runtime Behavior

Unpaid request:

```bash
curl -i -X POST https://agent-vc-4a3m.onrender.com/evaluate \
  -H 'Content-Type: application/json' \
  --data @sample_request.json
```

Expected response:

- HTTP 402.
- `PAYMENT-REQUIRED` header exists.
- Decoded payload uses `x402Version: 2`.
- `accepts[0].network` is `eip155:196`.
- `accepts[0].asset` is `0x779ded0c9e1022225f8e0630b35a9b54be713736`.
- `accepts[0].amount` is `5000000`.
- `extensions.bazaar.info.input.method` is `POST`.
- `extensions.bazaar.info.input.body.required` contains `project`.

After user confirmation, the Agent Client signs the x402 payment and replays the same request with the returned payment authorization header. The server then returns the report JSON and stores the evaluation.

## Web Page Boundary

The web page at `/` is not the paid report endpoint.

It can:

- Explain the product.
- Generate non-paid follow-up questions through `/interview`.
- Show the project JSON that should be submitted through Agent Client.

Production boundaries:

- Complete investment reports are generated only through the paid Agent Client endpoint.
- Investment database writes happen only after a valid paid `/evaluate` call.
- 100 USDT support quota decisions happen only in the paid endpoint.
- x402 remains the required payment gate for production report generation.

`/demo/evaluate` is restricted by default and returns 403.

## Network Note

Current working x402 payment network:

```bash
X402_NETWORK=eip155:196
X402_ASSET=0x779ded0c9e1022225f8e0630b35a9b54be713736
X402_ASSET_NAME=USDT
```

The x402 challenge is intentionally aligned with the OKX.AI service registration: X Layer (`eip155:196`) and USDT (`0x779ded0c9e1022225f8e0630b35a9b54be713736`). Keep `X402_MODE=okx` unless an OKX-supported external facilitator URL is provided.

## Local Verification

```bash
.venv/bin/python -m py_compile server.py app.py agent_vc/*.py
```

```bash
X402_ENABLED=1 \
X402_PAY_TO=0xc964dcc547cf0ce07716babb4eb2f4a2f09bf16c \
X402_PRICE=5 \
X402_MODE=okx \
X402_NETWORK=eip155:196 \
X402_ASSET=0x779ded0c9e1022225f8e0630b35a9b54be713736 \
.venv/bin/python - <<'PY'
import base64, json
from fastapi.testclient import TestClient
import server

c = TestClient(server.app)
r = c.post('/evaluate', json={
    'project': {
        'name': 'Demo Agent',
        'one_liner': '帮助 Agent 创业者获得 VC 式反馈',
        'target_user': 'OKX.AI Agent 创业者',
        'problem': '早期项目缺少付费场景、增长路径和投资叙事'
    }
})
print(r.status_code)
raw = r.headers.get('payment-required')
print(bool(raw))
if raw:
    data = json.loads(base64.b64decode(raw))
    print(data.get('x402Version'))
    print(data['accepts'][0]['network'])
    print(data['accepts'][0]['amount'])
    print(data.get('extensions', {}).get('bazaar', {}).get('info', {}).get('input', {}).get('method'))
PY
```

Real-payment replay is performed from a supported Agent Client with an authenticated Agentic Wallet and sufficient supported stablecoin balance.
