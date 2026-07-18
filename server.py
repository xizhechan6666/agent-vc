"""FastAPI entrypoint with optional x402 payment middleware."""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from agent_vc.evaluator import (
    apply_investment_gate,
    build_client_summary,
    evaluate_project,
    generate_interview,
    project_fingerprint,
    submitter_key,
)
from agent_vc.prompt import INPUT_SCHEMA, REPORT_SCHEMA_HINT
from agent_vc.store import (
    connect,
    duplicate_today,
    get_evaluation,
    get_evaluation_by_token,
    list_evaluations,
    save_evaluation,
    storage_health,
)
from agent_vc.sync import sync_evaluation
from app import INDEX_HTML, a2mcp_document, bazaar_discovery_extension, openapi_document, report_page


app = FastAPI(title="Agent VC API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE", "X-PAYMENT", "X-PAYMENT-RESPONSE"],
)


def x402_enabled() -> bool:
    return os.getenv("X402_ENABLED", "0") == "1"


def x402_mode() -> str:
    return os.getenv("X402_MODE", "okx").lower()


def x402_price_amount() -> str:
    configured_amount = os.getenv("X402_AMOUNT")
    if configured_amount:
        return configured_amount

    price = os.getenv("X402_PRICE", "5")
    normalized = price.replace("$", "").replace("USDT", "").replace("USDC", "").strip()
    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise RuntimeError("X402_PRICE must be a numeric stablecoin amount, for example 5 or $5.00") from exc

    decimals = int(os.getenv("X402_ASSET_DECIMALS", "6"))
    return str(int(value * (Decimal(10) ** decimals)))


def x402_price_display() -> str:
    configured = os.getenv("X402_SDK_PRICE")
    if configured:
        return configured

    price = os.getenv("X402_PRICE", "5")
    normalized = price.replace("$", "").replace("USDT", "").replace("USDC", "").strip()
    return f"${normalized}"


def x402_network() -> str:
    return os.getenv("X402_NETWORK", "eip155:196")


def x402_asset() -> str:
    return os.getenv("X402_ASSET", "0x779ded0c9e1022225f8e0630b35a9b54be713736")


def x402_asset_name() -> str:
    return os.getenv("X402_ASSET_NAME", "USDT")


def x402_asset_version() -> str:
    return os.getenv("X402_ASSET_VERSION", "1")


def x402_chain_id() -> int:
    network = x402_network()
    if not network.startswith("eip155:"):
        raise RuntimeError("Only EVM CAIP-2 x402 networks are supported")
    return int(network.split(":", 1)[1])


def b64_json(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode()


def build_x402_accept() -> dict[str, Any]:
    pay_to = os.getenv("X402_PAY_TO")
    if not pay_to:
        raise RuntimeError("X402_ENABLED=1 requires X402_PAY_TO")
    return {
        "scheme": os.getenv("X402_SCHEME", "exact"),
        "network": x402_network(),
        "asset": x402_asset(),
        "amount": x402_price_amount(),
        "payTo": pay_to,
        "maxTimeoutSeconds": int(os.getenv("X402_MAX_TIMEOUT_SECONDS", "300")),
        "extra": {"name": x402_asset_name(), "version": x402_asset_version()},
    }


def build_payment_required(request: Request, error: str = "Payment required") -> dict[str, Any]:
    payload = {
        "x402Version": 2,
        "error": error,
        "resource": {
            "url": absolute_url(request, "/evaluate"),
            "description": "Agent VC investment diagnosis report for OKX.AI Agent projects.",
            "mimeType": "application/json",
            "serviceName": os.getenv("SERVICE_NAME", "Agent VC Investment Diagnosis"),
            "tags": ["agent-vc", "okx-ai", "diagnosis"],
        },
        "accepts": [build_x402_accept()],
    }
    if os.getenv("X402_INCLUDE_DISCOVERY_IN_HEADER", "0") == "1":
        payload["extensions"] = {"bazaar": bazaar_discovery_extension()}
    return payload


def x402_cors_headers() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-PAYMENT, PAYMENT-SIGNATURE, Authorization",
        "Access-Control-Expose-Headers": "PAYMENT-REQUIRED, PAYMENT-RESPONSE, X-PAYMENT, X-PAYMENT-RESPONSE",
    }


def payment_required_headers(payload: dict[str, Any]) -> dict[str, str]:
    return {"PAYMENT-REQUIRED": b64_json(payload), **x402_cors_headers()}


