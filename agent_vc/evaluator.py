"""Evaluation and report generation."""

from __future__ import annotations

import hashlib
from typing import Any

from . import llm
from .prompt import INTERVIEW_PROMPT, REPORT_SCHEMA_HINT, SYSTEM_PROMPT
from .store import quota_preview


SCORE_KEYS = {
    "demand_strength": 20,
    "differentiation": 15,
    "delivery_reliability": 15,
    "business_model": 15,
    "growth_potential": 10,
    "defensibility": 10,
    "traction_quality": 10,
    "founder_clarity": 5,
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

    total = sum(normalized_scores.values())
    recommendation = str(report.get("recommendation", "watch"))
    if recommendation not in {"invest_candidate", "watch", "pass"}:
        recommendation = "invest_candidate" if total >= 85 else "watch" if total >= 60 else "pass"

    report["schema_version"] = "agent-vc-report-v1"
    report["project_name"] = str(report.get("project_name") or project.get("name") or "Unnamed Agent")
    report["scores"] = normalized_scores
    report["total_score"] = total
    report["recommendation"] = recommendation
    report["raw_eligible_for_investment"] = bool(
        report.get("raw_eligible_for_investment") and total >= 85 and recommendation == "invest_candidate"
    )
    report.setdefault("one_line_verdict", _default_verdict(total))
    report.setdefault("missing_information", [])
    report.setdefault("data_used_as_supporting_evidence", [])
    return report


def apply_investment_gate(report: dict[str, Any], conn: Any) -> dict[str, Any]:
    quota = quota_preview(conn)
    score = int(report.get("total_score", 0))
    raw_eligible = bool(report.get("raw_eligible_for_investment"))
    final_candidate = raw_eligible and score >= 85 and quota["slots_remaining"] > 0

    if final_candidate:
        status = "candidate"
        reason = "通过模型原始建议、最低分阈值和本轮投资候选名额限制；仍需人工复核后才可发放。"
    elif not raw_eligible:
        status = "not_candidate"
        reason = "报告建议暂不进入投资候选；可以按改进计划补充证据后重新提交。"
    elif score < 85:
        status = "not_candidate"
        reason = "总分未达到 85 分硬阈值。"
    else:
        status = "quota_limited"
        reason = "本轮投资候选名额已用完；报告可标记为强观察，但不触发候选资格。"

    return {
        **quota,
        "minimum_score": 85,
        "final_candidate": final_candidate,
        "candidate_status": status,
        "reason": reason,
    }


def heuristic_report(project: dict[str, Any], answers: list[dict[str, Any]], llm_error: str) -> dict[str, Any]:
    text = " ".join(str(v) for v in project.values() if v)
    text += " " + " ".join(str(item.get("answer", "")) for item in answers if isinstance(item, dict))
    lower = text.lower()

    def has_any(words: list[str]) -> bool:
        return any(word.lower() in lower for word in words)

    scores = {
        "demand_strength": 12 + (5 if has_any(["付费", "刚需", "高频", "pain", "urgent"]) else 0),
        "differentiation": 8 + (5 if has_any(["独家", "数据", "workflow", "专业", "壁垒"]) else 0),
        "delivery_reliability": 8 + (4 if has_any(["验证", "稳定", "准确", "测试", "benchmark"]) else 0),
        "business_model": 8 + (5 if has_any(["usdt", "usdc", "定价", "订阅", "复购", "毛利"]) else 0),
        "growth_potential": 6 + (3 if has_any(["分发", "社区", "kol", "增长", "渠道"]) else 0),
        "defensibility": 5 + (3 if has_any(["壁垒", "专有", "数据源", "网络效应"]) else 0),
        "traction_quality": 4 + (4 if has_any(["销量", "好评", "用户", "收入", "案例"]) else 0),
        "founder_clarity": 3 + (2 if len(text) > 500 else 0),
    }
    scores = {key: min(value, max_score) for key, value in scores.items() for max_score in [SCORE_KEYS[key]]}
    total = sum(scores.values())
    recommendation = "watch" if total >= 60 else "pass"
    name = str(project.get("name") or "Unnamed Agent")
    fingerprint = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return {
        "schema_version": "agent-vc-report-v1",
        "project_name": name,
        "one_line_verdict": _default_verdict(total),
        "recommendation": recommendation,
        "raw_eligible_for_investment": False,
        "total_score": total,
        "scores": scores,
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
        "missing_information": ["LLM_API_KEY", f"llm_error:{llm_error}"],
    }


def _default_verdict(total: int) -> str:
    if total >= 85:
        return "项目具备进入投资候选的基础，但仍需要通过硬性名额和人工复核。"
    if total >= 60:
        return "项目有可讨论的早期机会，但现阶段更适合观察和补证据。"
    return "项目当前更像功能演示，尚未形成足够清晰的投资叙事。"
