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
SERVICE_FEE_USDT=10
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
  "serviceDescription": "① 对 OKX.AI Agent 项目进行 VC 式追问、评分和投资委员会诊断，输出 HTML/JSON 报告。\n② 用户需提供 Agent 名称、链接或 ID、目标用户、问题、方案、定价、traction、差异化和融资叙事。",
  "serviceType": "A2MCP",
  "fee": "10",
  "endpoint": "https://YOUR_DOMAIN/evaluate"
}
```

Payment gate status is intentionally `X402_ENABLED=0` until the OKX Payment SDK integration is added.
