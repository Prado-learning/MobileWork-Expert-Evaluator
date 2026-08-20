"""专家导入 / 版本管理 / 迭代优化 / 对比报告 API（全部走插件脚本）。"""
from flask import Blueprint, jsonify, request

import plugin_cli
from db import get_db, jloads, row_to_dict

expert_bp = Blueprint("expert", __name__)


@expert_bp.post("/experts/import")
def import_expert():
    """从 OpenWork 全局或 workspace 导入专家（团）到隔离工作区并创建对象。

    body: {name?, source_type: global|workspace, source_path?}
    """
    try:
        body = request.get_json(force=True) or {}
        result = plugin_cli.import_expert(
            body.get("name", ""), body.get("source_type") or "global", body.get("source_path"))
        return jsonify(result), 201
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400


@expert_bp.get("/objects/<int:object_id>/versions")
def versions(object_id):
    try:
        return jsonify(plugin_cli.versions_list(object_id))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@expert_bp.post("/objects/<int:object_id>/versions/<int:version>/restore")
def restore_version(object_id, version):
    """把专家（团）恢复到历史版本 v<N>（快照覆盖回隔离工作区 + 全局 agents）。"""
    try:
        return jsonify(plugin_cli.restore_version(object_id, version))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@expert_bp.get("/objects/<int:object_id>/optimizations")
def optimizations(object_id):
    try:
        return jsonify(plugin_cli.optimizations_list(object_id))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@expert_bp.post("/objects/<int:object_id>/optimize")
def optimize(object_id):
    """基于评测建议迭代优化专家（团）：保存旧版 → 逐个 agent 重写 → 写回全局+副本。

    body: {run_id, note?, only_agents?}
    """
    try:
        body = request.get_json(force=True) or {}
        run_id = int(body.get("run_id") or 0)
        if run_id <= 0:
            return jsonify({"error": "run_id 必填"}), 400
        result = plugin_cli.optimize_expert(
            object_id, run_id, body.get("note", ""), body.get("only_agents"))
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@expert_bp.get("/compare")
def compare():
    """对比两次评测（优化前后）。params: base=<run1>&opt=<run2>"""
    base_id = request.args.get("base", type=int)
    opt_id = request.args.get("opt", type=int)
    if not base_id or not opt_id:
        return jsonify({"error": "base 与 opt 参数必填"}), 400
    conn = get_db()
    try:
        base = row_to_dict(conn.execute("SELECT * FROM runs WHERE id=?", (base_id,)).fetchone())
        opt = row_to_dict(conn.execute("SELECT * FROM runs WHERE id=?", (opt_id,)).fetchone())
        if not base or not opt:
            return jsonify({"error": "运行不存在"}), 404
        base_cases = conn.execute(
            "SELECT case_id, case_title, case_type, pass, score, error FROM case_results "
            "WHERE run_id=? ORDER BY id", (base_id,)).fetchall()
        opt_cases = conn.execute(
            "SELECT case_id, case_title, case_type, pass, score, error FROM case_results "
            "WHERE run_id=? ORDER BY id", (opt_id,)).fetchall()
        base_map = {c["case_id"]: dict(c) for c in base_cases}
        opt_map = {c["case_id"]: dict(c) for c in opt_cases}
        case_ids = sorted(set(base_map) | set(opt_map))
        detail = []
        for cid in case_ids:
            b, o = base_map.get(cid), opt_map.get(cid)
            detail.append({
                "case_id": cid,
                "title": (b or o).get("case_title", ""),
                "base": {"pass": bool((b or {}).get("pass")), "score": (b or {}).get("score"),
                         "error": (b or {}).get("error", "")},
                "opt": {"pass": bool((o or {}).get("pass")), "score": (o or {}).get("score"),
                        "error": (o or {}).get("error", "")},
            })
        return jsonify({
            "base": {"id": base["id"], "status": base["status"], "score": base["score"],
                     "pass": base["pass_count"], "fail": base["fail_count"],
                     "error": base["error_count"], "created_at": base["created_at"]},
            "opt": {"id": opt["id"], "status": opt["status"], "score": opt["score"],
                    "pass": opt["pass_count"], "fail": opt["fail_count"],
                    "error": opt["error_count"], "created_at": opt["created_at"]},
            "cases": detail,
        })
    finally:
        conn.close()
