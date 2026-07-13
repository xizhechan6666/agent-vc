#!/usr/bin/env python3
"""Minimal HTTP API for Agent VC.

Run:
    python3 app.py
"""

from __future__ import annotations

import json
import os
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from agent_vc.evaluator import apply_investment_gate, evaluate_project, generate_interview
from agent_vc.prompt import INPUT_SCHEMA, REPORT_SCHEMA_HINT
from agent_vc.store import connect, get_evaluation, save_evaluation


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent VC</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d7dce2;
      --text: #1d2430;
      --muted: #657184;
      --accent: #0f766e;
      --accent-dark: #0b5d56;
      --danger: #a13d2d;
      --shadow: 0 1px 2px rgba(20, 31, 44, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 15px;
      line-height: 1.45;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .topbar {
      max-width: 1180px;
      margin: 0 auto;
      padding: 18px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      white-space: nowrap;
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--accent);
    }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      grid-template-columns: minmax(360px, 0.9fr) minmax(420px, 1.1fr);
      gap: 18px;
      align-items: start;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .section-head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    h2 {
      margin: 0;
      font-size: 16px;
      font-weight: 650;
      letter-spacing: 0;
    }
    form, .output {
      padding: 16px;
    }
    label {
      display: block;
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }
    input, textarea {
      width: 100%;
      margin-top: 6px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      color: var(--text);
      background: #fff;
      font: inherit;
      line-height: 1.4;
    }
    textarea {
      min-height: 76px;
      resize: vertical;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    button {
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 10px 13px;
      min-height: 40px;
      background: var(--accent);
      color: white;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }
    button.secondary {
      background: #fff;
      color: var(--text);
      border-color: var(--line);
    }
    button:hover { background: var(--accent-dark); }
    button.secondary:hover { background: #eef2f5; }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .questions {
      padding: 0 16px 16px;
      display: grid;
      gap: 12px;
    }
    .question-row {
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    .question-row p {
      margin: 0 0 8px;
      font-weight: 650;
    }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #16202c;
      background: #f9fafb;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
    }
    .report-host {
      min-height: 360px;
    }
    .report-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }
    .report-hero {
      padding: 18px;
      border-bottom: 1px solid var(--line);
      background: #f8fbfb;
    }
    .report-hero h3 {
      margin: 0 0 8px;
      font-size: 22px;
      letter-spacing: 0;
    }
    .badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 5px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      font-size: 13px;
      font-weight: 650;
    }
    .report-section {
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }
    .report-section:last-child {
      border-bottom: 0;
    }
    .report-section h4 {
      margin: 0 0 10px;
      font-size: 15px;
    }
    .report-section p {
      margin: 0 0 8px;
    }
    .score-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .score-line {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
    }
    .report-list {
      margin: 0;
      padding-left: 18px;
    }
    .report-link {
      color: var(--accent-dark);
      font-weight: 700;
      text-decoration: none;
    }
    .message {
      color: var(--muted);
      font-size: 13px;
    }
    .error {
      color: var(--danger);
      font-weight: 650;
    }
    @media (max-width: 860px) {
      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }
      main {
        grid-template-columns: 1fr;
        padding: 14px;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <h1>Agent VC</h1>
      <div class="status"><span class="dot"></span><span id="health">checking</span></div>
    </div>
  </header>
  <main>
    <section>
      <div class="section-head">
        <h2>项目资料</h2>
        <span class="message">A2MCP report brain</span>
      </div>
      <form id="projectForm">
        <label>Agent 名称
          <input name="name" value="Demo Alpha Agent" required>
        </label>
        <label>Agent 链接或 ID
          <input name="agent_url" value="https://www.okx.ai/zh-hans/agents/demo">
        </label>
        <label>一句话介绍
          <textarea name="one_liner">帮助 OKX.AI Agent 创业者把产品包装成可成交的付费服务。</textarea>
        </label>
        <label>目标用户
          <textarea name="target_user">已经有 Agent 原型、但不知道如何定价和获得首批用户的 OKX.AI ASP。</textarea>
        </label>
        <label>解决的问题
          <textarea name="problem">很多 Agent 只是功能演示，缺少清晰付费场景、增长路径和投资叙事。</textarea>
        </label>
        <label>解决方案
          <textarea name="solution">通过项目问答、VC rubric 和投资委员会模拟，输出结构化诊断报告。</textarea>
        </label>
        <label>定价
          <input name="pricing" value="10 USDC/次，深度版 30 USDC/次。">
        </label>
        <label>现有数据或证据
          <textarea name="traction">已有 5 个项目方愿意试用，暂无正式收入。</textarea>
        </label>
        <label>差异化
          <textarea name="differentiation">不是通用聊天，而是固定 VC 诊断流程、评分卡、投资候选硬门控和 OKX.AI 生态语境。</textarea>
        </label>
        <label>融资叙事
          <textarea name="founder_pitch">OKX.AI 早期 Agent 数据稀缺，项目方更需要被投资人式追问和优化，而不是钱包流水分析。</textarea>
        </label>
        <label>已知风险
          <textarea name="risks">报告质量依赖 prompt 和模型；投资候选需要严格控制比例。</textarea>
        </label>
        <div class="actions">
          <button type="button" id="interviewBtn">生成追问</button>
          <button type="button" id="evaluateBtn">生成报告</button>
          <button type="button" class="secondary" id="clearBtn">清空回答</button>
        </div>
      </form>
      <div class="questions" id="questions"></div>
    </section>
    <section>
      <div class="section-head">
        <h2>输出</h2>
        <span class="message" id="runState">ready</span>
      </div>
      <div class="output">
        <div id="output" class="report-host">点击“生成追问”或“生成报告”。</div>
      </div>
    </section>
  </main>
  <script>
    const form = document.getElementById('projectForm');
    const output = document.getElementById('output');
    const runState = document.getElementById('runState');
    const questionsEl = document.getElementById('questions');

    function projectFromForm() {
      const data = new FormData(form);
      const project = {};
      for (const [key, value] of data.entries()) {
        if (!key.startsWith('answer_')) project[key] = String(value).trim();
      }
      return project;
    }

    function answersFromForm() {
      return Array.from(document.querySelectorAll('[data-question]')).map((node) => ({
        question: node.getAttribute('data-question'),
        answer: node.value.trim()
      })).filter((item) => item.answer);
    }

    function setBusy(isBusy, label) {
      runState.textContent = label;
      document.getElementById('interviewBtn').disabled = isBusy;
      document.getElementById('evaluateBtn').disabled = isBusy;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char]));
    }

    function listHtml(items) {
      const arr = Array.isArray(items) ? items : [];
      if (!arr.length) return '<p class="message">暂无</p>';
      return `<ul class="report-list">${arr.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
    }

    function paragraph(value) {
      return `<p>${escapeHtml(value || '暂无')}</p>`;
    }

    function renderReport(body) {
      const report = body.report || {};
      const gate = body.investment_gate || {};
      const scores = report.scores || {};
      const discussion = report.committee_discussion || {};
      const plan = report.improvement_plan || {};
      const understanding = report.project_understanding || {};
      const scoreRows = Object.entries(scores).map(([key, value]) => (
        `<div class="score-line"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`
      )).join('');
      return `
        <div class="report-card">
          <div class="report-hero">
            <h3>${escapeHtml(report.project_name || 'Agent VC Report')}</h3>
            ${paragraph(report.one_line_verdict)}
            <div class="badge-row">
              <span class="badge">总分 ${escapeHtml(report.total_score || 0)}</span>
              <span class="badge">结论 ${escapeHtml(report.recommendation || 'watch')}</span>
              <span class="badge">候选 ${escapeHtml(gate.candidate_status || 'not_candidate')}</span>
              <a class="badge report-link" href="${escapeHtml(body.report_url || '#')}" target="_blank" rel="noreferrer">打开 HTML 报告</a>
            </div>
          </div>
          <div class="report-section">
            <h4>投资人摘要</h4>
            ${paragraph(report.investment_summary)}
          </div>
          <div class="report-section">
            <h4>项目理解</h4>
            ${paragraph(`目标用户：${understanding.target_user || '暂无'}`)}
            ${paragraph(`问题：${understanding.problem || '暂无'}`)}
            ${paragraph(`方案：${understanding.solution || '暂无'}`)}
            ${paragraph(`为什么现在：${understanding.why_now || '暂无'}`)}
          </div>
          <div class="report-section">
            <h4>投资委员会讨论</h4>
            ${paragraph(`产品合伙人：${discussion.product_partner || '暂无'}`)}
            ${paragraph(`增长合伙人：${discussion.growth_partner || '暂无'}`)}
            ${paragraph(`技术合伙人：${discussion.technical_partner || '暂无'}`)}
            ${paragraph(`风控合伙人：${discussion.risk_partner || '暂无'}`)}
          </div>
          <div class="report-section">
            <h4>评分卡</h4>
            <div class="score-grid">${scoreRows}</div>
          </div>
          <div class="report-section">
            <h4>亮点</h4>
            ${listHtml(report.strengths)}
          </div>
          <div class="report-section">
            <h4>风险</h4>
            ${listHtml(report.risks)}
          </div>
          <div class="report-section">
            <h4>改进计划</h4>
            <p><strong>48 小时：</strong></p>
            ${listHtml(plan.next_48_hours)}
            <p><strong>7 天：</strong></p>
            ${listHtml(plan.next_7_days)}
            <p><strong>进入投资候选还需要：</strong></p>
            ${listHtml(plan.proof_needed_for_investment)}
          </div>
          <div class="report-section">
            <h4>定位与定价</h4>
            ${paragraph(report.suggested_positioning)}
            ${paragraph(report.pricing_feedback)}
          </div>
        </div>
      `;
    }

    async function postJson(path, payload) {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const text = await response.text();
      let body;
      try { body = JSON.parse(text); } catch { body = { raw: text }; }
      if (!response.ok) {
        const error = new Error(body.message || body.error || response.statusText);
        error.body = body;
        throw error;
      }
      return body;
    }

    function renderQuestions(items) {
      questionsEl.innerHTML = '';
      items.forEach((item, index) => {
        const row = document.createElement('div');
        row.className = 'question-row';
        const q = document.createElement('p');
        q.textContent = `${index + 1}. ${item.question}`;
        const label = document.createElement('label');
        label.textContent = item.why_it_matters || '回答';
        const textarea = document.createElement('textarea');
        textarea.setAttribute('data-question', item.question);
        textarea.name = `answer_${index + 1}`;
        textarea.placeholder = '项目方回答';
        label.appendChild(textarea);
        row.appendChild(q);
        row.appendChild(label);
        questionsEl.appendChild(row);
      });
    }

    document.getElementById('interviewBtn').addEventListener('click', async () => {
      setBusy(true, 'generating questions');
      try {
        const body = await postJson('/interview', { project: projectFromForm() });
        renderQuestions(body.questions || []);
        output.innerHTML = `<pre>${escapeHtml(JSON.stringify(body, null, 2))}</pre>`;
        runState.textContent = 'questions ready';
      } catch (error) {
        output.innerHTML = `<span class="error">${error.message}</span>`;
        runState.textContent = 'error';
      } finally {
        setBusy(false, runState.textContent);
      }
    });

    document.getElementById('evaluateBtn').addEventListener('click', async () => {
      setBusy(true, 'generating report');
      try {
        const body = await postJson('/evaluate', {
          project: projectFromForm(),
          answers: answersFromForm()
        });
        output.innerHTML = renderReport(body);
        runState.textContent = 'report ready';
      } catch (error) {
        output.innerHTML = `<span class="error">${error.message}</span>`;
        runState.textContent = 'error';
      } finally {
        setBusy(false, runState.textContent);
      }
    });

    document.getElementById('clearBtn').addEventListener('click', () => {
      document.querySelectorAll('[data-question]').forEach((node) => { node.value = ''; });
    });

    fetch('/health')
      .then((response) => response.json())
      .then((body) => {
        document.getElementById('health').textContent = body.llm_configured ? 'LLM configured' : 'local fallback';
      })
      .catch(() => {
        document.getElementById('health').textContent = 'offline';
      });
  </script>
</body>
</html>
"""


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, status: int, body: str) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def base_url(handler: BaseHTTPRequestHandler) -> str:
    forwarded_proto = handler.headers.get("X-Forwarded-Proto")
    proto = forwarded_proto or ("https" if os.getenv("PUBLIC_HTTPS", "0") == "1" else "http")
    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base:
        return public_base.rstrip("/")
    render_external_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if render_external_hostname:
        return f"https://{render_external_hostname}".rstrip("/")
    host = handler.headers.get("Host", f"{os.getenv('HOST', '127.0.0.1')}:{os.getenv('PORT', '8787')}")
    return f"{proto}://{host}".rstrip("/")


def openapi_document(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    root = base_url(handler)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Agent VC API",
            "version": "0.1.0",
            "description": "VC-style investment diagnosis for OKX.AI Agent projects.",
        },
        "servers": [{"url": root}],
        "paths": {
            "/evaluate": {
                "post": {
                    "summary": "Generate an Agent VC investment diagnosis report.",
                    "operationId": "evaluateAgentProject",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["project"],
                                    "properties": {
                                        "project": {"type": "object", "additionalProperties": {"type": "string"}},
                                        "answers": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "question": {"type": "string"},
                                                    "answer": {"type": "string"},
                                                },
                                            },
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Structured JSON report plus HTML report URL."},
                        "400": {"description": "Invalid request."},
                        "402": {"description": "Payment required after x402 middleware is enabled."},
                    },
                }
            },
            "/interview": {
                "post": {
                    "summary": "Generate investor questions for an Agent project.",
                    "operationId": "generateInvestorQuestions",
                    "responses": {"200": {"description": "Question list."}},
                }
            },
        },
    }


def a2mcp_document(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    root = base_url(handler)
    return {
        "agent": {
            "name": os.getenv("AGENT_NAME", "Agent VC"),
            "role": "ASP",
            "description": "面向 OKX.AI Agent 创业者的虚拟早期投资委员会，输出投资诊断报告和改进建议。",
        },
        "service": {
            "serviceName": os.getenv("SERVICE_NAME", "Agent VC Investment Diagnosis"),
            "serviceDescription": (
                "① 对 OKX.AI Agent 项目进行 VC 式追问、评分和投资委员会诊断，输出 HTML/JSON 报告。\n"
                "② 用户需提供 Agent 名称、链接或 ID、目标用户、问题、方案、定价、traction、差异化和融资叙事。"
            ),
            "serviceType": "A2MCP",
            "fee": os.getenv("SERVICE_FEE_USDT", "10"),
            "endpoint": f"{root}/evaluate",
        },
        "supportingEndpoints": {
            "webDemo": f"{root}/",
            "health": f"{root}/health",
            "openapi": f"{root}/openapi.json",
            "schema": f"{root}/schema",
        },
        "status": {
            "paymentGate": os.getenv("X402_ENABLED", "0") == "1",
            "llmConfigured": bool(os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")),
        },
    }


def h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def items_html(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="muted">暂无</p>'
    return "<ul>" + "".join(f"<li>{h(item)}</li>" for item in items) + "</ul>"


def report_page(evaluation: dict[str, Any]) -> str:
    report = evaluation["report"]
    scores = report.get("scores", {})
    discussion = report.get("committee_discussion", {})
    understanding = report.get("project_understanding", {})
    plan = report.get("improvement_plan", {})
    score_rows = "".join(
        f"<div class='score'><span>{h(key)}</span><strong>{h(value)}</strong></div>"
        for key, value in scores.items()
    )
    candidate = "进入候选" if evaluation["final_candidate"] else "未进入候选"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(report.get("project_name", "Agent VC Report"))} - Agent VC Report</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1d2430; background: #f6f7f9; line-height: 1.55; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 28px 18px 48px; }}
    .paper {{ background: #fff; border: 1px solid #d7dce2; border-radius: 8px; overflow: hidden; }}
    .hero {{ padding: 28px; background: #f8fbfb; border-bottom: 1px solid #d7dce2; }}
    h1 {{ margin: 0 0 10px; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    p {{ margin: 0 0 10px; }}
    section {{ padding: 22px 28px; border-bottom: 1px solid #d7dce2; }}
    section:last-child {{ border-bottom: 0; }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
    .badge {{ border: 1px solid #d7dce2; border-radius: 999px; padding: 6px 10px; background: #fff; font-weight: 650; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .score {{ display: flex; justify-content: space-between; gap: 12px; border: 1px solid #d7dce2; border-radius: 6px; padding: 9px 11px; background: #fbfcfd; }}
    .muted {{ color: #657184; }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin: 5px 0; }}
    @media print {{ body {{ background: #fff; }} main {{ padding: 0; }} .paper {{ border: 0; }} }}
    @media (max-width: 680px) {{ .grid {{ grid-template-columns: 1fr; }} h1 {{ font-size: 24px; }} section, .hero {{ padding: 18px; }} }}
  </style>
</head>
<body>
  <main>
    <article class="paper">
      <div class="hero">
        <h1>{h(report.get("project_name", "Agent VC Report"))}</h1>
        <p>{h(report.get("one_line_verdict", ""))}</p>
        <div class="badges">
          <span class="badge">总分 {h(report.get("total_score", 0))}</span>
          <span class="badge">结论 {h(report.get("recommendation", "watch"))}</span>
          <span class="badge">{h(candidate)}</span>
          <span class="badge">报告 #{h(evaluation["id"])}</span>
        </div>
      </div>
      <section>
        <h2>投资人摘要</h2>
        <p>{h(report.get("investment_summary", ""))}</p>
      </section>
      <section>
        <h2>项目理解</h2>
        <p><strong>目标用户：</strong>{h(understanding.get("target_user", ""))}</p>
        <p><strong>问题：</strong>{h(understanding.get("problem", ""))}</p>
        <p><strong>方案：</strong>{h(understanding.get("solution", ""))}</p>
        <p><strong>为什么现在：</strong>{h(understanding.get("why_now", ""))}</p>
      </section>
      <section>
        <h2>投资委员会讨论</h2>
        <p><strong>产品合伙人：</strong>{h(discussion.get("product_partner", ""))}</p>
        <p><strong>增长合伙人：</strong>{h(discussion.get("growth_partner", ""))}</p>
        <p><strong>技术合伙人：</strong>{h(discussion.get("technical_partner", ""))}</p>
        <p><strong>风控合伙人：</strong>{h(discussion.get("risk_partner", ""))}</p>
      </section>
      <section>
        <h2>评分卡</h2>
        <div class="grid">{score_rows}</div>
      </section>
      <section>
        <h2>亮点</h2>
        {items_html(report.get("strengths"))}
      </section>
      <section>
        <h2>风险</h2>
        {items_html(report.get("risks"))}
      </section>
      <section>
        <h2>改进计划</h2>
        <p><strong>48 小时</strong></p>
        {items_html(plan.get("next_48_hours"))}
        <p><strong>7 天</strong></p>
        {items_html(plan.get("next_7_days"))}
        <p><strong>进入投资候选还需要</strong></p>
        {items_html(plan.get("proof_needed_for_investment"))}
      </section>
      <section>
        <h2>定位与定价</h2>
        <p>{h(report.get("suggested_positioning", ""))}</p>
        <p>{h(report.get("pricing_feedback", ""))}</p>
      </section>
    </article>
  </main>
</body>
</html>"""


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


class AgentVCHandler(BaseHTTPRequestHandler):
    server_version = "AgentVC/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("ACCESS_LOG", "1") == "1":
            super().log_message(fmt, *args)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            html_response(self, 200, INDEX_HTML)
            return
        if path == "/openapi.json":
            json_response(self, 200, openapi_document(self))
            return
        if path == "/a2mcp.json":
            json_response(self, 200, a2mcp_document(self))
            return
        if path.startswith("/reports/"):
            report_id_text = path.removeprefix("/reports/").strip("/")
            try:
                report_id = int(report_id_text)
            except ValueError:
                html_response(self, 404, "<h1>Report not found</h1>")
                return
            with connect() as conn:
                evaluation = get_evaluation(conn, report_id)
            if evaluation is None:
                html_response(self, 404, "<h1>Report not found</h1>")
                return
            html_response(self, 200, report_page(evaluation))
            return
        if path == "/health":
            json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "agent-vc",
                    "version": "0.1.0",
                    "llm_configured": bool(
                        os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
                    ),
                },
            )
            return
        if path == "/schema":
            json_response(
                self,
                200,
                {
                    "input": INPUT_SCHEMA,
                    "output": REPORT_SCHEMA_HINT,
                    "endpoints": {
                        "POST /interview": "Generate VC questions from project input.",
                        "POST /evaluate": "Return VC report JSON and apply hard investment quota gate.",
                    },
                },
            )
            return
        json_response(self, 404, {"error": "not_found"})

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/health"}:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = read_json(self)
        except (json.JSONDecodeError, ValueError) as exc:
            json_response(self, 400, {"error": "invalid_json", "message": str(exc)})
            return

        if path == "/interview":
            project = payload.get("project", payload)
            if not isinstance(project, dict):
                json_response(self, 400, {"error": "invalid_project"})
                return
            questions = generate_interview(project)
            json_response(self, 200, questions)
            return

        if path == "/evaluate":
            project = payload.get("project")
            answers = payload.get("answers", [])
            if not isinstance(project, dict):
                json_response(self, 400, {"error": "invalid_project", "message": "Expected object field: project"})
                return
            if not isinstance(answers, list):
                json_response(self, 400, {"error": "invalid_answers", "message": "Expected array field: answers"})
                return

            report = evaluate_project(project, answers)
            with connect() as conn:
                gate = apply_investment_gate(report, conn)
                request_id = save_evaluation(
                    conn,
                    project_name=str(report.get("project_name") or project.get("name") or "Unnamed Agent"),
                    report=report,
                    gate=gate,
                )
            json_response(
                self,
                200,
                {
                    "request_id": request_id,
                    "report_url": f"/reports/{request_id}",
                    "investment_gate": gate,
                    "report": report,
                },
            )
            return

        json_response(self, 404, {"error": "not_found"})


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8787"))
    server = ThreadingHTTPServer((host, port), AgentVCHandler)
    print(f"Agent VC API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