def payment_signature_header(request: Request) -> str | None:
    return request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("X-PAYMENT")


def decode_header_json(value: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(value).decode())


def looks_like_evm_address(value: str) -> bool:
    return value.startswith("0x") and len(value) == 42


def x402_strict_signature_verify() -> bool:
    return os.getenv("X402_STRICT_SIGNATURE_VERIFY", "0") == "1"


def validate_payment_signature(header: str) -> tuple[bool, str, str]:
    try:
        envelope = decode_header_json(header)
        accepted = envelope.get("accepted")
        payload = envelope.get("payload")
        if not isinstance(accepted, dict) or not isinstance(payload, dict):
            return False, "", "Malformed payment signature."

        expected = build_x402_accept()
        for key in ("scheme", "network", "asset", "amount", "payTo"):
            if str(accepted.get(key, "")).lower() != str(expected[key]).lower():
                return False, "", f"Payment field mismatch: {key}."

        authorization = payload.get("authorization")
        signature = payload.get("signature")
        if not isinstance(authorization, dict) or not isinstance(signature, str):
            return False, "", "Missing authorization signature."

        auth_from = str(authorization.get("from", ""))
        auth_to = str(authorization.get("to", ""))
        auth_value = str(authorization.get("value", ""))
        valid_after = int(str(authorization.get("validAfter", "0")))
        valid_before = int(str(authorization.get("validBefore", "0")))
        nonce = str(authorization.get("nonce", ""))
        now = int(time.time())
        if not looks_like_evm_address(auth_from) or not looks_like_evm_address(auth_to):
            return False, "", "Payment authorization contains an invalid EVM address."
        if not signature.startswith("0x") or len(signature) < 10:
            return False, "", "Payment signature format is invalid."
        if auth_to.lower() != str(expected["payTo"]).lower() or auth_value != str(expected["amount"]):
            return False, "", "Authorization does not match this resource."
        if valid_after > now or valid_before < now:
            return False, "", "Payment authorization is outside its validity window."
        if not x402_strict_signature_verify():
            return True, auth_from, ""

        from eth_account import Account
        from eth_account.messages import encode_typed_data

        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "TransferWithAuthorization",
            "domain": {
                "name": str(expected["extra"]["name"]),
                "version": str(expected["extra"]["version"]),
                "chainId": x402_chain_id(),
                "verifyingContract": str(expected["asset"]),
            },
            "message": {
                "from": auth_from,
                "to": auth_to,
                "value": int(auth_value),
                "validAfter": valid_after,
                "validBefore": valid_before,
                "nonce": nonce,
            },
        }
        recovered = Account.recover_message(encode_typed_data(full_message=typed_data), signature=signature)
        if recovered.lower() != auth_from.lower():
            return False, "", "Payment signature does not match the authorization sender."
        return True, auth_from, ""
    except Exception as exc:
        return False, "", f"Invalid payment signature: {exc}"


def configure_okx_x402() -> None:
    if not x402_enabled() or x402_mode() == "sdk":
        return

    @app.middleware("http")
    async def okx_x402_middleware(request: Request, call_next: Any) -> Response:
        if request.url.path != "/evaluate" or request.method.upper() != "POST":
            return await call_next(request)

        header = payment_signature_header(request)
        if not header:
            payload = build_payment_required(request)
            return JSONResponse(
                content=payload,
                status_code=402,
                headers=payment_required_headers(payload),
            )

        valid, payer, error = validate_payment_signature(header)
        if not valid:
            payload = build_payment_required(request, error)
            return JSONResponse(
                content=payload | {"code": "payment_verification_failed", "message": error},
                status_code=402,
                headers=payment_required_headers(payload),
            )

        request.state.payment_payer = payer
        response = await call_next(request)
        if response.status_code < 400:
            response.headers["PAYMENT-RESPONSE"] = b64_json(
                {
                    "success": True,
                    "status": "success",
                    "payer": payer,
                    "transaction": "",
                    "network": x402_network(),
                }
            )
            for key, value in x402_cors_headers().items():
                response.headers.setdefault(key, value)
        return response


