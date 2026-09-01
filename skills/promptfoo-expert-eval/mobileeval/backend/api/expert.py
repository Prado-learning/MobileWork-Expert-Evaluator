"""专家导入 / 版本管理 / 迭代优化 / 对比报告 API（全部走插件脚本）。"""
import difflib
import os

from flask import Blueprint, jsonify, request

import plugin_cli
from db import get_db, jloads, row_to_dict

expert_bp = Blueprint("expert", __name__)


def _version_files(object_id, spec):
    """读取某版本的 agent 定义文件。spec = 版本号 或 "current"（当前隔离工作区）。

    返回 ({相对路径: 文本}, 显示标签)。路径强制限定在对象工作区内（安全边界）。
    """
    ws, _ = plugin_cli._resolve_object(object_id)
    ws_real = os.path.realpath(ws)
    if spec == "current":
        root = os.path.join(ws, ".opencode", "agents")
        label = "当前工作区"
    else:
        try:
            vn = int(spec)
        except (TypeError, ValueError):
            raise RuntimeError(f"版本参数无效：{spec}（应为版本号或 current）")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT path FROM expert_versions WHERE object_id=? AND version=?",
                (object_id, vn)).fetchone()
        finally:
            conn.close()
        if not row or not row["path"]:
            raise RuntimeError(f"版本 v{vn} 不存在快照")
        root = row["path"]
        if not os.path.isdir(root) and os.path.isdir(os.path.join(root, "agents")):
            root = os.path.join(root, "agents")
        label = f"v{vn}"
    if not os.path.isdir(root):
        raise RuntimeError(f"{label} 的 agent 目录不存在：{root}")
    if not os.path.realpath(root).startswith(ws_real + os.sep):
        raise RuntimeError("版本快照路径不在对象工作区内，拒绝读取")
    files = {}
    for dirpath, _, names in os.walk(root):
        for name in sorted(names):
            fp = os.path.join(dirpath, name)
            rel = os.path.relpath(fp, root).replace(os.sep, "/")
            try:
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    files[rel] = fh.read()
            except OSError:
                continue
    return files, label


@expert_bp.get("/objects/<int:object_id>/versions/diff")
def version_diff(object_id):
    """两版专家定义的 diff：params a=<版本|current>&b=<版本|current>。

    optimize-expert 生成新版本并快照旧版后，用此接口查看「改了什么」，闭环优化。
    """
    a = request.args.get("a", "")
    b = request.args.get("b", "")
    if not a or not b:
        return jsonify({"error": "a 与 b 参数必填（版本号或 current）"}), 400
    try:
        files_a, label_a = _version_files(object_id, a)
        files_b, label_b = _version_files(object_id, b)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 400
    paths = sorted(set(files_a) | set(files_b))
    files = []
    for p in paths:
        la = (files_a.get(p) or "").splitlines()
        lb = (files_b.get(p) or "").splitlines()
        if p not in files_a:
            status = "added"
        elif p not in files_b:
            status = "removed"
        elif la == lb:
            continue
        else:
            status = "changed"
        lines = []
        for ln in difflib.unified_diff(la, lb, fromfile=f"{label_a}/{p}",
                                       tofile=f"{label_b}/{p}", lineterm=""):
            if ln.startswith("+++") or ln.startswith("---"):
                kind = "meta"
            elif ln.startswith("@@"):
                kind = "hunk"
            elif ln.startswith("+"):
                kind = "add"
            elif ln.startswith("-"):
                kind = "del"
            else:
                kind = "ctx"
            lines.append({"kind": kind, "text": ln})
        files.append({
            "path": p, "status": status, "lines": lines,
            "added": sum(1 for x in lines if x["kind"] == "add"),
            "removed": sum(1 for x in lines if x["kind"] == "del"),
        })
    return jsonify({"a": label_a, "b": label_b, "same_count": len(paths) - len(files),
                    "files": files})


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
