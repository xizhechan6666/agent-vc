"""Lightweight Agent wallet verification.

This module is intentionally conservative. V1 does not claim deep fund-flow
forensics; it creates a structured optional evidence block that can be enriched
later with OKLink or another indexed transaction API.
"""

from __future__ import annotations

import re
from typing import Any


XLAYER_CHAIN_ID = 196
XLAYER_EXPLORER_BASE = "https://www.oklink.com/x-layer/evm/address"


def build_wallet_research(project: dict[str, Any]) -> dict[str, Any]:
    address = str(
        project.get("agent_wallet_address") or project.get("wallet_address") or ""
    ).strip()
    chain = normalize_chain(project.get("wallet_chain") or project.get("chain") or "xlayer")

    if not address:
        return {
            "status": "not_provided",
            "chain": chain,
            "address": "",
            "verified_ownership": False,
            "explorer_url": "",
            "integrity_score": 0,
            "metrics": {},
            "positive_signals": [],
            "red_flags": [],
            "notes": ["项目方未提供 Agent 钱包地址；本次不计入链上验证加分。"],
        }

    if not is_evm_address(address):
        return {
            "status": "invalid_address",
            "chain": chain,
            "address": address,
            "verified_ownership": False,
            "explorer_url": "",
            "integrity_score": 0,
            "metrics": {},
            "positive_signals": [],
            "red_flags": ["钱包地址格式不是有效 EVM 地址，暂不能作为 X Layer 验证证据。"],
            "notes": ["X Layer v1 仅支持 0x 开头的 EVM 地址。"],
        }

    explorer_url = f"{XLAYER_EXPLORER_BASE}/{address}"
    signature = str(project.get("wallet_signature") or "").strip()
    signer_source = str(project.get("wallet_source") or "").strip()
    verified_ownership = bool(signature or signer_source in {"x402_payer", "agent_client_payer"})

    positive_signals = ["已提供可访问的 X Layer / OKLink 钱包核验链接。"]
    red_flags = []
    notes = [
        "当前版本只做轻量验证：地址格式、链路归属、浏览器核验入口和项目方自述证据。",
        "尚未接入完整交易索引，因此不会把交易笔数直接视为真实用户或收入证据。",
    ]
    integrity_score = 4

    if verified_ownership:
        integrity_score += 3
        positive_signals.append("钱包所有权已有签名或 Agent Client 支付方来源支持。")
    else:
        red_flags.append("尚未完成钱包签名或 x402 付款方绑定，不能证明该地址一定属于提交方。")
        notes.append("后续版本应要求该钱包签名 nonce，或直接读取 x402 payer/signer wallet。")

    if str(project.get("onchain_evidence") or "").strip():
        integrity_score += 2
        positive_signals.append("项目方补充了链上或产品验证说明，可作为人工复核线索。")

    return {
        "status": "basic_check" if not verified_ownership else "ownership_supported",
        "chain": chain,
        "chain_id": XLAYER_CHAIN_ID,
        "address": address,
        "verified_ownership": verified_ownership,
        "explorer_url": explorer_url,
        "integrity_score": min(integrity_score, 10),
        "metrics": {
            "tx_count_observed": None,
            "unique_counterparties": None,
            "top_counterparty_share": None,
            "reciprocal_transfer_ratio": None,
        },
        "positive_signals": positive_signals,
        "red_flags": red_flags,
        "notes": notes,
    }


def wallet_bonus(wallet_research: dict[str, Any]) -> int:
    status = wallet_research.get("status")
    if status in {"not_provided", "invalid_address"}:
        return 0
    bonus = 3
    if wallet_research.get("verified_ownership"):
        bonus += 3
    if wallet_research.get("positive_signals"):
        bonus += 2
    if wallet_research.get("red_flags"):
        bonus -= 1
    return max(0, min(bonus, 8))


def wallet_evidence_lines(wallet_research: dict[str, Any]) -> list[str]:
    if not wallet_research or wallet_research.get("status") == "not_provided":
        return []
    lines = []
    address = wallet_research.get("address")
    if address:
        lines.append(f"Agent 钱包地址：{address}")
    explorer_url = wallet_research.get("explorer_url")
    if explorer_url:
        lines.append(f"X Layer 浏览器核验链接：{explorer_url}")
    for item in wallet_research.get("positive_signals") or []:
        lines.append(str(item))
    for item in wallet_research.get("red_flags") or []:
        lines.append(str(item))
    return lines


def normalize_chain(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "")
    if text in {"xlayer", "x-layer", "okxxlayer", "196", "eip155:196"}:
        return "xlayer"
    return text or "xlayer"


def is_evm_address(value: Any) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", str(value or "").strip()))
