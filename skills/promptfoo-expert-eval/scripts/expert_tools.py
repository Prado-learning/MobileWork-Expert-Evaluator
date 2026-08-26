"""expert_tools.py — promptfoo-expert-eval 的 AI 工具集（跨平台单一来源）。

被以下场景调用：
- MobileEval web：后端动作端点通过 subprocess 调用本脚本并落库
- OpenWork / Claude Code：AI 读 SKILL.md 后执行本脚本（生成 + 直接写库）

子命令：
  context          导出被测专家（团）上下文摘要（供其它工具/可视化消费）
  analyze-expert   分析专家包 → 生成评测任务配置 JSON（场景/自主度/提示词/断言/业务指标）
                   带 --object-id 时直接写入 tasks 表
  generate-cases   基于专家定义 + 任务 → 生成评测 case 数组；带 --object-id 时直接写入 cases 表
  review-cases     批量审核用例（approve/reject，all/selected）
  list-cases       列出某对象下用例（含状态，供审核决策）
  list-tasks       列出某对象下评测任务
  suggest          解读评测结果（summary.json，可附人工评审）→ 生成结构化优化建议；带 --run-id 时写库

凭据：优先 ANTHROPIC_API_KEY（可配 ANTHROPIC_BASE_URL）；否则回退 DEEPSEEK_API_KEY
（DeepSeek 提供 Anthropic 兼容端点）。Windows 上支持读用户级注册表环境变量。
"""
import argparse
import json
import os
import shutil
import sys

from db import get_db, init_db, jdumps, jloads, resolve_db, resolve_project_home

# --------------------------------------------------------------------------- #
# 凭据 / LLM 客户端
# --------------------------------------------------------------------------- #


