"""Evaluation and report generation."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from . import llm
from .prompt import INTERVIEW_PROMPT, REPORT_SCHEMA_HINT, SYSTEM_PROMPT
from .store import quota_preview


SCORE_KEYS = {
    "team_background": 10,
    "problem_clarity": 10,
    "product_readiness": 15,
    "market_potential": 15,
    "business_model": 10,
    "growth_strategy": 10,
    "defensibility": 10,
    "verification_bonus": 20,
}

SCORE_LABELS = {
    "team_background": "团队背景",
    "problem_clarity": "问题清晰度",
    "product_readiness": "产品成熟度",
    "market_potential": "市场潜力",
    "business_model": "商业模式",
    "growth_strategy": "增长策略",
    "defensibility": "竞争壁垒",
    "verification_bonus": "真实产品与链上验证加分",
}


def generate_interview(project: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "task": "generate_investor_questions",
        "project": project,
        "required_question_count": 6,
    }
    try:
        result = llm.call_json(INTERVIEW_PROMPT, payload)
        if isinstance(result.get("questions"), list) and result["questions"]:
            return result
    except llm.LLMError:
        pass

    return {
        "questions": [
            {
                "id": "q1",
                "question": "用户为什么会为这个 Agent 持续付费，而不是直接使用通用大模型或已有 Agent？",
                "why_it_matters": "这是判断商业化和替代风险的核心问题。",
            },
            {
                "id": "q2",
                "question": "请描述一次真实用户从输入需求到获得结果的完整流程，哪些步骤可验证？",
                "why_it_matters": "早期 Agent 最容易在交付稳定性上失分。",
            },
            {
                "id": "q3",
                "question": "你的定价依据是什么？用户在什么情况下会复购？",
                "why_it_matters": "单次好奇调用不是可投资的商业模式。",
            },
            {
                "id": "q4",
                "question": "你现在最可信的 traction 是什么？如果没有数据，最接近真实需求的证据是什么？",
                "why_it_matters": "数据可以少，但证据链不能完全空白。",
            },
            {
                "id": "q5",
                "question": "这个 Agent 的能力里，哪一部分最难被后来者复制？",
                "why_it_matters": "没有壁垒的 Agent 很难获得投资判断上的高分。",
            },
            {
                "id": "q6",
                "question": "如果只允许你在 48 小时内改一个东西来提高成交率，你会改什么？",
                "why_it_matters": "能否抓住关键瓶颈，反映创始人的产品判断。",
            },
        ]
    }


def evaluate_project(project: dict[str, Any], answers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "task": "evaluate_agent_startup",
        "project": project,
        "answers": answers or [],
        "output_schema_hint": REPORT_SCHEMA_HINT,
        "score_labels": SCORE_LABELS,
    }
    try:
        report = llm.call_json(SYSTEM_PROMPT, payload)
        return normalize_report(report, project)
    except llm.LLMError as exc:
        return heuristic_report(project, answers or [], str(exc))


def normalize_report(report: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    scores = report.get("scores")
    if not isinstance(scores, dict):
        scores = {}
    normalized_scores: dict[str, int] = {}
    for key, max_score in SCORE_KEYS.items():
        value = scores.get(key, 0)
        try:
            numeric = int(round(float(value)))
        except (TypeError, ValueError):
            numeric = 0
        normalized_scores[key] = min(max(numeric, 0), max_score)

    normalized_scores["verification_bonus"] = max(
        normalized_scores.get("verification_bonus", 0),
        verification_bonus_from_project(project),
    )
    total = sum(normalized_scores.values())
    recommendation = str(report.get("recommendation", "watch"))
    if recommendation not in {"invest_candidate", "watch", "pass"}:
        recommendation = "invest_candidate" if total >= minimum_score() else "watch" if total >= 60 else "pass"

    report["schema_version"] = "nvc-report-v2"
    report["project_name"] = str(report.get("project_name") or project.get("name") or "Unnamed Agent")
    report["scores"] = normalized_scores
    report["score_labels"] = SCORE_LABELS
    report["score_max"] = SCORE_KEYS
    report["total_score"] = total
    report["recommendation"] = recommendation
    report["raw_eligible_for_investment"] = bool(
        report.get("raw_eligible_for_investment")
        and total >= minimum_score()
        and recommendation == "invest_candidate"
    )
    report.setdefault("one_line_verdict", _default_verdict(total))
    report.setdefault("missing_information", [])
    report.setdefault("data_used_as_supporting_evidence", [])
    report.setdefault("verification_evidence", verification_evidence(project))
    report.setdefault("reapply_conditions", [])
    report.setdefault("contact_cta", default_contact_cta())
    return report


def apply_investment_gate(report: dict[str, Any], conn: Any, *, duplicate: bool = False) -> dict[str, Any]:
    quota = quota_preview(conn)
    score = int(report.get("total_score", 0))
    raw_eligible = bool(report.get("raw_eligible_for_investment"))
    threshold = minimum_score()
    final_candidate = raw_eligible and score >= threshold and quota["slots_remaining"] > 0 and not duplicate

    if final_candidate:
        status = "selected"
        headline = "恭喜，你的项目已通过本轮评估，并获得 NVC 提供的 100 USDT 早期投资支持。"
        reason = "通过模型原始建议、最低分阈值、重复提交检查和本轮投资候选名额限制；仍需人工核验后发放。"
    elif duplicate:
        status = "duplicate_limited"
        headline = "本轮暂未进入 100 USDT 早期投资支持名单。"
        reason = "系统识别到同一项目或同一提交人在今天已经测评过；为防止刷奖，本次不触发投资候选。"
    elif not raw_eligible:
        status = "not_selected"
        headline = "本轮暂未进入 100 USDT 早期投资支持名单。"
        reason = "报告建议暂不进入投资候选；可以按改进计划补充证据后重新提交。"
    elif score < threshold:
        status = "not_selected"
        headline = "本轮暂未进入 100 USDT 早期投资支持名单。"
        reason = f"总分未达到 {threshold} 分硬阈值。"
    else:
        status = "quota_limited"
        headline = "你的项目达到强观察标准，但本轮投资名额暂时已满。"
        reason = "本轮投资候选名额已用完；报告可标记为强观察，但不触发候选资格。"

    return {
        **quota,
        "minimum_score": threshold,
        "final_candidate": final_candidate,
        "candidate_status": status,
        "award_status": status,
        "award_amount_usdt": 100 if final_candidate else 0,
        "promotion_support_usdt": 500 if final_candidate else 0,
        "assessment_fee_usdt": int(os.getenv("SERVICE_FEE_USDT", "5")),
        "headline": headline,
        "reason": reason,
        "next_steps": selected_next_steps() if final_candidate else not_selected_next_steps(status),
        "contact": default_contact_cta(),
        "manual_review_required": True,
        "duplicate_limited": duplicate,
    }


def heuristic_report(project: dict[str, Any], answers: list[dict[str, Any]], llm_error: str) -> dict[str, Any]:
    text = " ".join(str(v) for v in project.values() if v)
    text += " " + " ".join(str(item.get("answer", "")) for item in answers if isinstance(item, dict))
    lower = text.lower()

    def has_any(words: list[str]) -> bool:
        return any(word.lower() in lower for word in words)

    scores = {
        "team_background": 5 + (3 if has_any(["团队", "创始人", "经验", "背景"]) else 0),
        "problem_clarity": 5 + (4 if has_any(["痛点", "刚需", "高频", "pain", "urgent"]) else 0),
        "product_readiness": 7 + (5 if has_any(["上线", "demo", "验证", "稳定", "测试", "benchmark"]) else 0),
        "market_potential": 8 + (5 if has_any(["市场", "规模", "人群", "需求", "分发"]) else 0),
        "business_model": 5 + (4 if has_any(["usdt", "usdc", "定价", "订阅", "复购", "毛利"]) else 0),
        "growth_strategy": 5 + (3 if has_any(["分发", "社区", "kol", "增长", "渠道"]) else 0),
        "defensibility": 5 + (3 if has_any(["壁垒", "专有", "数据源", "网络效应"]) else 0),
        "verification_bonus": verification_bonus_from_project(project),
    }
    scores = {key: min(value, max_score) for key, value in scores.items() for max_score in [SCORE_KEYS[key]]}
    total = sum(scores.values())
    recommendation = "watch" if total >= 60 else "pass"
    name = str(project.get("name") or "Unnamed Agent")
    fingerprint = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return {
        "schema_version": "nvc-report-v2",
        "project_name": name,
        "one_line_verdict": _default_verdict(total),
        "recommendation": recommendation,
        "raw_eligible_for_investment": False,
        "total_score": total,
        "scores": scores,
        "score_labels": SCORE_LABELS,
        "score_max": SCORE_KEYS,
        "investment_summary": "当前为本地启发式评估结果，因为未配置 LLM API 或 LLM 调用失败。它适合联调流程，不适合作为最终报告质量验收。",
        "project_understanding": {
            "target_user": str(project.get("target_user", "")),
            "problem": str(project.get("problem", "")),
            "solution": str(project.get("solution", "")),
            "why_now": "需要项目方进一步说明为什么现在是进入 OKX.AI 生态的好时机。",
        },
        "committee_discussion": {
            "product_partner": "产品叙事需要从功能描述升级为明确的付费场景。",
            "growth_partner": "需要说明首批用户从哪里来，以及如何在 Agent 广场内形成可见转化。",
            "technical_partner": "需要证明交付结果可重复、可验证，而不是一次性 prompt 演示。",
            "risk_partner": "当前不建议触发投资候选，原因是证据链和模型评估尚未完整。",
        },
        "strengths": ["项目已提交基本信息，可以进入投资诊断流程。"],
        "risks": ["缺少 LLM 深度评估。", "缺少可验证 traction 或复购证据。"],
        "improvement_plan": {
            "next_48_hours": ["补齐目标用户、付费理由、差异化和交付样例。"],
            "next_7_days": ["收集 3 个真实用户案例，并把报告输出调整成可截图传播的版本。"],
            "proof_needed_for_investment": ["真实调用记录", "用户反馈", "复购或愿付费证据"],
        },
        "suggested_positioning": "把项目包装成具体任务结果，而不是泛泛的聊天 Agent。",
        "pricing_feedback": "先用低门槛单次付费测试转化，再根据复购和结果价值提价。",
        "data_used_as_supporting_evidence": [f"local_fallback_fingerprint:{fingerprint}"],
        "verification_evidence": verification_evidence(project),
        "reapply_conditions": ["补充真实产品链接、用户证据或链上可验证数据后，可再次测评。"],
        "contact_cta": default_contact_cta(),
        "missing_information": ["LLM_API_KEY", f"llm_error:{llm_error}"],
    }


def _default_verdict(total: int) -> str:
    if total >= minimum_score():
        return "项目具备进入投资候选的基础，但仍需要通过硬性名额和人工复核。"
    if total >= 60:
        return "项目有可讨论的早期机会，但现阶段更适合观察和补证据。"
    return "项目当前更像功能演示，尚未形成足够清晰的投资叙事。"


def minimum_score() -> int:
    return int(os.getenv("INVESTMENT_MINIMUM_SCORE", "88"))


def verification_bonus_from_project(project: dict[str, Any]) -> int:
    bonus = 0
    if _looks_like_url(project.get("agent_url")) or _looks_like_url(project.get("product_url")):
        bonus += 6
    if _looks_like_url(project.get("website")) or _looks_like_url(project.get("social")):
        bonus += 3
    if _looks_like_wallet(project.get("wallet_address")):
        bonus += 5
    evidence_text = " ".join(
        str(project.get(key, ""))
        for key in ("traction", "onchain_evidence", "verification", "launched_product")
    ).lower()
    if any(word in evidence_text for word in ("收入", "用户", "销量", "交易", "调用", "tx", "revenue", "users")):
        bonus += 4
    if len(evidence_text) > 160:
        bonus += 2
    return min(bonus, SCORE_KEYS["verification_bonus"])


def verification_evidence(project: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    if project.get("agent_url"):
        evidence.append(f"Agent/产品链接：{project.get('agent_url')}")
    if project.get("product_url"):
        evidence.append(f"产品链接：{project.get('product_url')}")
    if project.get("wallet_address"):
        evidence.append(f"钱包地址：{project.get('wallet_address')}")
    if project.get("website"):
        evidence.append(f"官网：{project.get('website')}")
    if project.get("social"):
        evidence.append(f"社交账号：{project.get('social')}")
    if project.get("onchain_evidence"):
        evidence.append(f"链上/产品证据：{project.get('onchain_evidence')}")
    return evidence


def project_fingerprint(project: dict[str, Any]) -> str:
    fields = [
        "name",
        "agent_url",
        "product_url",
        "website",
        "social",
        "wallet_address",
        "one_liner",
    ]
    raw = " ".join(str(project.get(field, "")) for field in fields)
    normalized = re.sub(r"\s+", " ", raw.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24] if normalized else ""


def submitter_key(project: dict[str, Any]) -> str:
    raw = str(project.get("contact") or project.get("email") or project.get("wallet_address") or "")
    normalized = re.sub(r"\s+", "", raw.lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24] if normalized else ""


def _looks_like_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("http://", "https://")) or "." in text and len(text) > 5


def _looks_like_wallet(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", text) or re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text))


def default_contact_cta() -> str:
    return os.getenv(
        "CONTACT_CTA",
        "请关注并联系推特 @jch47643085 或 TG @maxjiang，并提交项目名、报告编号和钱包地址，完成身份核验后进入后续流程。",
    )


def selected_next_steps() -> list[str]:
    return [
        "保存本报告链接，并记录报告编号。",
        "通过 NVC 官方联系方式提交项目名、报告编号、联系邮箱/Telegram 和收款钱包。",
        "完成团队身份、产品真实性和重复提交核验后，进入 100 USDT 支持发放流程。",
        "入选项目还有机会获得价值最高 500 USDT 的项目推广与创始人个人品牌营销支持。",
    ]


def not_selected_next_steps(status: str) -> list[str]:
    if status == "quota_limited":
        return [
            "本轮名额已满，建议先进入社区观察名单。",
            "补充产品链接、真实用户反馈、收入或链上可验证证据后，在下一轮重新提交。",
        ]
    if status == "duplicate_limited":
        return [
            "同一项目每天最多测评一次，请不要通过改写少量文字重复提交。",
            "如项目发生重大变化，请次日补充新的产品证据后重新测评。",
        ]
    return [
        "优先补齐报告中的关键风险和证明材料。",
        "加入社区获得项目优化建议，满足重新申请条件后再次测评。",
        "如果已上线产品，请补充产品链接、钱包地址、用户案例或链上证据以获得验证加分。",
    ]