def configure_x402() -> None:
    if not x402_enabled() or x402_mode() != "sdk":
        return

    pay_to = os.getenv("X402_PAY_TO") or os.getenv("PAY_TO_ADDRESS")
    if not pay_to:
        raise RuntimeError("X402_ENABLED=1 requires X402_PAY_TO or PAY_TO_ADDRESS")

    missing_auth = [
        name
        for name in ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE")
        if not os.getenv(name)
    ]
    if missing_auth:
        raise RuntimeError(f"X402_MODE=sdk requires official OKX Payment SDK credentials: {', '.join(missing_auth)}")

    try:
        from x402.http import OKXAuthConfig, OKXFacilitatorClient, OKXFacilitatorConfig, PaymentOption
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact.server import ExactEvmScheme
        from x402.server import x402ResourceServer
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install dependencies with `pip install -r requirements.txt`") from exc

    network = x402_network()
    facilitator = OKXFacilitatorClient(
        OKXFacilitatorConfig(
            auth=OKXAuthConfig(
                api_key=os.getenv("OKX_API_KEY", ""),
                secret_key=os.getenv("OKX_SECRET_KEY", ""),
                passphrase=os.getenv("OKX_PASSPHRASE", ""),
            ),
            base_url=os.getenv("OKX_BASE_URL", "https://web3.okx.com"),
            sync_settle=os.getenv("X402_SYNC_SETTLE", "1") == "1",
        )
    )

    resource_server = x402ResourceServer(facilitator)
    resource_server.register(network, ExactEvmScheme())

    routes = {
        "POST /evaluate": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme=os.getenv("X402_SCHEME", "exact"),
                    price=x402_price_display(),
                    network=network,
                    pay_to=pay_to,
                    max_timeout_seconds=int(os.getenv("X402_MAX_TIMEOUT_SECONDS", "300")),
                )
            ],
            description="Agent VC investment diagnosis report for OKX.AI Agent projects.",
            mime_type="application/json",
        )
    }

    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=resource_server)


configure_okx_x402()
configure_x402()


def absolute_url(request: Request, path: str) -> str:
    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base:
        return f"{public_base.rstrip('/')}{path}"
    render_external_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if render_external_hostname:
        return f"https://{render_external_hostname}{path}"
    return str(request.base_url).rstrip("/") + path


def request_adapter(request: Request) -> Any:
    """Adapter so existing a2mcp/openapi helpers can read headers."""

    class Adapter:
        headers = request.headers

    return Adapter()


def require_owner(request: Request) -> None:
    expected = os.getenv("OWNER_ACCESS_TOKEN")
    provided = request.headers.get("X-Agent-VC-Owner-Token") or request.query_params.get("owner_token")
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Owner token required")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.head("/")
async def head_index() -> Response:
    return Response(content=b"", media_type="text/html", headers={"Content-Length": "0"})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "agent-vc",
        "version": "0.1.0",
        "llm_configured": bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")),
        "x402_enabled": x402_enabled(),
    }


@app.head("/health")
async def head_health() -> JSONResponse:
    return JSONResponse(content=None, headers={"Content-Length": "0"})


@app.get("/schema")
async def schema() -> dict[str, Any]:
    return {
        "input": INPUT_SCHEMA,
        "output": REPORT_SCHEMA_HINT,
        "endpoints": {
            "POST /interview": "Generate VC questions from project input.",
            "POST /evaluate": "Return VC report JSON and apply hard investment quota gate.",
        },
    }


@app.get("/evaluate")
async def evaluate_probe(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "service": os.getenv("SERVICE_NAME", "Agent VC Investment Diagnosis"),
        "service_type": "A2MCP",
        "method": "POST",
        "endpoint": absolute_url(request, "/evaluate"),
        "payment_required_for_post": x402_enabled(),
        "x402": {
            "enabled": x402_enabled(),
            "network": x402_network(),
            "asset": x402_asset(),
            "amount": x402_price_amount() if x402_enabled() else None,
            "pay_to_configured": bool(os.getenv("X402_PAY_TO")),
        },
        "request_schema": INPUT_SCHEMA,
        "note": "Send POST /evaluate with a project object. Paid calls receive HTTP 402 first and return a report after payment replay.",
    }


@app.head("/evaluate")
async def head_evaluate() -> Response:
    return Response(content=b"", media_type="application/json", headers={"Content-Length": "0"})


@app.options("/evaluate")
async def options_evaluate() -> Response:
    return Response(
        status_code=204,
        headers={
            "Allow": "GET, HEAD, OPTIONS, POST",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS, POST",
            "Access-Control-Allow-Headers": "Content-Type, X-PAYMENT, PAYMENT-SIGNATURE",
            "Access-Control-Max-Age": "600",
        },
    )


