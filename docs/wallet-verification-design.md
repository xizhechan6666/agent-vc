# Agent Wallet Verification

Agent wallet verification is an optional evidence layer. It is not a required input and it must not automatically trigger investment support.

The goal is to improve confidence when a founder provides a real Agent wallet, while avoiding the false assumption that transaction count equals real users or revenue.

## Current Implemented Scope

The current implementation is intentionally conservative.

Implemented fields:

- `agent_wallet_address`
- `wallet_chain`
- `wallet_signature`
- `onchain_evidence`

Implemented output object:

```json
{
  "status": "not_provided | invalid_address | basic_check | ownership_supported",
  "chain": "xlayer",
  "chain_id": 196,
  "address": "0x...",
  "verified_ownership": false,
  "explorer_url": "https://www.oklink.com/x-layer/evm/address/0x...",
  "integrity_score": 0,
  "metrics": {
    "tx_count_observed": null,
    "unique_counterparties": null,
    "top_counterparty_share": null,
    "reciprocal_transfer_ratio": null
  },
  "positive_signals": [],
  "red_flags": [],
  "notes": []
}
```

Status meanings:

- `not_provided`: no wallet address was submitted.
- `invalid_address`: submitted wallet is not a valid 0x EVM address.
- `basic_check`: address format is valid and an OKLink X Layer explorer link can be generated, but ownership is not proven.
- `ownership_supported`: address has a wallet signature or a trusted payer/signer source.

## What It Does Today

The current code:

- accepts an optional X Layer-style EVM address;
- validates the address format;
- creates an OKLink X Layer explorer link;
- adds cautious positive signals and red flags;
- adds a small verification bonus;
- includes the wallet block in the JSON and HTML report.

The current code does not:

- query full transaction history;
- calculate complete counterparty concentration;
- identify wash trading automatically;
- prove that wallet volume is real revenue;
- trigger payout.

## Address Authenticity

A typed wallet address is weak evidence until ownership is supported.

Preferred hierarchy:

1. If x402 payment verification exposes the payer or signer wallet in a future SDK surface, default to that wallet.
2. If the user submits a different wallet, require a signature challenge.
3. If neither is available, treat the submitted address as unverified and only give limited evidence weight.

Current code already supports `wallet_signature` and `wallet_source`-style ownership signals, but does not yet issue nonce challenges itself.

## Data Sources

Current human-readable explorer:

```text
https://www.oklink.com/x-layer/evm/address/{address}
```

X Layer chain ID:

```text
eip155:196
```

Plain RPC can confirm chain identity, balance, code, logs, and known transaction receipts. It cannot provide a complete "all transactions by address" history without indexing.

Do not use Dune, Blockscout, Etherscan, or OKLink API as production dependencies until the exact X Layer endpoint, API terms, rate limits, and cost are confirmed.

## Future Transaction Analysis

When an indexed X Layer transaction source is confirmed, add these metrics:

- `tx_count_observed`
- `active_days`
- `unique_counterparties`
- `top_counterparty_share`
- `top3_counterparty_share`
- `reciprocal_transfer_ratio`
- `repeated_amount_ratio`
- stablecoin transfer count and volume

Suggested risk thresholds:

- `top_counterparty_share > 0.55`: suspicious concentration.
- `top3_counterparty_share > 0.80`: suspicious concentration.
- `reciprocal_transfer_ratio > 0.45`: possible circular activity.
- `repeated_amount_ratio > 0.35`: possible scripted behavior.
- `active_days < 2` and `tx_count_observed > 30`: burst activity, needs caution.
- `unique_counterparties < 4` and `tx_count_observed > 20`: weak evidence.

These thresholds are confidence warnings, not fraud labels.

## Scoring Integration

The report remains a 100-point system:

- Base project score: up to 80.
- Verification bonus: up to 20.

Wallet evidence contributes only inside `verification_bonus`.

Current wallet bonus is deliberately capped and conservative:

- valid submitted wallet: small bonus;
- ownership support: additional bonus;
- red flags reduce bonus;
- no wallet does not block evaluation.

## Report Language

Use cautious wording.

Acceptable:

- "该钱包提供了有限但正向的链上验证信号。"
- "已提供钱包地址，但尚未证明该地址属于提交方。"
- "交易数据尚未完成穿透分析，不能直接视为真实用户或真实收入证据。"

Avoid:

- "该项目一定真实。"
- "仅凭当前钱包数据无法直接下高风险结论。"
- "交易笔数多，所以用户真实。"

## Integration Boundary

Wallet verification is separate from x402 payment.

- x402 verifies that a paid request can access `/evaluate`.
- wallet verification evaluates optional project evidence.
- candidate status still depends on server quota, duplicate checks, score threshold, and manual review.
