"""mobilework-expert-manager 桥接 API。

页面「AI 创建/编辑」入口把业务目标提交到这里，后端返回结构化提示词（可直接粘贴到
OpenWork 对话框，由 agent 加载 skills/mobilework-expert-manager/SKILL.md 执行），
并可选择性地把任务记录到数据库（chat_sessions 语义），供后续追溯。

设计原则：
- 本桥接不直接执行 manager 技能（技能由 OpenWork agent 在会话中调用，遵循其安全边界）。
- 页面提交 → 校验 → 返回「提示词卡片」+ 可选落库；agent 拿到提示词后在对话框执行。
"""
import json
import os

from flask import Blueprint, jsonify, request

bridge_bp = Blueprint("expert_manager_bridge", __name__)


def _skill_root():
    """定位 mobilework-expert-manager 技能目录（本插件捆绑路径）。

    查找顺序：
    1. 环境变量 MOBILEEVAL_SKILLS_ROOT（显式指定 skills 根，如项目仓库 skills/ 目录）
    2. 运行目录布局：<project>/skills/mobilework-expert-manager（模板复制后同根）
    3. 项目源码布局：backend/ 上溯到插件 skills 根
    """
    env = os.environ.get("MOBILEEVAL_SKILLS_ROOT")
    if env:
        c = os.path.abspath(os.path.join(env, "mobilework-expert-manager"))
        if os.path.isfile(os.path.join(c, "SKILL.md")):
            return c
    here = os.path.dirname(os.path.abspath(__file__))
    # backend/api/ -> backend/ -> <project root>/（MobileEval 模板布局）
    run_root = os.path.abspath(os.path.join(here, "..", ".."))
    c = os.path.join(run_root, "skills", "mobilework-expert-manager")
    if os.path.isfile(os.path.join(c, "SKILL.md")):
        return c
    # 项目源码布局（backend -> mobileeval -> skill 目录 -> 插件 skills 根）
    for c in (
        os.path.abspath(os.path.join(here, "..", "..", "..", "..", "skills", "mobilework-expert-manager")),
        os.path.abspath(os.path.join(here, "..", "..", "..", "skills", "mobilework-expert-manager")),
    ):
        if os.path.isfile(os.path.join(c, "SKILL.md")):
            return c
    return None


@bridge_bp.get("/expert-manager/status")
def status():
    """检查 manager 技能是否已捆绑到本插件。"""
    root = _skill_root()
    return jsonify({
        "bundled": root is not None,
        "skill_root": root,
        "scripts": len(os.listdir(os.path.join(root, "scripts"))) if root and os.path.isdir(os.path.join(root, "scripts")) else 0,
    })


@bridge_bp.post("/expert-manager/generate")
def generate():
    """接收业务目标，返回供 agent 执行的提示词卡片。

    body: {"goal": "…", "kind": "create|convert|edit", "extra": {}}
    """
    body = request.get_json(force=True) or {}
    goal = (body.get("goal") or "").strip()
    kind = (body.get("kind") or "create").strip()
    if not goal:
        return jsonify({"error": "请描述业务目标（如：创建一个负责代码评审的专家团）"}), 400
    if kind not in ("create", "convert", "edit"):
        return jsonify({"error": f"kind 仅支持 create|convert|edit，收到 {kind}"}), 400

    skill_root = _skill_root()
    if not skill_root:
        return jsonify({"error": "mobilework-expert-manager 技能未捆绑在本插件中（缺少 skills/mobilework-expert-manager/SKILL.md）"}), 500

    prompt = _build_prompt(goal, kind, body.get("extra") or {})
    # 可选落库（chat_sessions 记录任务，便于页面/报告追溯）
    saved = None
    try:
        from db import get_db, row_to_dict
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO chat_sessions (object_id, title) VALUES (NULL, ?)",
                (f"Expert Manager 请求：{goal[:50]}",))
            saved = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 落库失败不影响返回
        saved = {"error": str(exc)}

    return jsonify({
        "ok": True,
        "kind": kind,
        "goal": goal,
        "skill_root": skill_root,
        "prompt": prompt,
        "session_id": saved,
        "hint": "把下方 prompt 复制到 OpenWork 对话框发送，agent 将加载 mobilework-expert-manager 技能执行。",
    })


def _build_prompt(goal, kind, extra):
    verb = {"create": "创建", "convert": "转换", "edit": "编辑"}[kind]
    detail = ""
    if kind == "convert" and extra.get("source_path"):
        detail += f"\n来源路径：{extra['source_path']}"
    if kind == "edit" and extra.get("target_name"):
        detail += f"\n目标专家/专家团：{extra['target_name']}"
    if extra.get("note"):
        detail += f"\n补充说明：{extra['note']}"
    return (
        f"请加载本插件捆绑的 mobilework-expert-manager 技能"
        f"（skills/mobilework-expert-manager/SKILL.md，脚本在其 scripts/ 目录），"
        f"按其中协议帮我{verb}一个 OpenCode 格式的专家/专家团。\n\n"
        f"业务目标：{goal}{detail}\n\n"
        f"要求：先按技能的新手交互协议确认需求与方案，完整业务确认卡确认后再生成；"
        f"生成结果需为 OpenCode 格式（含 .opencode/agents/*.md 与 opencode.json）。"
        f"完成后告诉我产物路径，我再把它导入评测中心。"
    )


def _register(app):
    app.register_blueprint(bridge_bp, url_prefix="/api")
