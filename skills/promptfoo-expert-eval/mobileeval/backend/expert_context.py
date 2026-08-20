"""从评测工作区加载被测专家（团）的实际定义，作为 AI 评测配置分析的输入。

分析来源默认是被测对象本身（角色/技能/权限/委派/工作流），任务描述仅作辅助。
"""
import json
import os

import config


def _read_jsonc(path):
    if not os.path.exists(path):
        return {}
    lines = [ln for ln in open(path, encoding="utf-8").read().splitlines()
             if not ln.lstrip().startswith(("//", "/*"))]
    try:
        return json.loads("\n".join(lines))
    except ValueError:
        return {}


def _agent_md_summary(agents_dir, agent_id, max_chars=400):
    """读取单个 agent 的 md 定义（frontmatter + 正文工作流摘要）。"""
    path = os.path.join(agents_dir, f"{agent_id}.md")
    if not os.path.exists(path):
        return ""
    raw = open(path, encoding="utf-8").read()
    parts = raw.split("---", 2)
    fm = {}
    body = raw
    if len(parts) >= 3:
        try:
            fm = json.loads(parts[1]) if parts[1].lstrip().startswith("{") else _yaml_frontmatter(parts[1])
        except Exception:  # noqa: BLE001
            fm = {}
        body = parts[2]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    body_text = " ".join(lines)[:max_chars]
    return {"frontmatter": fm, "body": body_text}


def _yaml_frontmatter(fm_text):
    """极简 YAML frontmatter 解析（name/description/displayName/profession/steps/mode）。"""
    out = {}
    for ln in fm_text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", "-", "'")):
            continue
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def load_expert_context(workspace_dir=None, agent_name=None):
    """加载被测专家（团）上下文，返回结构化摘要文本。

    workspace_dir：评测工作区（含 .opencode/）；agent_name：被测团长 agent id。
    """
    workspace_dir = workspace_dir or config.DEFAULT_WORKSPACE
    agent_name = agent_name or config.DEFAULT_AGENT
    oc_dir = os.path.join(workspace_dir, ".opencode")
    if not os.path.isdir(oc_dir):
        return {"agent_name": agent_name, "workspace_dir": workspace_dir,
                "summary": "（未找到 .opencode 配置，无法读取专家定义）", "agents": []}

    cfg = _read_jsonc(os.path.join(oc_dir, "opencode.jsonc"))
    agents = []
    for aid, a in (cfg.get("agent") or {}).items():
        perm = a.get("permission") or {}
        task_allow = []
        tv = perm.get("task")
        if isinstance(tv, dict):
            task_allow = [k for k, v in tv.items() if v == "allow"]
        agents.append({
            "id": aid,
            "description": (a.get("description") or "")[:200],
            "mode": a.get("mode", ""),
            "steps": a.get("steps"),
            "task_allow": task_allow,
            "permission": {
                "bash": "ask" if isinstance(perm.get("bash"), dict) and perm["bash"].get("*") == "ask"
                        else ("allow(白名单)" if isinstance(perm.get("bash"), dict) else perm.get("bash")),
                "edit": perm.get("edit"),
                "webfetch": perm.get("webfetch"),
            },
        })

    # agent md 补充角色/工作流信息
    agents_dir = os.path.join(oc_dir, "agents")
    for ag in agents:
        md = _agent_md_summary(agents_dir, ag["id"]) if os.path.isdir(agents_dir) else {}
        if md:
            fm = md.get("frontmatter") or {}
            prof = fm.get("profession") or fm.get("description") or ""
            ag["md_role"] = prof[:200]
            ag["md_workflow"] = md.get("body", "")[:300]

    lead = next((a for a in agents if a["id"] == agent_name), agents[0] if agents else None)
    summary_parts = [f"被测对象：{agent_name}（工作区 {workspace_dir}）"]
    if lead:
        summary_parts.append(f"团长：{lead['id']} · {lead.get('md_role') or lead.get('description') or ''} · "
                             f"steps={lead.get('steps')} · 可委派: {','.join(lead.get('task_allow') or []) or '无'}")
    members = [a for a in agents if a["id"] != agent_name]
    if members:
        summary_parts.append("团员：")
        for m in members:
            summary_parts.append(f"  - {m['id']} · {m.get('md_role') or m.get('description') or ''} · steps={m.get('steps')}")
    return {
        "agent_name": agent_name,
        "workspace_dir": workspace_dir,
        "agents": agents,
        "summary": "\n".join(summary_parts),
    }