def _registry_env(name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except Exception:  # noqa: BLE001
        return None


def resolve_credentials():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or _registry_env("ANTHROPIC_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or _registry_env("DEEPSEEK_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if anthropic_key:
        return {"api_key": anthropic_key, "base_url": base_url,
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")}
    if deepseek_key:
        return {"api_key": deepseek_key, "base_url": "https://api.deepseek.com/anthropic",
                "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-chat")}
    return None


def _client():
    creds = resolve_credentials()
    if not creds:
        raise RuntimeError("未配置 AI 凭据：请设置 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY")
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("未安装 anthropic SDK：pip install anthropic")
    kwargs = {"api_key": creds["api_key"]}
    if creds.get("base_url"):
        kwargs["base_url"] = creds["base_url"]
    return anthropic.Anthropic(**kwargs), creds["model"]


SYSTEM_PROMPT = """你是 MobileEval 评测中心的 AI 评测方案设计师，面向无开发经验的业务用户。
你负责：分析被测专家（团）定义、设计评测配置（场景/自主度/提示词/断言/业务指标）、
生成评测 case、解读评测结果并给出可执行的优化建议。
原则：先分析被测对象（团长与团员的角色/权限/委派/工作流）再设计；用简洁中文；
区分"技术性能指标"与"用户可感知体验"；优化建议必须基于评测证据。"""


def _call(messages, max_tokens=2500, system=None):
    client, model = _client()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        system=system or SYSTEM_PROMPT, messages=messages)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _parse_json(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        s, e = text.find("{"), text.rfind("}")
        if 0 <= s < e:
            try:
                return json.loads(text[s:e + 1])
            except ValueError:
                pass
        s, e = text.find("["), text.rfind("]")
        if 0 <= s < e:
            try:
                return json.loads(text[s:e + 1])
            except ValueError:
                pass
    return None


# --------------------------------------------------------------------------- #
# 专家上下文加载（从 .opencode 读取被测对象定义）
# --------------------------------------------------------------------------- #


def _read_jsonc(path):
    if not os.path.exists(path):
        return {}
    lines = [ln for ln in open(path, encoding="utf-8").read().splitlines()
             if not ln.lstrip().startswith(("//", "/*"))]
    try:
        return json.loads("\n".join(lines))
    except ValueError:
        return {}


def _yaml_frontmatter(fm_text):
    out = {}
    for ln in fm_text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", "-", "'")):
            continue
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def _agent_md(agents_dir, agent_id):
    path = os.path.join(agents_dir, f"{agent_id}.md")
    if not os.path.exists(path):
        return {}, ""
    raw = open(path, encoding="utf-8").read()
    parts = raw.split("---", 2)
    fm, body = {}, raw
    if len(parts) >= 3:
        try:
            fm = json.loads(parts[1]) if parts[1].lstrip().startswith("{") else _yaml_frontmatter(parts[1])
        except Exception:  # noqa: BLE001
            fm = {}
        body = parts[2]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    return fm, " ".join(lines)[:400]


def load_expert_context(workspace_dir, agent_name=None):
    agent_name = agent_name or "software-team-lead"
    oc_dir = os.path.join(workspace_dir, ".opencode") if workspace_dir else None
    if not oc_dir or not os.path.isdir(oc_dir):
        return {"agent_name": agent_name, "workspace_dir": workspace_dir or "",
                "summary": "（未找到 .opencode 配置，无法读取专家定义）", "agents": []}
    cfg = _read_jsonc(os.path.join(oc_dir, "opencode.jsonc"))
    agents = []
    for aid, a in (cfg.get("agent") or {}).items():
        perm = a.get("permission") or {}
        task_allow = []
        tv = perm.get("task")
        if isinstance(tv, dict):
            task_allow = [k for k, v in tv.items() if v == "allow"]
        agents.append({"id": aid, "description": (a.get("description") or "")[:200],
                       "mode": a.get("mode", ""), "steps": a.get("steps"),
                       "task_allow": task_allow,
                       "bash": "ask" if isinstance(perm.get("bash"), dict) and perm["bash"].get("*") == "ask"
                               else ("allow" if isinstance(perm.get("bash"), dict) else perm.get("bash")),
                       "edit": perm.get("edit"), "webfetch": perm.get("webfetch")})
    agents_dir = os.path.join(oc_dir, "agents")
    for ag in agents:
        fm, body = _agent_md(agents_dir, ag["id"]) if os.path.isdir(agents_dir) else ({}, "")
        if fm or body:
            ag["md_role"] = (fm.get("profession") or fm.get("description") or "")[:200]
            ag["md_workflow"] = body[:300]
    lead = next((a for a in agents if a["id"] == agent_name), agents[0] if agents else None)
    parts = [f"被测对象：{agent_name}（工作区 {workspace_dir}）"]
    if lead:
        parts.append(f"团长：{lead['id']} · {lead.get('md_role') or lead.get('description') or ''} · "
                     f"steps={lead.get('steps')} · 可委派: {','.join(lead.get('task_allow') or []) or '无'}")
    for m in [a for a in agents if a["id"] != agent_name]:
        parts.append(f"  - 团员 {m['id']} · {m.get('md_role') or m.get('description') or ''} · steps={m.get('steps')}")
    return {"agent_name": agent_name, "workspace_dir": workspace_dir,
            "agents": agents, "summary": "\n".join(parts)}


# --------------------------------------------------------------------------- #
# 三个工具
# --------------------------------------------------------------------------- #

def analyze_expert(workspace_dir, agent_name, name="", description=""):
    ctx = load_expert_context(workspace_dir, agent_name)
    prompt = (
        "你是评测方案设计师。请根据【被测专家（团）定义】与【任务名称/描述】设计一份完整的专家评测配置。\n"
        "被测专家（团）定义是主要依据（决定场景类型/自主度/提示词/断言/业务指标如何匹配其实际能力），"
        "任务描述仅作辅助参考。\n\n"
        f"【被测专家（团）定义】\n{ctx['summary']}\n\n"
        f"【任务名称】{name}\n【任务描述】{description}\n\n"
        "只输出一个 JSON 对象（不要代码块标记、不要解释），格式：\n"
        '{"scenario_type": "structured|hybrid|open_ended", '
        '"autonomy_level": "low|high", '
        '"prompt_template": "发给被测专家/专家团的固定提示词（支持 {output_dir} 占位，指明产物目录与最终输出要求）", '
        '"assertions": [{"type": "contains|regex|javascript", "value": "..."}], '
        '"human_metrics": [{"name": "业务指标名", "criteria": "1-5分", "weight": 0.6}], '
        '"analysis": "设计说明：面向无开发经验用户解释为什么这样配置，说明如何匹配该专家（团）的角色/技能/权限/工作流"}\n'
        "规则：\n"
        "1. 先分析被测对象：团长与团员的角色、可委派关系、权限（bash/edit/webfetch）、steps 与工作流；\n"
        "2. 精确度要求高、自主度要求低的任务 → structured + low + 确定性断言；"
        "只给目标与验收标准的开放任务 → open_ended + high，assertions 可留空；"
        "兼顾硬约束与专业判断 → hybrid；\n"
        "3. 提示词要与该专家团的编排方式匹配：涉及团长的 case 提示词应要求委派对应团员"
        "（如 PRD→产品经理、实现→工程师、测试→QA），并让团长验收汇总；\n"
        "4. assertions 用 promptfoo 语法：contains/regex 作用于最终输出文本；"
        "javascript 可用 import('node:fs') 验证产物文件（value 支持 {output_dir_abs} 占位）；\n"
        "5. human_metrics 是业务/用户可感知指标（如交付可用性、说明清晰度），2-4 个，权重和约等于 1；\n"
        "6. prompt_template 要具体可执行，包含产物输出目录与最终回复要求。"
    )
    raw = _call([{"role": "user", "content": prompt}], max_tokens=2500)
    data = _parse_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"AI 未返回合法 JSON：{str(raw)[:200]}")
    return _validate_task_config(data)


def _validate_task_config(data):
    scenario = data.get("scenario_type")
    if scenario not in ("structured", "hybrid", "open_ended"):
        scenario = "hybrid"
    autonomy = data.get("autonomy_level")
    if autonomy not in ("low", "high"):
        autonomy = "low"
    assertions = data.get("assertions") or []
    if not isinstance(assertions, list):
        assertions = []
    allowed = ("contains", "regex", "javascript", "python")
    assertions = [a for a in assertions if isinstance(a, dict)
                  and a.get("type") in allowed and a.get("value")]
    metrics = data.get("human_metrics") or []
    if not isinstance(metrics, list):
        metrics = []
    metrics = [{"name": str(m.get("name", "指标")), "criteria": str(m.get("criteria", "1-5分")),
                "weight": float(m.get("weight") or 0.5)} for m in metrics if isinstance(m, dict)][:5]
    if not metrics:
        metrics = [{"name": "交付质量", "criteria": "1-5分", "weight": 0.6},
                   {"name": "说明清晰度", "criteria": "1-5分", "weight": 0.4}]
    return {"scenario_type": scenario, "autonomy_level": autonomy,
            "prompt_template": str(data.get("prompt_template") or "").strip(),
            "assertions": assertions, "human_metrics": metrics,
            "analysis": str(data.get("analysis") or "").strip()}


def generate_case_plan(workspace_dir, agent_name, task, count=6):
    """生成评测 case 概要（供用户确认，不写库）。

    返回 plan 列表：[{"title", "type", "target", "verify"}, ...]
    """
    count = max(1, min(count, 12))
    ctx = load_expert_context(workspace_dir, agent_name)
    task_name = task.get("name", "")
    task_desc = task.get("description", "")
    prompt = (
        "你是评测方案设计师。请基于【被测专家（团）定义】与【任务信息】，先输出评测 case 概要"
        "（这一步只做方案设计，供用户确认，不要展开完整 case）。\n\n"
        f"【被测专家（团）定义】\n{ctx['summary']}\n\n"
        f"【任务名称】{task_name}\n【任务描述】{task_desc}\n\n"
        f"设计 {count} 个评测 case 的概要，覆盖：结构化（精确产出+确定性断言）、混合式（硬约束+专业判断）、"
        "开放式（高自主，只给目标与验收标准）三类（若任务性质明确可侧重某类）。\n"
        "整体输出 JSON 数组（不要代码块标记），格式：\n"
        '[{"title": "case 标题", "type": "structured|hybrid|open_ended", '
        '"target": "评测目标（一句话）", "verify": "验证点（2-3 个要点，分号分隔）"}]\n'
        "规则：case 之间要有区分度（不同侧重），避免重复；单 case 须能在 5 分钟内完成，"
        "聚焦 1 个明确功能/Bug/文档，委派不超过 2 个团员。"
    )
    raw = _call([{"role": "user", "content": prompt}], max_tokens=4000)
    data = _parse_json(raw)
    if isinstance(data, dict) and "title" in data:
        data = [data]
    if not isinstance(data, list):
        raise RuntimeError(f"AI 未返回 case 概要：{str(raw)[:200]}")
    plan = []
    for i, c in enumerate(data[:count]):
        if not isinstance(c, dict) or not c.get("title"):
            continue
        ctype = c.get("type") if c.get("type") in ("structured", "hybrid", "open_ended") else "hybrid"
        plan.append({"seq": i + 1, "title": str(c.get("title")),
                     "type": ctype, "target": str(c.get("target") or ""),
                     "verify": str(c.get("verify") or "")})
    if not plan:
        raise RuntimeError("AI 未返回有效 case 概要，请重试")
    return plan


def generate_cases(workspace_dir, agent_name, task, count=6, plan=None):
    count = max(1, min(count, 12))
    ctx = load_expert_context(workspace_dir, agent_name)
    batches = (count + 5) // 6
    all_cases = []
    for b in range(batches):
        n = min(6, count - b * 6)
        all_cases.extend(_case_batch(ctx, task, n, prefix=f"b{b + 1}-" if batches > 1 else "",
                                     plan=plan))
    return all_cases


def _case_batch(ctx, task, count, prefix="", plan=None):
    task_name = task.get("name", "")
    task_desc = task.get("description", "")
    plan_block = ""
    if plan:
        lines = []
        for p in plan:
            lines.append(
                f"- case{p.get('seq', '')}：标题「{p.get('title')}」[{p.get('type')}]；"
                f"目标：{p.get('target')}；验证点：{p.get('verify')}")
        plan_block = (
            f"\n\n【用户已确认的 case 概要（必须严格按此展开，一个概要对应一个 case，标题/类型沿用）】\n"
            + "\n".join(lines))
    prompt = (
        "你是评测方案设计师。请基于【被测专家（团）定义】与【任务信息】，为该专家系统自动生成一组评测 case。\n\n"
        f"【被测专家（团）定义】\n{ctx['summary']}\n\n"
        f"【任务名称】{task_name}\n【任务描述】{task_desc}\n\n"
        f"{plan_block}\n\n"
        f"要求生成 {count} 个 case，覆盖：结构化（精确产出+确定性断言）、混合式（硬约束+专业判断）、"
        "开放式（高自主，只给目标与验收标准）三类（若任务性质明确可侧重某类）。\n"
        "每个 case 是一个对象，整体输出 JSON 数组（不要代码块标记），格式：\n"
        '[{"case_id": "c1", "title": "case 标题", "type": "structured|hybrid|open_ended", '
        '"dimension": "tool_accuracy|kb_match|collaboration|output_quality", '
        '"prompt": "发给被测专家/专家团的完整任务文本（支持 {output_dir} 占位，指明产物目录；'
        '涉及团长的 case 应要求委派对应团员并由团长验收汇总；不要询问用户）", '
        '"output_dir": "eval-runs/{run_id}/c1", '
        '"assertions": [{"type": "contains|regex|javascript|tool-call|delegation|kb-hit", "value": "..."}]}]\n'
        "规则：\n"
        "1. 每个 case 的 prompt 要匹配该专家团的编排方式（委派对应团员、团长验收）；\n"
        "2. 结构化 case 必须给确定性断言；开放式 case 的 assertions 可留空（靠人工评审）；\n"
        "3. assertions 用 promptfoo 语法：contains/regex 作用于最终输出文本（regex 严禁 (?i) 前缀）；\n"
        "   javascript 断言禁止 require，必须用固定模板：\n"
        "   const fsp = import('node:fs');\n"
        "   return fsp.then(m => { const fs = m.default; /* 检查产物 */ return true; });\n"
        "   {output_dir_abs} 是已编码的产物目录路径字符串，直接使用、不要加引号；\n"
        "4. case 之间要有区分度（不同侧重），避免重复；\n"
        "5. output_dir 使用 eval-runs/{run_id}/<case_id> 占位格式；\n"
        "6. 严禁在 prompt 中写入任何具体文件路径/绝对路径，产物位置一律用 {output_dir} 占位；\n"
        "7. 任务规模可控：单 case 的 agent 运行须能在 5 分钟内完成（opencode 运行窗口限制），\n"
        "   聚焦 1 个明确功能/Bug/文档，委派不超过 2 个团员，避免完整多阶段流程。\n"
        "8. dimension 标记该 case 观测的模块维度；模块级断言（观测过程而非最终输出）：\n"
        "   tool-call=断言某工具被调用（value=工具名，或 {\"tool\":\"名\",\"status\":\"completed\"}）；\n"
        "   delegation=断言团长委派给某团员（value=团员 agent 名，仅 team 有效）；\n"
        "   kb-hit=断言检索命中某关键词（value=关键词）。涉及协同/委派的 case 应给 delegation 断言。\n"
        "9. 业务视角断言（用户可感知体验，区别于技术断言）：llm-rubric=用 LLM 裁判对最终输出\n"
        "   按标准打分，格式 {\"type\":\"llm-rubric\",\"metric\":\"可用性|相关性|完整性|可交付\",\"value\":\"评分标准描述\"}；\n"
        "   open_ended/hybrid case 应给 1-2 条 llm-rubric 业务断言，覆盖可用性与可交付性。\n"
        "10. 评测方向覆盖（按任务性质至少覆盖其一）：\n"
        "    - 多模态解析：要求专家团解析表格/文档/数据（markdown 表格、CSV、JSON 等）并准确问答，断言解析结果正确；\n"
        "    - 技能生成：要求专家团根据业务知识用自然语言生成一个可运行技能/工作流（输出技能定义文档），\n"
        "      断言产物结构合规、可解析、含触发条件与执行步骤（验证\"业务人员自然语言转技能\"可行性）。\n"
        "11. 【交付文件名机制·最重要】每个 case 的 prompt 必须明确列出\"交付文件清单\"——\n"
        "    在【交付要求】中用 `{output_dir}/<确切文件名>` 指明每个产物文件（如 `{output_dir}/BUGFIX-REPORT.md`、\n"
        "    `{output_dir}/FIX-DIFF.md`、`{output_dir}/TEST-OUTPUT.txt`），文件名用大写、含义明确的固定名；\n"
        "    javascript 断言只检查这些 prompt 中已声明的确切文件名，禁止凭空猜测文件名；\n"
        "    断言写法：fs.existsSync(dir + '/BUGFIX-REPORT.md')（dir 来自 {output_dir_abs}）。"
    )
    raw = _call([{"role": "user", "content": prompt}], max_tokens=8000)
    data = _parse_json(raw)
    if isinstance(data, dict) and "case_id" in data:
        data = [data]
    if not isinstance(data, list):
        raise RuntimeError(f"AI 未返回 case 数组：{str(raw)[:200]}")
    cases = []
    for i, c in enumerate(data[:count]):
        if not isinstance(c, dict) or not c.get("prompt"):
            continue
        cid = prefix + str(c.get("case_id") or f"c{i + 1}")
        assertions = c.get("assertions") or []
        if not isinstance(assertions, list):
            assertions = []
        allowed = ("contains", "regex", "javascript", "python",
                   "tool-call", "delegation", "kb-hit", "llm-rubric")
        assertions = [a for a in assertions if isinstance(a, dict)
                      and a.get("type") in allowed and a.get("value")]
        ctype = c.get("type") if c.get("type") in ("structured", "hybrid", "open_ended") else "hybrid"
        dim = c.get("dimension") if c.get("dimension") in (
            "tool_accuracy", "kb_match", "collaboration", "output_quality") else ""
        cases.append({"case_id": cid, "title": str(c.get("title") or f"case {cid}"),
                      "type": ctype, "dimension": str(dim or ""),
                      "prompt": str(c.get("prompt") or "").strip(),
                      "output_dir": str(c.get("output_dir") or f"eval-runs/{{run_id}}/{cid}"),
                      "assertions": assertions})
    if not cases:
        raise RuntimeError("AI 生成的 case 均为空，请重试")
    return cases


def suggest(summary, review=None, run_meta=None):
    """解读评测结果（summary.json），可附人工评审，生成结构化优化建议文本。"""
    cases = summary.get("cases", []) if isinstance(summary, dict) else []
    stats = summary.get("stats", {}) if isinstance(summary, dict) else {}
    case_lines = []
    for c in cases:
        fails = [a for a in (c.get("assertions") or []) if not a.get("pass")]
        fail_desc = "; ".join(f"{a.get('type')}: {str(a.get('reason'))[:80]}" for a in fails[:3])
        case_lines.append(
            f"- case {c.get('id')} [{c.get('type')}] {'PASS' if c.get('pass') else 'FAIL'} "
            f"score={c.get('score')} output_len={c.get('output_length')}"
            + (f" 失败断言: {fail_desc}" if fail_desc else ""))
    meta = run_meta or {}
    review_text = ""
    if review:
        review_text = (f"\n人工评审（rating={review.get('rating')}）：{review.get('comments')}"
                       f" 指标: {json.dumps(review.get('metrics') or [], ensure_ascii=False)}")
        case_reviews = review.get("case_reviews") or []
        if case_reviews:
            lines = [f"- case {cr.get('case_id')}: verdict={cr.get('verdict')} 备注={cr.get('comments')}"
                     for cr in case_reviews if cr.get('case_id')]
            review_text += "\n逐 case 人工纠错：\n" + "\n".join(lines)
    prompt = (
        "请基于以下评测结果生成结构化的专家（团）优化建议，要求：\n"
        "1. 先总结评测结论（1-2 句）\n"
        "2. 按优先级列出 3-5 条可执行优化建议，每条注明依据的证据（case/断言/评审）\n"
        "3. 区分：专家自身问题 / 评测配置问题 / 环境波动\n"
        "4. 针对专家团关注委派与协同\n\n"
        f"【评测对象】{meta.get('object', '?')}\n"
        f"【状态】{meta.get('status', '?')} score={meta.get('score', '?')} "
        f"pass/fail/error={meta.get('pass_fail_error', '?')}\n"
        f"【case 结果】\n" + ("\n".join(case_lines) if case_lines else "（无）") +
        review_text
    )
    return _call([{"role": "user", "content": prompt}], max_tokens=2000)


# --------------------------------------------------------------------------- #
# 数据落库（OpenWork/Claude Code 调用时直接写 MobileEval SQLite）
# --------------------------------------------------------------------------- #

def _latest_task(conn, object_id):
    row = conn.execute(
        "SELECT * FROM tasks WHERE object_id=? ORDER BY id DESC LIMIT 1",
        (object_id,)).fetchone()
    return dict(row) if row else None


def save_task(object_id, name, description, config, db_path=None):
    """analyze-expert 产物落库（去 task 层后：不再建评测任务，仅把业务指标写入对象）。

    返回 {object_id}；兼容旧调用。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        obj = conn.execute("SELECT id FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            raise RuntimeError(f"对象 {object_id} 不存在（objects 表）")
        metrics = config.get("human_metrics") or []
        if metrics:
            conn.execute("UPDATE objects SET human_metrics=? WHERE id=?",
                         (jdumps(metrics), object_id))
            conn.commit()
        return object_id
    finally:
        conn.close()


def save_cases(object_id, cases, db_path=None, task_id=None, mode="replace"):
    """generate-cases 产物落库。

    mode=replace（默认）：删除该对象 pending/rejected 用例后插入（approved 保留）；
    mode=append：不清除，直接追加。返回写入数量。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        obj = conn.execute("SELECT id FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            raise RuntimeError(f"对象 {object_id} 不存在（objects 表）")
        tid = task_id  # 去 task 层：不指定时 case 直接挂对象（task_id=NULL）
        if task_id:
            t = conn.execute("SELECT id FROM tasks WHERE id=? AND object_id=?", (task_id, object_id)).fetchone()
            if not t:
                raise RuntimeError(f"任务 {task_id} 不存在或不属于对象 {object_id}")
        if mode != "append":
            conn.execute("DELETE FROM cases WHERE object_id=? AND status IN ('pending','rejected')",
                         (object_id,))
        for c in cases:
            conn.execute(
                """INSERT INTO cases (object_id, task_id, case_id, title, type, dimension,
                   prompt, output_dir, assertions, status)
                   VALUES (?,?,?,?,?,?,?,?,?,'pending')""",
                (object_id, tid, c["case_id"], c["title"], c["type"],
                 c.get("dimension") or "", c["prompt"], c["output_dir"],
                 jdumps(c["assertions"])))
        conn.commit()
        return len(cases), tid
    finally:
        conn.close()


def review_cases(object_id, action="approve", scope="all", case_ids=None, note="", db_path=None):
    """批量审核用例。action=approve|reject；scope=all|selected。返回 {updated, cases}。"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        obj = conn.execute("SELECT id FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            raise RuntimeError(f"对象 {object_id} 不存在（objects 表）")
        rows = conn.execute(
            "SELECT id, case_id, title FROM cases WHERE object_id=? AND status='pending' ORDER BY id",
            (object_id,)).fetchall()
        if scope == "all":
            targets = [dict(r) for r in rows]
        else:
            ids = {int(x) for x in (case_ids or [])}
            targets = [dict(r) for r in rows if r["id"] in ids]
            missing = ids - {r["id"] for r in targets}
            if missing:
                raise RuntimeError(f"部分 case 不存在或不是待审核状态：{sorted(missing)}")
        if not targets:
            raise RuntimeError("该对象没有可审核的待审核用例")
        # action 参数（approve/reject）映射为规范的 status 值（approved/rejected），
        # 与 write_cases_file 的 status='approved' 查询、旧数据保持一致。
        status_map = {"approve": "approved", "reject": "rejected"}
        status = status_map.get(action, action)
        for t in targets:
            conn.execute(
                "UPDATE cases SET status=?, review_note=?, reviewed_at=datetime('now','localtime') WHERE id=?",
                (status, note or (f"AI 自动审核{'通过' if action == 'approve' else '拒绝'}"), t["id"]))
        conn.commit()
        return {"action": action, "scope": scope, "updated": len(targets),
                "cases": [{"id": t["id"], "case_id": t["case_id"], "title": t["title"]} for t in targets]}
    finally:
        conn.close()


def list_cases(object_id, db_path=None):
    """列出某对象下用例（含状态），供审核/查看。"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, case_id, title, type, status, review_note FROM cases WHERE object_id=? ORDER BY id",
            (object_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_objects(db_path=None):
    """列出评测库（web 所用数据库）中的全部专家/专家团对象。

    这是确认"对象是否存在"的唯一权威入口：AI 不得自行搜索数据库文件、
    不得使用非本库的 --db-path。对象不在列表里 = 库里没有，应执行 import-expert 导入。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, kind, agent_name, current_version, "
            "(SELECT COUNT(*) FROM cases c WHERE c.object_id=o.id) AS case_count "
            "FROM objects o ORDER BY id").fetchall()]
        return {"db": os.path.abspath(resolve_db(db_path)), "objects": rows}
    finally:
        conn.close()


def list_tasks(object_id, db_path=None):
    """列出某对象下评测任务。"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, description, scenario_type, autonomy_level, "
            "(SELECT COUNT(*) FROM cases c WHERE c.task_id=t.id) AS case_count "
            "FROM tasks t WHERE object_id=? ORDER BY id DESC", (object_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def overview(object_id, db_path=None):
    """对象全貌摘要：对象信息 + case 列表 + 最近评测 + 下一步建议。

    一次调用拿全所有决策信息，供 AI 快速判断下一步（避免多次 list-cases/context/help 探索查询，
    显著缩短 OpenWork 侧的执行时间）。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        obj = conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            raise RuntimeError(
                f"对象 {object_id} 不存在（评测库 {os.path.abspath(resolve_db(db_path))}）。"
                f"请先执行 list-objects 查看库里有哪些对象；若目标专家/专家团不在其中，"
                f"用 import-expert 导入后再 overview")
        o = dict(obj)
        cases = [dict(r) for r in conn.execute(
            "SELECT id, case_id, title, type, status FROM cases WHERE object_id=? ORDER BY id",
            (object_id,)).fetchall()]
        runs = [dict(r) for r in conn.execute(
            "SELECT id, status, score, version, agent_on, model, repeat, created_at "
            "FROM runs WHERE object_id=? ORDER BY id DESC LIMIT 8",
            (object_id,)).fetchall()]
        pending = sum(1 for c in cases if c["status"] == "pending")
        approved = sum(1 for c in cases if c["status"] == "approved")
        if pending and not approved:
            step = "review"
            hint = (f"有 {pending} 条待审核 case：询问用户是否全部通过（review-cases --scope=all），"
                    f"通过后 run-eval 发起评测")
            options = [
                {"key": "1", "label": "全部通过", "action": "review-cases --object-id=%d --action=approve --scope=all --db-path=<db>" % object_id, "default": True},
                {"key": "2", "label": "只通过部分", "action": "list-cases --object-id=%d 展示 id 后 review-cases --scope=selected --case-ids=..." % object_id},
                {"key": "3", "label": "驳回全部 / 重新生成", "action": "review-cases --action=reject --scope=all 后重新 generate-case-plan"},
            ]
        elif approved:
            step = "ready"
            hint = f"已有 {approved} 条通过 case，可直接 run-eval 发起评测"
            options = [
                {"key": "1", "label": "发起评测", "action": "mobileeval_ctl.py run-eval --object-id=%d --dry-run --db-path=<db>（先预览参数再确认）" % object_id, "default": True},
                {"key": "2", "label": "再生成一批 case", "action": "generate-case-plan（mode=append 追加）"},
                {"key": "3", "label": "查看/导出报告", "action": "mobileeval_ctl.py open --page=object --object-id=%d" % object_id},
            ]
        else:
            step = "nocase"
            hint = "没有 case：先 generate-case-plan 生成概要 → 用户确认 → generate-cases 写库"
            options = [
                {"key": "1", "label": "生成评测 case", "action": "generate-case-plan 生成概要 → 用户确认 → generate-cases 写库", "default": True},
                {"key": "2", "label": "取消", "action": "流程结束"},
            ]
        return {
            "object": {k: o.get(k) for k in ("id", "name", "kind", "agent_name",
                                              "model", "current_version")},
            "case_stats": {"total": len(cases), "pending": pending, "approved": approved},
            "cases": cases,
            "recent_runs": runs,
            "next_step": step,
            "next_step_hint": hint,
            "options": options,
        }
    finally:
        conn.close()


def _mask_key(key):
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def list_models(db_path=None):
    """列出全局评测模型（api_key 仅返回掩码）。"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM models ORDER BY is_default DESC, id ASC").fetchall()]
        for m in rows:
            m["api_key_hint"] = _mask_key(m.get("api_key") or "")
            m["api_key"] = ""
        return rows
    finally:
        conn.close()


def add_model(name, provider, model, base_url="", api_key="", is_default=0, db_path=None):
    """新增全局评测模型（发起评测时选择，provider/model/base_url/api_key 传给 promptfoo）。"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        if is_default:
            conn.execute("UPDATE models SET is_default=0 WHERE is_default=1")
        cur = conn.execute(
            """INSERT INTO models (name, provider, model, base_url, api_key, is_default)
               VALUES (?,?,?,?,?,?)""",
            (name, provider or "deepseek", model, base_url or "", api_key or "",
             1 if is_default else 0))
        conn.commit()
        return {"id": cur.lastrowid, "name": name, "provider": provider or "deepseek",
                "model": model, "base_url": base_url or "",
                "api_key_hint": _mask_key(api_key or ""), "is_default": 1 if is_default else 0}
    finally:
        conn.close()


def save_suggestion(run_id, content, review_id=None, source="auto", db_path=None):
    """suggest 产物落库到 ai_suggestions。"""
    init_db(db_path)
    conn = get_db(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO ai_suggestions (run_id, review_id, source, content) VALUES (?,?,?,?)",
            (run_id, review_id, source, content))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 专家导入（来源解析 + 隔离工作区）
# --------------------------------------------------------------------------- #

# 专家来源目录（OpenWork 全局专家）
OPENCODE_GLOBAL_DIR = os.path.expanduser("~/.config/opencode")


def _resolve_agents_dir(source_type, source_path):
    """定位专家（团）的 agents 目录与资源目录，返回 (agents_dir, assets_dir)。"""
    if source_type == "global":
        agents_dir = os.path.join(OPENCODE_GLOBAL_DIR, "agents")
        if not os.path.isdir(agents_dir):
            raise RuntimeError(f"OpenWork 全局 agents 目录不存在：{agents_dir}")
        return agents_dir, OPENCODE_GLOBAL_DIR
    if source_type == "workspace":
        sp = os.path.abspath(source_path or "")
        if not os.path.isdir(sp):
            raise RuntimeError(f"workspace 不存在：{sp}")
        for cand in (os.path.join(sp, ".opencode", "agents"), os.path.join(sp, "agents")):
            if os.path.isdir(cand):
                return cand, os.path.dirname(os.path.dirname(cand)) if cand.endswith(os.sep + "agents") else sp
        raise RuntimeError(f"{sp} 下未找到 .opencode/agents 或 agents 目录")
    raise RuntimeError(f"未知 source-type：{source_type}（支持 global|workspace）")


def _pick_agent_files(agents_dir, name):
    """按名称挑 agent .md 文件。name 匹配某 agent → 单专家；否则视为专家团（全部）。

    返回 (md_files, is_team)。
    """
    mds = sorted(f for f in os.listdir(agents_dir)
                 if f.endswith(".md") and not f.startswith("."))
    if not mds:
        raise RuntimeError(f"agents 目录 {agents_dir} 没有 .md 文件")
    if name:
        exact = [f for f in mds if os.path.splitext(f)[0] == name]
        if exact:
            # 指定团长且存在团员 → 导入整个团队；否则单专家
            if name in ("software-team-lead",) and len(mds) > 1:
                return mds, True
            return exact, False
        # 名称不精确匹配单个 agent：看是否匹配团长（则导入整个团队）
        if name in ("software-team-lead",) or "software-team-lead.md" in mds:
            return mds, True
        raise RuntimeError(f"未找到专家/专家团「{name}」，可用 agent：{', '.join(os.path.splitext(f)[0] for f in mds)}")
    # 无名称：存在团长 → 导入整个团队；否则报错提示
    if any(os.path.splitext(f)[0] == "software-team-lead" for f in mds):
        return mds, True
    raise RuntimeError(f"未指定专家名；可用 agent：{', '.join(os.path.splitext(f)[0] for f in mds)}")


def import_expert(name, source_type="global", source_path=None, db_path=None):
    """导入专家（团）到隔离工作区并创建对象记录。

    - 从 OpenWork 全局（~/.config/opencode/agents）或用户 workspace（.opencode/agents）定位；
    - 复制到 MobileEval 专属工作区 eval-data/workspaces/<name>/ 隔离评测；
    - 自动生成 opencode.jsonc 权限配置（非交互评测必需）；
    - 创建 objects 记录（source_type=global|workspace，记录来源路径）。
    返回对象 dict。
    """
    init_db(db_path)
    agents_dir, assets_dir = _resolve_agents_dir(source_type, source_path)
    md_files, is_team = _pick_agent_files(agents_dir, name)
    display_name = name or ("软件专家团" if is_team else os.path.splitext(md_files[0])[0])
    # 工作区必须落在权威项目根（与 web 同库）：从 resolve_db 反推，不用模块级 PROJECT_ROOT
    # （安装副本场景 PROJECT_ROOT 推导错位，会把工作区建到 ~/MobileEval）
    ws_root = os.path.join(resolve_project_home(db_path), "eval-data", "workspaces", display_name)
    agents_dst = os.path.join(ws_root, ".opencode", "agents")
    os.makedirs(agents_dst, exist_ok=True)
    # 复制 agent 定义
    for f in md_files:
        shutil.copy2(os.path.join(agents_dir, f), os.path.join(agents_dst, f))
    # 复制配套资源（avatars/commands 等，取现有目录）
    for sub in ("avatars", "commands"):
        src = os.path.join(assets_dir, sub)
        dst = os.path.join(ws_root, ".opencode", sub)
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(src):
                if not f.startswith("."):
                    shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    # 权限配置兜底（非交互评测必需）
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from run_eval import ensure_permission_config
        ensure_permission_config(ws_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 权限配置写入失败：{exc}", file=sys.stderr)
    # 创建对象记录
    agent_name = "software-team-lead" if is_team else os.path.splitext(md_files[0])[0]
    conn = get_db(db_path)
    try:
        # 同名对象已存在：更新工作区指针（重新导入）
        existing = conn.execute("SELECT id FROM objects WHERE name=? AND source_type=?",
                                (display_name, source_type)).fetchone()
        if existing:
            oid = existing["id"]
            conn.execute(
                """UPDATE objects SET workspace_dir=?, source_path=?, agent_name=?, kind=?
                   WHERE id=?""",
                (ws_root, agents_dir, agent_name, "team" if is_team else "single", oid))
        else:
            cur = conn.execute(
                """INSERT INTO objects (name, kind, agent_name, workspace_dir, source, source_path, source_type)
                   VALUES (?,?,?,?,?,?,?)""",
                (display_name, "team" if is_team else "single", agent_name, ws_root,
                 "global" if source_type == "global" else "local", agents_dir, source_type))
            oid = cur.lastrowid
        conn.commit()
        obj = dict(conn.execute("SELECT * FROM objects WHERE id=?", (oid,)).fetchone())
        return {"object_id": oid, "name": obj["name"], "kind": obj["kind"],
                "agent_name": obj["agent_name"], "workspace_dir": ws_root,
                "source_type": source_type, "source_path": agents_dir,
                "agents": [os.path.splitext(f)[0] for f in md_files],
                "is_team": is_team}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 版本管理 + 迭代优化
# --------------------------------------------------------------------------- #

VERSION_KEEP = 10  # 版本滚动保留最近 N 版


def versions_list(object_id, db_path=None):
    init_db(db_path)
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, version, path, score, note, created_at FROM expert_versions "
            "WHERE object_id=? ORDER BY version DESC", (object_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def restore_version(object_id, version, db_path=None):
    """把专家（团）恢复到历史版本 v<N>。

    先将当前版本快照（若尚无快照）确保可逆，再把 versions/v<N>/agents 覆盖回
    隔离工作区 .opencode/agents 与全局 ~/.config/opencode/agents（与 optimize-expert
    写回行为一致），并更新 current_version。
    返回 {version, restored, current_version, global}。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        obj = conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            raise RuntimeError(f"对象 {object_id} 不存在")
        ws_root = obj["workspace_dir"] or ""
        src = os.path.join(_versions_root(ws_root), f"v{version}", "agents")
        if not os.path.isdir(src):
            raise RuntimeError(f"版本 v{version} 快照不存在：{src}")
        files = [f for f in os.listdir(src) if f.endswith(".md")]
        if not files:
            raise RuntimeError(f"版本 v{version} 快照中没有 agent 定义文件")
        # 0) 恢复前快照当前版本（若该版本尚无快照），保证切换可逆
        cur = int(obj["current_version"] or 1)
        if cur != int(version):
            _snapshot_workspace(ws_root, cur)
        # 1) 隔离工作区副本
        dst_ws = os.path.join(ws_root, ".opencode", "agents")
        if os.path.isdir(dst_ws):
            shutil.rmtree(dst_ws, ignore_errors=True)
        os.makedirs(dst_ws, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(src, f), os.path.join(dst_ws, f))
        # 2) 全局 agents（与 optimize-expert 一致：source_type=global 时写 ~/.config/opencode/agents）
        global_done = False
        if obj["source_type"] == "global":
            gdir = os.path.join(OPENCODE_GLOBAL_DIR, "agents")
            if os.path.isdir(gdir):
                for f in files:
                    shutil.copy2(os.path.join(src, f), os.path.join(gdir, f))
                global_done = True
        # 3) 更新当前版本
        conn.execute("UPDATE objects SET current_version=? WHERE id=?",
                     (int(version), object_id))
        conn.commit()
        return {"version": int(version), "restored": len(files),
                "current_version": int(version), "global": global_done}
    finally:
        conn.close()


def _versions_root(ws_root):
    return os.path.join(ws_root, "versions")


def _snapshot_workspace(ws_root, version):
    """快照当前隔离工作区的 .opencode/agents 到 versions/v<version>/agents。"""
    src = os.path.join(ws_root, ".opencode", "agents")
    if not os.path.isdir(src):
        return ""
    dst = os.path.join(_versions_root(ws_root), f"v{version}", "agents")
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        if f.endswith((".md", ".json", ".jsonc")):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    return os.path.dirname(dst)


def _prune_versions(object_id, ws_root, keep=VERSION_KEEP, db_path=None):
    """滚动清理：只保留最近 keep 个版本（删目录 + 删记录）。"""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, version, path FROM expert_versions WHERE object_id=? "
            "ORDER BY version DESC", (object_id,)).fetchall()
        for r in rows[keep:]:
            p = r["path"]
            if p and os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            conn.execute("DELETE FROM expert_versions WHERE id=?", (r["id"],))
        conn.commit()
    finally:
        conn.close()


def _read_agents(agents_dir):
    """读 agents 目录下所有 .md，返回 {name: content}。"""
    out = {}
    if not os.path.isdir(agents_dir):
        return out
    for f in sorted(os.listdir(agents_dir)):
        if f.endswith(".md") and not f.startswith("."):
            with open(os.path.join(agents_dir, f), encoding="utf-8") as fh:
                out[os.path.splitext(f)[0]] = fh.read()
    return out


def _optimize_prompt(agent_name, current_md, suggestion):
    return (
        "你是专家系统优化器。基于评测暴露的弱点，优化专家 agent 的 Markdown 定义，"
        "提升该专家在真实评测中的表现。\n\n"
        f"【评测优化建议】\n{suggestion}\n\n"
        f"【当前 agent 定义（{agent_name}）】\n{current_md}\n\n"
        "优化规则：\n"
        "1. frontmatter 的 name / displayName / profession / color / avatar_url / mode 必须原样保留（身份标识不可变）；\n"
        "2. 针对评测建议改进：工作流程（SOP）、输出规范、验收标准、质量门控、异常处理、"
        "委派与协作方式、权限边界等；保留角色定位与职责边界；\n"
        "3. 不得引入评测建议之外的大幅重构，保持其余内容稳定；\n"
        "4. 输出完整的 Markdown 文件内容（含 frontmatter 和正文），不要代码块标记，不要解释。"
    )


def optimize_expert(object_id, run_id, db_path=None, note="", only_agents=None):
    """根据评测结果迭代优化专家（团）。

    流程：读取评测建议（ai_suggestions，AI 建议本身已含人工评审意见，由 suggest 生成时
    将全部人工评审喂入）→ 快照当前版本（保存旧版）→ AI 逐个 agent 重写 .md →
    写回隔离工作区副本 + OpenWork 全局（~/.config/opencode/agents）→ 记录版本与优化关系。
    baseline_run_id 记入 optimizations，回归评测由调用方（run-eval）继续。
    说明：无建议时明确报错，提示先执行 suggest 生成（人工评审持久化在 reviews 表不丢失）。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        obj = dict(conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone())
        if not obj:
            raise RuntimeError(f"对象 {object_id} 不存在")
        ws_root = obj["workspace_dir"] or ""
        if not os.path.isdir(ws_root):
            raise RuntimeError(f"隔离工作区不存在：{ws_root}（请先 import-expert）")
        # 读取评测建议（ai_suggestions 中该 run 最近一条）
        sug = conn.execute(
            "SELECT id, content FROM ai_suggestions WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,)).fetchone()
        if not sug:
            raise RuntimeError(f"run {run_id} 没有优化建议，请先执行 suggest 生成")
        suggestion_id, suggestion = sug["id"], sug["content"]
        obj_agents_dir = os.path.join(OPENCODE_GLOBAL_DIR, "agents") \
            if obj.get("source_type") == "global" else obj.get("source_path") or ""
        version = int(obj.get("current_version") or 1)
    finally:
        conn.close()

    # 1) 快照当前版本（保存旧版）
    snapshot_path = _snapshot_workspace(ws_root, version)
    # 2) 读取当前 agent 定义（以隔离工作区为准，全局缺失时用全局）
    local_agents = _read_agents(os.path.join(ws_root, ".opencode", "agents"))
    global_agents = _read_agents(obj_agents_dir) if os.path.isdir(obj_agents_dir) else {}
    target_agents = {name: content for name, content in local_agents.items()}
    for name, content in global_agents.items():
        if name not in target_agents:
            target_agents[name] = content

    # 3) 逐个 agent 优化
    optimized = []
    for agent_name, current_md in sorted(target_agents.items()):
        if only_agents and agent_name not in only_agents:
            continue
        raw = _call([{"role": "user", "content": _optimize_prompt(agent_name, current_md, suggestion)}],
                    max_tokens=6000)
        new_md = raw.strip()
        if new_md.startswith("```"):
            new_md = new_md.split("```", 2)[1]
            if new_md.startswith("markdown") or new_md.startswith("md"):
                new_md = new_md.split("\n", 1)[1] if "\n" in new_md else ""
            new_md = new_md.strip()
        if not new_md.startswith("---"):
            raise RuntimeError(f"agent {agent_name} 优化输出不是合法 Markdown 定义")
        # 写回隔离工作区副本
        with open(os.path.join(ws_root, ".opencode", "agents", f"{agent_name}.md"),
                  "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_md)
        # 写回 OpenWork 全局（当前用户使用的版本）
        if obj_agents_dir and os.path.isdir(obj_agents_dir):
            with open(os.path.join(obj_agents_dir, f"{agent_name}.md"),
                      "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new_md)
        optimized.append(agent_name)

    if not optimized:
        raise RuntimeError("没有 agent 被优化（only_agents 未命中）")

    # 4) 记录版本与优化关系（滚动保留）
    new_version = version + 1
    conn = get_db(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO expert_versions (object_id, version, path, score, note)
               VALUES (?,?,?,?,?)""",
            (object_id, version, snapshot_path, None,
             note or f"优化前版本（baseline run {run_id}）"))
        conn.execute("UPDATE objects SET current_version=? WHERE id=?", (new_version, object_id))
        conn.execute(
            """INSERT INTO optimizations (object_id, baseline_run_id, suggestion_id,
               version_from, version_to, summary) VALUES (?,?,?,?,?,?)""",
            (object_id, run_id, suggestion_id, version, new_version,
             json.dumps({"optimized": optimized}, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    _prune_versions(object_id, ws_root, VERSION_KEEP, db_path)

    return {"object_id": object_id, "version_from": version, "version_to": new_version,
            "baseline_run_id": run_id, "suggestion_id": suggestion_id,
            "optimized": optimized, "note": note}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="expert_tools", description="promptfoo-expert-eval AI 工具集")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ctx = sub.add_parser("context", help="导出被测专家（团）上下文")
    p_ctx.add_argument("--workspace", required=True)
    p_ctx.add_argument("--agent", default="software-team-lead")

    p_an = sub.add_parser("analyze-expert", help="分析专家包 → 评测任务配置 JSON（带 --object-id 时写库）")
    p_an.add_argument("--workspace", required=True)
    p_an.add_argument("--agent", default="software-team-lead")
    p_an.add_argument("--name", default="")
    p_an.add_argument("--description", default="")
    p_an.add_argument("--object-id", type=int, default=None, help="提供则把任务配置写入 tasks 表")
    p_an.add_argument("--db-path", default=None, help="SQLite 数据库路径（默认 MOBILEEVAL_DB 或 <仓库同级>/MobileEval/eval-data/mobileeval.db）")

    p_gc = sub.add_parser("generate-cases", help="生成评测 case 数组（带 --object-id 时写库）")
    p_gc.add_argument("--workspace", required=True)
    p_gc.add_argument("--agent", default="software-team-lead")
    p_gc.add_argument("--name", default="")
    p_gc.add_argument("--description", default="")
    p_gc.add_argument("--count", type=int, default=6)
    p_gc.add_argument("--plan", default="", help="用户已确认的 case 概要 JSON 字符串（generate-case-plan 输出），严格按此展开")
    p_gc.add_argument("--object-id", type=int, default=None, help="提供则把 case 写入 cases 表")
    p_gc.add_argument("--task-id", type=int, default=None, help="case 挂载的任务（默认该对象最新任务）")
    p_gc.add_argument("--mode", default="replace", choices=["replace", "append"],
                      help="replace=覆盖未审核（默认）| append=直接追加")
    p_gc.add_argument("--db-path", default=None)

    p_gcp = sub.add_parser("generate-case-plan", help="生成评测 case 概要（供用户确认，不写库）")
    p_gcp.add_argument("--workspace", required=True)
    p_gcp.add_argument("--agent", default="software-team-lead")
    p_gcp.add_argument("--name", default="")
    p_gcp.add_argument("--description", default="")
    p_gcp.add_argument("--count", type=int, default=6)

    p_rc = sub.add_parser("review-cases", help="批量审核用例（approve/reject）")
    p_rc.add_argument("--object-id", type=int, required=True)
    p_rc.add_argument("--action", default="approve", choices=["approve", "reject"])
    p_rc.add_argument("--scope", default="all", choices=["all", "selected"])
    p_rc.add_argument("--case-ids", default="", help="scope=selected 时用逗号分隔的 case 数据库 id")
    p_rc.add_argument("--note", default="")
    p_rc.add_argument("--db-path", default=None)

    p_lc = sub.add_parser("list-cases", help="列出某对象下用例（含状态）")
    p_lc.add_argument("--object-id", type=int, required=True)
    p_lc.add_argument("--db-path", default=None)

    p_lt = sub.add_parser("list-tasks", help="列出某对象下评测任务")
    p_lt.add_argument("--object-id", type=int, required=True)
    p_lt.add_argument("--db-path", default=None)

    p_ov = sub.add_parser("overview", help="对象全貌摘要（对象+case+最近评测+下一步建议，一次拿全）")
    p_ov.add_argument("--object-id", type=int, required=True)
    p_ov.add_argument("--db-path", default=None)

    p_lm = sub.add_parser("list-models", help="列出全局评测模型（api_key 仅返回掩码）")
    p_lm.add_argument("--db-path", default=None)

    p_lo = sub.add_parser("list-objects", help="列出评测库（web 所用库）中的专家/专家团（对象存在与否的唯一权威入口）")
    p_lo.add_argument("--db-path", default=None)
    p_am = sub.add_parser("add-model", help="新增全局评测模型（发起评测时选择，传给 promptfoo）")
    p_am.add_argument("--name", required=True, help="显示名")
    p_am.add_argument("--provider", default="deepseek")
    p_am.add_argument("--model", required=True, help="模型 id")
    p_am.add_argument("--base-url", default="")
    p_am.add_argument("--api-key", default="")
    p_am.add_argument("--is-default", type=int, default=0)
    p_am.add_argument("--db-path", default=None)

    p_ie = sub.add_parser("import-expert", help="从 OpenWork 全局或 workspace 导入专家（团）到隔离工作区")
    p_ie.add_argument("--name", default="", help="专家/专家团名（匹配 agents 目录；空=自动识别团队）")
    p_ie.add_argument("--source-type", default="global", choices=["global", "workspace"])
    p_ie.add_argument("--source-path", default=None, help="source-type=workspace 时的专家包目录")
    p_ie.add_argument("--db-path", default=None)

    p_sg = sub.add_parser("suggest", help="解读评测结果 + 优化建议（带 --run-id 时写库）")
    p_sg.add_argument("--summary", required=True, help="summary.json 路径")
    p_sg.add_argument("--review", default=None, help="人工评审 JSON 路径（可选）")
    p_sg.add_argument("--meta", default=None, help="运行元数据 JSON 路径（可选）")
    p_sg.add_argument("--run-id", type=int, default=None, help="提供则把建议写入 ai_suggestions 表")
    p_sg.add_argument("--db-path", default=None)

    p_vl = sub.add_parser("versions-list", help="列出专家（团）版本历史")
    p_vl.add_argument("--object-id", type=int, required=True)
    p_vl.add_argument("--db-path", default=None)

    p_rv = sub.add_parser("restore-version", help="把专家（团）恢复到历史版本 v<N>（快照覆盖回隔离工作区+全局）")
    p_rv.add_argument("--object-id", type=int, required=True)
    p_rv.add_argument("--version", type=int, required=True)
    p_rv.add_argument("--db-path", default=None)

    p_oe = sub.add_parser("optimize-expert", help="基于评测建议迭代优化专家（团），保存旧版 + 写回全局")
    p_oe.add_argument("--object-id", type=int, required=True)
    p_oe.add_argument("--run-id", type=int, required=True, help="基线评测 run id（须已生成建议：suggest --run-id，建议已含人工评审意见）")
    p_oe.add_argument("--note", default="")
    p_oe.add_argument("--only-agents", default="", help="只优化指定 agent（逗号分隔，默认全部）")
    p_oe.add_argument("--db-path", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "context":
        _emit(load_expert_context(args.workspace, args.agent))
    elif args.cmd == "analyze-expert":
        config = analyze_expert(args.workspace, args.agent, args.name, args.description)
        if args.object_id:
            oid = save_task(args.object_id, args.name, args.description, config, args.db_path)
            _emit({"object_id": oid, "config": config})
        else:
            _emit(config)
    elif args.cmd == "generate-cases":
        plan = json.loads(args.plan) if args.plan else None
        cases = generate_cases(args.workspace, args.agent,
                               {"name": args.name, "description": args.description},
                               args.count, plan=plan)
        if args.object_id:
            n, tid = save_cases(args.object_id, cases, args.db_path, args.task_id, args.mode)
            _emit({"generated": n, "task_id": tid, "mode": args.mode,
                   "hint": "用 open --page=object --object-id=<id> 打开页面查看 case"})
        else:
            _emit(cases)
    elif args.cmd == "generate-case-plan":
        plan = generate_case_plan(args.workspace, args.agent,
                                  {"name": args.name, "description": args.description}, args.count)
        _emit({"status": "awaiting_confirmation", "plan": plan,
               "options": [
                   {"key": "1", "label": "确认，按此概要生成完整 case",
                    "action": "generate-cases --count=%d --plan=<plan JSON> --object-id=<id> --db-path=<db>" % args.count,
                    "default": True},
                   {"key": "2", "label": "调整数量或内容",
                    "action": "用户指定 count/标题/类型/验证点后重跑 generate-case-plan"},
                   {"key": "3", "label": "重新生成概要",
                    "action": "重新执行 generate-case-plan（可换描述/数量）"},
                   {"key": "4", "label": "取消",
                    "action": "流程结束，不生成 case"},
               ],
               "hint": "把 plan 展示给用户确认并按 options 渲染；确认后把 plan JSON 作为 --plan 传给 generate-cases"})
    elif args.cmd == "review-cases":
        case_ids = [int(x) for x in args.case_ids.split(",") if x.strip()]
        _emit(review_cases(args.object_id, args.action, args.scope, case_ids, args.note, args.db_path))
    elif args.cmd == "list-cases":
        _emit(list_cases(args.object_id, args.db_path))
    elif args.cmd == "list-tasks":
        _emit(list_tasks(args.object_id, args.db_path))
    elif args.cmd == "overview":
        _emit(overview(args.object_id, args.db_path))
    elif args.cmd == "list-objects":
        _emit(list_objects(args.db_path))
    elif args.cmd == "list-models":
        _emit(list_models(args.db_path))
    elif args.cmd == "add-model":
        _emit(add_model(args.name, args.provider, args.model, args.base_url,
                        args.api_key, args.is_default, args.db_path))
    elif args.cmd == "import-expert":
        _emit(import_expert(args.name, args.source_type, args.source_path, args.db_path))
    elif args.cmd == "suggest":
        with open(args.summary, encoding="utf-8") as fh:
            summary = json.load(fh)
        review = json.load(open(args.review, encoding="utf-8")) if args.review else None
        meta = json.load(open(args.meta, encoding="utf-8")) if args.meta else None
        content = suggest(summary, review, meta)
        if args.run_id:
            sid = save_suggestion(args.run_id, content,
                                  review_id=(review or {}).get("id") if review else None,
                                  db_path=args.db_path)
            _emit({"suggestion_id": sid, "content": content[:200]})
        else:
            print(content)
    elif args.cmd == "versions-list":
        _emit(versions_list(args.object_id, args.db_path))
    elif args.cmd == "restore-version":
        _emit(restore_version(args.object_id, args.version, args.db_path))
    elif args.cmd == "optimize-expert":
        only = [x.strip() for x in args.only_agents.split(",") if x.strip()] or None
        _emit(optimize_expert(args.object_id, args.run_id, args.db_path,
                              args.note, only_agents=only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
