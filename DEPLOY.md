# Deploy Agent VC

## What Has To Be Public

OKX.AI A2MCP registration needs a public HTTPS endpoint. For this service, use:

```text
https://YOUR_DOMAIN/evaluate
```

Helpful discovery pages:

```text
https://YOUR_DOMAIN/
https://YOUR_DOMAIN/health
https://YOUR_DOMAIN/a2mcp.json
https://YOUR_DOMAIN/openapi.json
```

## Environment Variables

Set these on the cloud host:

```bash
HOST=0.0.0.0
PORT=8787
PUBLIC_BASE_URL=https://YOUR_DOMAIN
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com/chat/completions
LLM_MODEL=deepseek-chat
LLM_SSL_VERIFY=1
SERVICE_FEE_USDT=5
X402_ENABLED=1
X402_PAY_TO=0xc964dcc547cf0ce07716babb4eb2f4a2f09bf16c
X402_PRICE=$5.00
X402_NETWORK=eip155:84532
X402_SCHEME=exact
INVESTMENT_WINDOW_SIZE=20
INVESTMENT_MAX_PER_WINDOW=1
```

Do not commit API keys.

On Render, `LLM_API_KEY` is defined with `sync: false` in `render.yaml`, so Render prompts you for the value in the dashboard instead of storing it in Git.

## Docker

Build locally:

```bash
docker build -t agent-vc .
```

Run locally:

```bash
docker run --rm -p 8787:8787 \
  -e LLM_API_KEY='...' \
  -e PUBLIC_BASE_URL='http://127.0.0.1:8787' \
  agent-vc
```

## Render

`render.yaml` is included. In the Render dashboard, add secret environment variables:

```text
LLM_API_KEY
```

After deploy, open:

```text
https://YOUR_RENDER_URL/a2mcp.json
```

Copy `service.endpoint`, `service.fee`, `service.serviceName`, and `service.serviceDescription` into the OKX.AI ASP service registration flow.

The included Render plan is `free` to avoid accidental charges. Free web services can spin down when idle and their local SQLite data is not persistent. Upgrade the instance type when you need 24/7 availability.

## OKX.AI Registration Fields

For an API service:

```json
{
  "serviceName": "Agent VC Investment Diagnosis",
  "serviceDescription": "① 通过 x402 付费后，对 OKX.AI Agent 项目进行 VC 式追问、评分和投资委员会诊断。\n② 返回结构化 JSON、投资/奖励门控结果、数据库同步状态，以及独立 HTML 报告链接 report_url。\n③ 网页端只用于产品介绍，不免费生成完整研报，不参与入库和 100 USDT 支持筛选。",
  "serviceType": "A2MCP",
  "fee": "5",
  "endpoint": "https://YOUR_DOMAIN/evaluate"
}
```

## x402 Payment Gate

The deployed `/evaluate` endpoint is protected by x402 when:

```bash
X402_ENABLED=1
X402_PAY_TO=0xc964dcc547cf0ce07716babb4eb2f4a2f09bf16c
X402_PRICE=$5.00
X402_NETWORK=eip155:84532
```

Unauthenticated callers receive HTTP 402. Clients pay, then replay the same request with the x402 payment signature header.

The web page at `/` is only a product landing and paid Agent Client guide. By default, `/demo/evaluate` returns 403 so browser users cannot receive a free full report, enter the investment database, or consume quota. The A2MCP service endpoint remains `/evaluate`.

Before registration or review, open:

```text
https://YOUR_DOMAIN/integration-check
```

It returns a no-secret status object confirming the paid endpoint, x402 status, report URL template, and Agent Client response contract.

## Network Note

The current x402 Python SDK has a default stablecoin asset for `eip155:84532`, so this repo uses it for the working one-shot payment gate. X Layer identity and Agent wallet verification still use X Layer (`eip155:196`) conceptually.

Do not switch `X402_NETWORK` to `eip155:196` until the OKX x402 facilitator and supported stablecoin contract for X Layer are confirmed. If you switch early without an explicit supported asset configuration, the server may fail to produce a valid payment requirement.
