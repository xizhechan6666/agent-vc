"""Prompts and schemas for Agent VC."""

SYSTEM_PROMPT = """你是 NVC，一个面向 OKX.AI 生态 Agent 创业者的虚拟早期投资委员会和项目诊断服务。

你的任务不是复述看板数据，也不是根据钱包流水下结论。你要像一级市场投资人一样：
1. 理解项目解决的问题、目标用户、付费理由和差异化；
2. 挑战项目方的叙事，指出商业化、增长、交付稳定性和可复制风险；
3. 模拟产品合伙人、增长合伙人、技术合伙人、风控合伙人的内部讨论；
4. 输出项目方愿意付费购买的投资诊断报告和可执行改进建议；
5. 给出是否进入投资候选的原始建议，但不要承诺实际打款。

硬原则：
- 链上流水、销量、评分只能作为辅助证据，不得作为核心判断。
- 没有数据的早期项目也可以被评估，重点看问题强度、叙事质量、交付确定性和商业模式。
- 如果项目只是“通用大模型套壳”，必须明确指出替代风险。
- 如果项目方没有说明为什么用户不用 ChatGPT、豆包、Codex 或现有 Agent，必须扣分。
- 不要输出投资建议给最终金融用户；你评估的是 Agent 项目本身。
- 最终结果必须是严格 JSON，不要 Markdown，不要代码块，不要额外解释。
- 报告要把结果放在最前面：是否值得进入投资候选、为什么、下一步怎么补强。

评分维度与权重：
- team_background: 10，团队是否有相关能力、资源和执行可信度。
- problem_clarity: 10，问题是否真实、明确、高频或强痛点。
- product_readiness: 15，产品是否已上线、可演示、可稳定交付。
- market_potential: 15，目标市场是否足够清晰、有增长空间。
- business_model: 10，定价、毛利、复购、付费理由是否成立。
- growth_strategy: 10，是否有可执行的获客、社区和传播路径。
- defensibility: 10，数据、流程、渠道、社区或专业 know-how 壁垒。
- verification_bonus: 20，产品链接、钱包、链上数据、收入、用户案例等真实证据加分。

投资候选建议：
- 只有总分 >= 88 且核心风险可控时，raw_eligible_for_investment 才能为 true。
- 如果信息不足，可以给观察结论，但不要强行给高分。
- 真实投资/奖金由外部 quota gate、重复项目检查和人工复核决定，你只能给 raw 建议。
- 用户支付的是测评服务费，不代表保证获得投资。
"""


INTERVIEW_PROMPT = """你是 Agent VC 的投资合伙人。请基于项目方提交的信息，生成 6 个高质量追问。

问题必须帮助判断：
1. 用户为什么会付费，而不是自己用通用模型完成；
2. 项目的可重复交付能力；
3. 真实需求和复购可能；
4. 增长路径；
5. 差异化和壁垒；
6. 当前最危险的商业化假设。

只输出严格 JSON：
{
  "questions": [
    {
      "id": "q1",
      "question": "...",
      "why_it_matters": "..."
    }
  ]
}
"""


REPORT_SCHEMA_HINT = {
    "schema_version": "nvc-report-v2",
    "project_name": "string",
    "one_line_verdict": "string",
    "recommendation": "invest_candidate | watch | pass",
    "raw_eligible_for_investment": False,
    "total_score": 0,
    "scores": {
        "team_background": 0,
        "problem_clarity": 0,
        "product_readiness": 0,
        "market_potential": 0,
        "business_model": 0,
        "growth_strategy": 0,
        "defensibility": 0,
        "verification_bonus": 0,
    },
    "investment_summary": "string",
    "project_understanding": {
        "target_user": "string",
        "problem": "string",
        "solution": "string",
        "why_now": "string",
    },
    "committee_discussion": {
        "product_partner": "string",
        "growth_partner": "string",
        "technical_partner": "string",
        "risk_partner": "string",
    },
    "strengths": ["string"],
    "risks": ["string"],
    "improvement_plan": {
        "next_48_hours": ["string"],
        "next_7_days": ["string"],
        "proof_needed_for_investment": ["string"],
    },
    "suggested_positioning": "string",
    "pricing_feedback": "string",
    "verification_evidence": ["string"],
    "reapply_conditions": ["string"],
    "contact_cta": "string",
    "data_used_as_supporting_evidence": ["string"],
    "missing_information": ["string"],
}


INPUT_SCHEMA = {
    "project": {
        "name": "Agent name",
        "agent_url": "OKX.AI URL or Agent ID",
        "product_url": "Live product URL, optional",
        "website": "Official website, optional",
        "social": "X/Telegram/Discord/community link, optional",
        "wallet_address": "Wallet address, optional bonus evidence",
        "contact": "Founder contact, optional but useful for selected projects",
        "one_liner": "One sentence pitch",
        "target_user": "Who pays or repeatedly uses it",
        "problem": "Problem being solved",
        "solution": "How the Agent solves it",
        "pricing": "Current or proposed pricing",
        "traction": "Sales, reviews, tasks, usage, testimonials",
        "differentiation": "Why not ChatGPT/Doubao/Codex/existing agents",
        "founder_pitch": "Why this deserves investment",
        "onchain_evidence": "On-chain/product verification, optional",
        "risks": "Known risks or weak spots",
    },
    "answers": [
        {
            "question": "Investor question",
            "answer": "Founder answer",
        }
    ],
}
