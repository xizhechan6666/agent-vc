"""FastAPI entrypoint with optional x402 payment middleware."""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import FastAPI, HTTPException, Request
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
from agent_vc.store import connect, duplicate_today, get_evaluation, get_evaluation_by_token, save_evaluation
from agent_vc.sync import sync_evaluation
from app import INDEX_HTML, a2mcp_document, bazaar_discovery_extension, openapi_document, report_page


app = FastAPI(title="Agent VC API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)


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
    return {
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
        "extensions": {"bazaar": bazaar_discovery_extension()},
    }


def payment_signature_header(request: Request) -> str | None:
    return request.headers.get("PAYMENT-SIGNATURE") or request.headers.get("X-PAYMENT")


def decode_header_json(value: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(value).decode())


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
        if auth_to.lower() != str(expected["payTo"]).lower() or auth_value != str(expected["amount"]):
            return False, "", "Authorization does not match this resource."
        if valid_after > now or valid_before < now:
            return False, "", "Payment authorization is outside its validity window."

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
                content={},
                status_code=402,
                headers={"PAYMENT-REQUIRED": b64_json(payload)},
            )

        valid, payer, error = validate_payment_signature(header)
        if not valid:
            payload = build_payment_required(request, error)
            return JSONResponse(
                content={"error": "payment_verification_failed", "message": error},
                status_code=402,
                headers={"PAYMENT-REQUIRED": b64_json(payload)},
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
        return response


def configure_x402() -> None:
    if not x402_enabled() or x402_mode() != "sdk":
        return

    pay_to = os.getenv("X402_PAY_TO")
    if not pay_to:
        raise RuntimeError("X402_ENABLED=1 requires X402_PAY_TO")

    try:
        from x402.http.facilitator_client import FacilitatorConfig, HTTPFacilitatorClient
        from x402.http.middleware.fastapi import payment_middleware
        from x402.http.types import PaymentOption, RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.schemas import AssetAmount
        from x402.server import x402ResourceServer
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install dependencies with `pip install -r requirements.txt`") from exc

    network = x402_network()
    scheme = os.getenv("X402_SCHEME", "exact")
    price = AssetAmount(
        amount=x402_price_amount(),
        asset=x402_asset(),
        extra={"name": x402_asset_name(), "version": x402_asset_version()},
    )

    routes = {
        "POST /evaluate": RouteConfig(
            accepts=PaymentOption(
                scheme=scheme,
                pay_to=pay_to,
                price=price,
                network=network,
                max_timeout_seconds=int(os.getenv("X402_MAX_TIMEOUT_SECONDS", "300")),
            ),
            description="Agent VC investment diagnosis report for OKX.AI Agent projects.",
            mime_type="application/json",
            service_name=os.getenv("SERVICE_NAME", "Agent VC Investment Diagnosis"),
            tags=["agent-vc", "okx-ai", "diagnosis"],
            extensions={"bazaar": bazaar_discovery_extension()},
        )
    }

    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(url=os.getenv("X402_FACILITATOR_URL", "https://x402.org/facilitator"))
    )
    resource_server = x402ResourceServer(facilitator)
    resource_server.register(network, ExactEvmServerScheme())

    app.middleware("http")(
        payment_middleware(
            routes=routes,
            server=resource_server,
            sync_facilitator_on_start=os.getenv("X402_SYNC_FACILITATOR_ON_START", "1") == "1",
        )
    )


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


def run_evaluation(payload: dict[str, Any], request: Request) -> dict[str, Any]:
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
    report_token = secrets.token_urlsafe(18)
    with connect() as conn:
        duplicate = duplicate_today(conn, project_fingerprint=fingerprint, submitter_key=user_key)
        gate = apply_investment_gate(report, conn, duplicate=duplicate)
        paid_report_url = absolute_url(request, f"/agent/reports/{report_token}")
        report["paid_report_url"] = paid_report_url
        report["award_result"] = gate
        client_summary = build_client_summary(report, gate, paid_report_url)
        report["client_summary"] = client_summary
        request_id = save_evaluation(
            conn,
            project_name=str(report.get("project_name") or project.get("name") or "Unnamed Agent"),
            report=report,
            gate=gate,
            project_fingerprint=fingerprint,
            submitter_key=user_key,
            duplicate=duplicate,
            contact_hint=contact_hint,
            report_token=report_token,
        )
    sync_status = sync_evaluation(
        {
            "request_id": request_id,
            "report_token": report_token,
            "paid_report_url": absolute_url(request, f"/agent/reports/{report_token}"),
            "project_fingerprint": fingerprint,
            "submitter_key": user_key,
            "duplicate_today": duplicate,
            "contact_hint": contact_hint,
            "investment_gate": gate,
            "client_summary": client_summary,
            "report": report,
        }
    )

    return {
        "request_id": request_id,
        "report_token": report_token,
        "report_url": absolute_url(request, f"/agent/reports/{report_token}"),
        "legacy_report_url": absolute_url(request, f"/reports/{request_id}"),
        "investment_gate": gate,
        "client_summary": client_summary,
        "sync": sync_status,
        "report": report,
    }


@app.post("/interview")
async def interview(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project", payload)
    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="invalid_project")
    return generate_interview(project)


@app.post("/evaluate")
async def evaluate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return run_evaluation(payload, request)


@app.post("/demo/evaluate")
async def demo_evaluate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if os.getenv("DEMO_EVALUATE_ENABLED", "0") != "1":
        raise HTTPException(status_code=403, detail="完整研报、入库和 100 USDT 支持筛选仅通过 Agent Client 付费调用 /evaluate 完成。")
    return run_evaluation(payload, request)
