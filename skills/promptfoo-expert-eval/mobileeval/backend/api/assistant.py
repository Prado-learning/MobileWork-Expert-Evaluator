"""AI 能力 API：工具执行（走插件脚本，无 Claude SDK 依赖）与优化建议查询。

架构约定：所有大模型能力统一由插件脚本（promptfoo-expert-eval 的 expert_tools.py）
产生并直接落库；AI 对话由 OpenWork 完成，本模块不再提供聊天接口。
"""
from flask import Blueprint, jsonify, request

import plugin_cli

assistant_bp = Blueprint("assistant", __name__)


@assistant_bp.post("/assistant/tools/<tool_name>")
def invoke_tool(tool_name):
    """直接执行某个工具（底层是插件脚本 expert_tools.py），供网页按钮/手动触发使用。"""
    try:
        args = request.get_json(force=True) or {}
        result = plugin_cli.execute_tool(tool_name, args)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@assistant_bp.get("/runs/<int:run_id>/suggestions")
def list_suggestions(run_id):
    """列出优化建议（纯查询，不自动生成）。

    建议由「生成建议」动作产生：generate_suggestions 会把该 run 全部人工评审
    （综合 + 逐 case）喂给 AI，因此 AI 建议本身已含人工意见，无需额外强制重生成。
    """
    from db import get_db, row_to_dict
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM ai_suggestions WHERE run_id=? ORDER BY id DESC", (run_id,)).fetchall()
        return jsonify([row_to_dict(r) for r in rows])
    finally:
        conn.close()
