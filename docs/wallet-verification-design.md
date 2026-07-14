# Agent Wallet Verification Design

## Positioning

Agent wallet verification is an optional bonus layer, not a required input and not the core investment decision. It should help us answer one question:

> Does this Agent wallet show enough real on-chain behavior to improve confidence in the project, or does the activity look artificial?

The output should feed into `verification_bonus`, confidence notes, and the HTML report. It must not automatically trigger investment or payment.

## V1 Scope

V1 supports X Layer first.

The product should accept an optional `agent_wallet_address` field. If the user submits the assessment through a paid Agent Client, the preferred wallet should be the payer/signer wallet from the x402 payment flow when the SDK exposes it. If the user manually provides a different address, require a signature challenge before treating that address as verified.

V1 should return a compact `wallet_research` object:

```json
{
  "status": "not_provided | not_configured | insufficient_data | clean | suspicious | high_risk",
  "chain": "xlayer",
  "address": "0x...",
  "explorer_url": "https://www.oklink.com/x-layer/evm/address/0x...",
  "integrity_score": 0,
  "metrics": {
    "native_balance": "0",
    "tx_count_observed": 0,
    "token_transfer_count_observed": 0,
    "active_days": 0,
    "unique_counterparties": 0,
    "top_counterparty_share": 0,
    "top3_counterparty_share": 0,
    "reciprocal_transfer_ratio": 0,
    "repeated_amount_ratio": 0
  },
  "positive_signals": [],
  "red_flags": [],
  "notes": []
}
```

## Address Authenticity

Do not trust a typed wallet address by default.

Recommended hierarchy:

1. If the request is paid through Agent Client/x402 and the payment verification response exposes the payer or signer wallet, default to that wallet as the Agent wallet.
2. If the user wants to analyze a different wallet, issue a nonce and require `personal_sign` from that address.
3. If neither is available, mark the wallet as `unverified_submitted_address` and use it only as weak evidence.

This prevents users from submitting a high-quality third-party wallet as their own Agent wallet.

## Data Sources

### Primary: X Layer RPC

Use public X Layer RPC for low-cost baseline checks:

- `eth_chainId` to confirm chain identity.
- `eth_getBalance` for native OKB balance.
- `eth_getCode` to identify EOA vs contract.
- `eth_getLogs` for ERC-20 `Transfer` events when token contracts are known.
- `eth_getTransactionReceipt` if we already have transaction hashes.

Verified locally:

- `https://rpc.xlayer.tech` responds with chain ID `0xc4`, which is decimal `196`.
- `eth_blockNumber` also responds successfully.

Limit: plain RPC does not provide complete "all transactions by address" search. To get all normal transactions involving an address, we need an indexed API or our own indexer.

### Primary Explorer Link: OKLink X Layer

Use OKLink as the human-readable audit link:

```text
https://www.oklink.com/x-layer/evm/address/{address}
```

The service can include this link in the report so users and reviewers can manually inspect the address.

OKLink documentation confirms X Layer / `XLAYER` support in explorer tooling. For automated address transaction history, use OKLink API only after we confirm the exact address-history endpoint and API key terms. Do not assume it is free or public.

### Secondary: Etherscan V2

Etherscan V2 is useful for Ethereum, Base, Arbitrum, Polygon, and other supported EVM chains. It has direct endpoints for:

- normal transactions by address
- ERC-20 transfers by address
- internal transactions
- address labels / name tags

Current docs do not list X Layer as a supported Etherscan V2 chain, so it is not a V1 X Layer source.

### Secondary: Blockscout-Compatible Explorers

Blockscout exposes Etherscan-style account APIs:

- `txlist`
- `tokentx`
- `txlistinternal`
- balance APIs

If X Layer later has a reliable Blockscout instance, this becomes the simplest indexer route. No reliable X Layer Blockscout endpoint is confirmed for V1.

### Later: Dune

Dune is good for custom analytics and dashboards, but it requires API keys and may have credit/billing constraints. It should be used later for richer research, not for the first production dependency.

### Later: Arkham / Chainalysis / Commercial Forensics

These are strong for entity labels, fund-flow graphs, and compliance-grade tracing. They are useful for manual review and high-value candidates, but likely too heavy and costly for a 5 USDT automated assessment.

## Analysis Logic

Do not say "real user" only because the wallet has many transactions. Score based on structure.

Positive signals:

- Activity spans multiple days or weeks.
- Many distinct counterparties.
- Counterparties are not all newly funded by the same source.
- Stablecoin or protocol interactions match the submitted product story.
- Transfers are not all identical values.
- Inbound and outbound flows are not dominated by one or two addresses.

Red flags:

- High transaction count but one counterparty dominates.
- Same two or three wallets repeatedly send funds back and forth.
- Many transfers happen in short bursts with repeated amounts.
- Counterparties were created or funded at nearly the same time.
- Gross volume is high but net flow is near zero.
- Wallet has no relation to the submitted product, contract, site, or Agent identity.

Suggested thresholds for V1:

- `top_counterparty_share > 0.55`: suspicious concentration.
- `top3_counterparty_share > 0.8`: suspicious concentration.
- `reciprocal_transfer_ratio > 0.45`: possible circular activity.
- `repeated_amount_ratio > 0.35`: possible scripted behavior.
- `active_days < 2` and `tx_count_observed > 30`: burst activity, needs caution.
- `unique_counterparties < 4` and `tx_count_observed > 20`: weak evidence.

These thresholds are not hard fraud labels. They only lower confidence and reduce the verification bonus.

## Scoring Integration

Keep the current 100-point system:

- Base project/memo score: up to 80.
- Verification bonus: up to 20.

Suggested wallet contribution inside verification bonus:

- Valid Agent wallet ownership: +3
- Basic X Layer activity: +3
- Counterparty diversity: +4
- Activity consistency with submitted project: +4
- Low wash/circular-trading risk: +4
- Useful product/contract/explorer evidence: +2

If the wallet is suspicious, give no wallet bonus and add a confidence warning. Do not automatically reject the project unless there is obvious fraud.

## Report Copy

Use cautious language:

- Good: "该钱包提供了有限但正向的链上验证信号。交易对手分布相对分散，活动时间不是集中刷量形态。"
- Good: "交易笔数较多，但主要集中在少数地址之间，不能直接视为真实用户或真实收入证据。"
- Avoid: "该项目一定真实。"
- Avoid: "该项目存在诈骗。"

## Implementation Plan

1. Add optional fields: `agent_wallet_address`, `wallet_chain`, `wallet_signature`.
2. Add `agent_vc/wallet_research.py` with provider adapters:
   - `xlayer_rpc` for baseline checks.
   - `oklink` when exact API access is confirmed.
   - `blockscout` / `etherscan` for later multi-chain support.
3. Call wallet research only when an address is provided or x402 exposes payer wallet.
4. Store `wallet_research` in the evaluation JSON and database.
5. Include a "链上钱包验证" section in the HTML report.
6. Feed a summarized wallet result into the LLM prompt, but keep deterministic scoring in code.

## Open Questions

- Does the current OKX x402 SDK expose payer/signer wallet after payment verification?
- Which OKLink API endpoint and plan provide X Layer address transaction history?
- Which X Layer stablecoin contracts should we monitor first?
- Should we require signature verification before giving any wallet bonus, or allow a smaller unverified bonus?