@app.get("/integration-check")
async def integration_check(request: Request) -> dict[str, Any]:
    return {
        "ok": True,
        "service": os.getenv("SERVICE_NAME", "Agent VC Investment Diagnosis"),
        "public_base_url": absolute_url(request, ""),
        "web_landing_url": absolute_url(request, "/"),
        "paid_agent_endpoint": absolute_url(request, "/evaluate"),
        "a2mcp_manifest_url": absolute_url(request, "/a2mcp.json"),
        "openapi_url": absolute_url(request, "/openapi.json"),
        "paid_report_url_template": absolute_url(request, "/agent/reports/{report_token}"),
        "browser_free_full_report_enabled": os.getenv("DEMO_EVALUATE_ENABLED", "0") == "1",
        "owner_preview_enabled": bool(os.getenv("OWNER_ACCESS_TOKEN")),
        "storage": storage_health(),
        "x402": {
            "enabled": x402_enabled(),
            "mode": x402_mode(),
            "price": os.getenv("X402_PRICE", "5"),
            "amount": x402_price_amount() if x402_enabled() else None,
            "network": x402_network(),
            "scheme": os.getenv("X402_SCHEME", "exact"),
            "asset": x402_asset(),
            "asset_name": x402_asset_name(),
            "pay_to_configured": bool(os.getenv("X402_PAY_TO")),
            "strict_signature_verify": x402_strict_signature_verify(),
            "discovery_in_payment_header": os.getenv("X402_INCLUDE_DISCOVERY_IN_HEADER", "0") == "1",
        },
        "agent_client_contract": {
            "request_schema_present": True,
            "output_schema_present": True,
            "returns_report_url": True,
            "returns_chat_summary": True,
            "returns_result_first_message": True,
            "returns_founder_next_action": True,
            "returns_shareable_text": True,
        },
        "llm": {
            "configured": bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")),
            "model": os.getenv("LLM_MODEL", "deepseek-chat"),
        },
    }


@app.get("/openapi.json")
async def openapi_json(request: Request) -> dict[str, Any]:
    return openapi_document(request_adapter(request))


@app.get("/a2mcp.json")
async def a2mcp_json(request: Request) -> dict[str, Any]:
    doc = a2mcp_document(request_adapter(request))
    doc["service"]["endpoint"] = absolute_url(request, "/evaluate")
    doc["supportingEndpoints"] = {
        "webDemo": absolute_url(request, "/"),
        "health": absolute_url(request, "/health"),
        "integrationCheck": absolute_url(request, "/integration-check"),
        "openapi": absolute_url(request, "/openapi.json"),
        "schema": absolute_url(request, "/schema"),
    }
    doc["status"]["paymentGate"] = x402_enabled()
    return doc


@app.get("/reports/{report_id}", response_class=HTMLResponse)
async def report(report_id: int) -> str:
    with connect() as conn:
        evaluation = get_evaluation(conn, report_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_page(evaluation)


@app.get("/agent/reports/{report_token}", response_class=HTMLResponse)
async def agent_report(report_token: str) -> str:
    with connect() as conn:
        evaluation = get_evaluation_by_token(conn, report_token)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_page(evaluation)


def run_evaluation(payload: dict[str, Any], request: Request, *, owner_preview: bool = False) -> dict[str, Any]:
    project = payload.get("project")
    answers = payload.get("answers", [])
    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="Expected object field: project")
    if not isinstance(answers, list):
        raise HTTPException(status_code=400, detail="Expected array field: answers")

    report = evaluate_project(project, answers)
    fingerprint = project_fingerprint(project)
    user_key = submitter_key(project)
    contact_hint = str(project.get("contact") or project.get("email") or "")
    payer_wallet = str(getattr(request.state, "payment_payer", "") or project.get("payer_wallet") or "")
    source = "owner_preview" if owner_preview else "agent_client"
    report_token = secrets.token_urlsafe(18)
    paid_report_url = absolute_url(request, f"/agent/reports/{report_token}")
    with connect() as conn:
        duplicate = duplicate_today(conn, project_fingerprint=fingerprint, submitter_key=user_key)
        gate = apply_investment_gate(report, conn, duplicate=duplicate)
        report["paid_report_url"] = paid_report_url
        report["award_result"] = gate
        client_summary = build_client_summary(report, gate, paid_report_url)
        report["client_summary"] = client_summary
        request_id = save_evaluation(
            conn,
            project_name=str(report.get("project_name") or project.get("name") or "Unnamed Agent"),
            project=project,
            answers=answers,
            report=report,
            gate=gate,
            project_fingerprint=fingerprint,
            submitter_key=user_key,
            duplicate=duplicate,
            contact_hint=contact_hint,
            report_token=report_token,
            report_url=paid_report_url,
            payer_wallet=payer_wallet,
            source=source,
            owner_preview=owner_preview,
        )
    sync_status = sync_evaluation(
        {
            "request_id": request_id,
            "report_token": report_token,
            "paid_report_url": paid_report_url,
            "report_url": paid_report_url,
            "source": source,
            "payer_wallet": payer_wallet,
            "project": project,
            "answers": answers,
            "project_fingerprint": fingerprint,
            "submitter_key": user_key,
            "duplicate_today": duplicate,
            "contact_hint": contact_hint,
            "investment_gate": gate,
            "client_summary": client_summary,
            "report": report,
            "owner_preview": owner_preview,
        }
    )

    return {
        "request_id": request_id,
        "report_token": report_token,
        "report_url": paid_report_url,
        "legacy_report_url": absolute_url(request, f"/reports/{request_id}"),
        "investment_gate": gate,
        "client_summary": client_summary,
        "sync": sync_status,
        "source": source,
        "payer_wallet": payer_wallet,
        "owner_preview": owner_preview,
        "report": report,
    }


@app.get("/owner/dashboard", response_class=HTMLResponse)
async def owner_dashboard() -> str:
    return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent VC Owner Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f4ef;
      --panel: #ffffff;
      --line: #d8d2c5;
      --text: #202124;
      --muted: #6f6a61;
      --accent: #9b6b2f;
      --ok: #1f7a4d;
      --warn: #a65d12;
      --bad: #9b2f2f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: #fffaf0;
      padding: 24px;
    }
    main { padding: 24px; max-width: 1440px; margin: 0 auto; }
    h1 { margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }
    p { margin: 0; color: var(--muted); }
    .controls {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) 120px auto auto;
      gap: 10px;
      margin: 18px 0;
      align-items: center;
    }
    input, button {
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
    }
    input { padding: 0 12px; background: var(--panel); color: var(--text); }
    button {
      padding: 0 14px;
      background: var(--text);
      color: white;
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary { background: var(--panel); color: var(--text); }
    .status { min-height: 24px; margin-bottom: 14px; color: var(--muted); }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }
    table { width: 100%; border-collapse: collapse; min-width: 1180px; }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }
    th { background: #fbf7ef; color: #3c3832; position: sticky; top: 0; }
    tr:last-child td { border-bottom: 0; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fbf7ef;
      white-space: nowrap;
    }
    .candidate { color: var(--ok); border-color: #9ac4ad; background: #edf7f1; }
    .duplicate { color: var(--warn); border-color: #d9b17b; background: #fff5e7; }
    .preview { color: var(--muted); }
    details { max-width: 360px; }
    pre {
      max-height: 280px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      padding: 10px;
      border-radius: 6px;
      background: #f7f4ee;
      border: 1px solid var(--line);
    }
    @media (max-width: 760px) {
      header, main { padding: 16px; }
      .controls { grid-template-columns: 1fr; }
      table { min-width: 980px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Agent VC 后台</h1>
    <p>查看付费 Agent Client 调用、owner preview、投资候选、联系方式、付款钱包和报告链接。</p>
  </header>
  <main>
    <div class="controls">
      <input id="token" type="password" placeholder="输入 OWNER_ACCESS_TOKEN" autocomplete="off" />
      <input id="limit" type="number" min="1" max="500" value="100" />
      <button id="load">加载记录</button>
      <button id="csv" class="secondary">导出 CSV</button>
    </div>
    <div id="status" class="status">Token 只保存在当前浏览器 localStorage，不会写进页面或数据库。</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>时间</th>
            <th>项目</th>
            <th>分数</th>
            <th>投资状态</th>
            <th>联系方式</th>
            <th>付款钱包</th>
            <th>来源</th>
            <th>报告</th>
            <th>提交内容</th>
            <th>追问回答</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </main>
  <script>
    const tokenInput = document.querySelector('#token');
    const limitInput = document.querySelector('#limit');
    const statusEl = document.querySelector('#status');
    const rowsEl = document.querySelector('#rows');
    tokenInput.value = localStorage.getItem('agent_vc_owner_token') || '';

    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[ch]));
    }

    function pill(text, cls = '') {
      return `<span class="pill ${cls}">${esc(text)}</span>`;
    }

    function projectLine(project) {
      if (!project || typeof project !== 'object') return '';
      return project.one_liner || project.summary || project.problem || '';
    }

    function renderRows(items) {
      if (!items.length) {
        rowsEl.innerHTML = '<tr><td colspan="11">暂无记录。</td></tr>';
        return;
      }
      rowsEl.innerHTML = items.map((row) => {
        const project = row.project && typeof row.project === 'object' ? row.project : {};
        const answers = Array.isArray(row.answers) ? row.answers : [];
        const candidate = row.final_candidate ? pill('候选', 'candidate') : pill('未入选');
        const duplicate = row.duplicate_today ? pill('重复', 'duplicate') : '';
        const source = row.source === 'owner_preview' ? pill('owner preview', 'preview') : pill(row.source || 'agent client');
        const report = row.report_url ? `<a href="${esc(row.report_url)}" target="_blank" rel="noreferrer">打开报告</a>` : '';
        return `
          <tr>
            <td>${esc(row.id)}</td>
            <td>${esc(row.created_at)}</td>
            <td><strong>${esc(row.project_name)}</strong><br><span>${esc(projectLine(project))}</span></td>
            <td>${esc(row.total_score)}/100<br>${esc(row.recommendation || '')}</td>
            <td>${candidate} ${duplicate}</td>
            <td>${esc(row.contact_hint || project.contact || project.email || '')}</td>
            <td>${esc(row.payer_wallet || '')}</td>
            <td>${source}</td>
            <td>${report}</td>
            <td><details><summary>查看</summary><pre>${esc(JSON.stringify(project, null, 2))}</pre></details></td>
            <td><details><summary>${answers.length} 条</summary><pre>${esc(JSON.stringify(answers, null, 2))}</pre></details></td>
          </tr>
        `;
      }).join('');
    }

    async function loadRows() {
      const token = tokenInput.value.trim();
      if (!token) {
        statusEl.textContent = '请先输入 OWNER_ACCESS_TOKEN。';
        return;
      }
      localStorage.setItem('agent_vc_owner_token', token);
      statusEl.textContent = '正在加载...';
      rowsEl.innerHTML = '';
      const limit = Math.max(1, Math.min(Number(limitInput.value || 100), 500));
      const res = await fetch(`/owner/evaluations?limit=${limit}`, {
        headers: { 'X-Agent-VC-Owner-Token': token }
      });
      if (!res.ok) {
        statusEl.textContent = res.status === 401 ? 'Token 不正确。' : `加载失败：HTTP ${res.status}`;
        return;
      }
      const data = await res.json();
      statusEl.textContent = `已加载 ${data.count} 条记录。`;
      renderRows(data.items || []);
    }

    async function downloadCsv() {
      const token = tokenInput.value.trim();
      if (!token) {
        statusEl.textContent = '请先输入 OWNER_ACCESS_TOKEN。';
        return;
      }
      localStorage.setItem('agent_vc_owner_token', token);
      const limit = Math.max(1, Math.min(Number(limitInput.value || 500), 500));
      const res = await fetch(`/owner/evaluations.csv?limit=${limit}`, {
        headers: { 'X-Agent-VC-Owner-Token': token }
      });
      if (!res.ok) {
        statusEl.textContent = res.status === 401 ? 'Token 不正确。' : `导出失败：HTTP ${res.status}`;
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'agent-vc-evaluations.csv';
      a.click();
      URL.revokeObjectURL(url);
    }

    document.querySelector('#load').addEventListener('click', loadRows);
    document.querySelector('#csv').addEventListener('click', downloadCsv);
    tokenInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') loadRows();
    });
  </script>
</body>
</html>
"""


@app.get("/owner/evaluations")
async def owner_evaluations(request: Request, limit: int = 100) -> dict[str, Any]:
    require_owner(request)
    with connect() as conn:
        rows = list_evaluations(conn, limit=limit)
    return {"count": len(rows), "items": rows}


@app.get("/owner/evaluations.csv")
async def owner_evaluations_csv(request: Request, limit: int = 500) -> Response:
    require_owner(request)
    with connect() as conn:
        rows = list_evaluations(conn, limit=limit)

    output = io.StringIO()
    fieldnames = [
        "id",
        "created_at",
        "project_name",
        "total_score",
        "recommendation",
        "final_candidate",
        "duplicate_today",
        "contact_hint",
        "payer_wallet",
        "source",
        "report_url",
        "project_one_liner",
        "project_website",
        "project_twitter",
        "project_agent_wallet",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        project = row.get("project") if isinstance(row.get("project"), dict) else {}
        writer.writerow(
            {
                "id": row.get("id"),
                "created_at": row.get("created_at"),
                "project_name": row.get("project_name"),
                "total_score": row.get("total_score"),
                "recommendation": row.get("recommendation"),
                "final_candidate": row.get("final_candidate"),
                "duplicate_today": row.get("duplicate_today"),
                "contact_hint": row.get("contact_hint"),
                "payer_wallet": row.get("payer_wallet"),
                "source": row.get("source"),
                "report_url": row.get("report_url"),
                "project_one_liner": project.get("one_liner") or project.get("summary") or "",
                "project_website": project.get("website") or project.get("product_url") or "",
                "project_twitter": project.get("twitter") or project.get("x") or "",
                "project_agent_wallet": project.get("agent_wallet") or project.get("wallet_address") or "",
            }
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=agent-vc-evaluations.csv"},
    )


@app.post("/interview")
async def interview(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project", payload)
    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="invalid_project")
    return generate_interview(project)


@app.post("/owner/interview")
async def owner_interview(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_owner(request)
    project = payload.get("project", payload)
    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="invalid_project")
    questions = generate_interview(project)
    return {
        "owner_preview": True,
        "payment_required": False,
        "next_step": "answer_questions",
        "questions": questions.get("questions", []),
        "agent_client_style_message": (
            "我会先追问 3 个投资人最关心的问题。你回答后，我会生成完整评分、投资结论、"
            "改进建议和 HTML 报告链接。"
        ),
    }


@app.post("/evaluate")
async def evaluate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return run_evaluation(payload, request)


@app.post("/owner/evaluate")
async def owner_evaluate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_owner(request)
    result = run_evaluation(payload, request, owner_preview=True)
    result["owner_note"] = "Owner preview call: x402 skipped, saved for report preview, excluded from public quota counting."
    return result


@app.post("/owner/simulate")
async def owner_simulate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_owner(request)
    project = payload.get("project")
    answers = payload.get("answers", [])
    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="Expected object field: project")
    if not isinstance(answers, list):
        raise HTTPException(status_code=400, detail="Expected array field: answers")

    questions = generate_interview(project).get("questions", [])
    conversation: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": "I would like to use Agent VC to evaluate my Agent project.",
        },
        {
            "role": "agent",
            "content": (
                "可以。我需要先了解项目名称、一句话介绍、目标用户和核心问题。"
                "如果你愿意，也可以补充产品链接、Agent 钱包、traction 和联系方式。"
            ),
        },
        {"role": "user", "content": project},
        {
            "role": "agent",
            "content": "我会先补充 3 个投资人追问，再生成最终投资评估。",
            "questions": questions,
        },
    ]

    if not answers:
        return {
            "owner_preview": True,
            "payment_required": False,
            "stage": "questions_ready",
            "next_step": "POST the same payload with answers[] to /owner/simulate or /owner/evaluate.",
            "conversation": conversation,
            "questions": questions,
        }

    result = run_evaluation(payload, request, owner_preview=True)
    summary = result.get("client_summary", {})
    conversation.extend(
        [
            {"role": "user", "content": answers},
            {
                "role": "agent",
                "content": summary.get("chat_summary") or summary.get("headline"),
                "result_first_message": summary.get("result_first_message"),
                "score_line": summary.get("score_line"),
                "founder_next_action": summary.get("founder_next_action"),
                "report_url": result.get("report_url"),
            },
        ]
    )
    return {
        "owner_preview": True,
        "payment_required": False,
        "stage": "report_ready",
        "conversation": conversation,
        "result": result,
    }


@app.post("/demo/evaluate")
async def demo_evaluate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if os.getenv("DEMO_EVALUATE_ENABLED", "0") != "1":
        raise HTTPException(status_code=403, detail="完整研报、入库和 100 USDT 支持筛选仅通过 Agent Client 付费调用 /evaluate 完成。")
    return run_evaluation(payload, request)
