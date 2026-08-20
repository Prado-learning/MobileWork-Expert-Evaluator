"""Case 管理：对象导入后 AI 自动生成 case 集，人工审核（通过/拒绝/编辑）。"""
from flask import Blueprint, jsonify, request

import plugin_cli
from db import get_db, jloads, jdumps, row_to_dict

cases_bp = Blueprint("cases", __name__)


def _serialize(row):
    d = row_to_dict(row)
    if d:
        d["assertions"] = jloads(d.get("assertions"))
    return d


def _get_task_object(object_id, task_id=None):
    conn = get_db()
    try:
        obj = row_to_dict(conn.execute(
            "SELECT * FROM objects WHERE id=?", (object_id,)).fetchone())
        task = None
        if obj:
            if task_id:
                task = row_to_dict(conn.execute(
                    "SELECT * FROM tasks WHERE id=? AND object_id=?", (task_id, object_id)).fetchone())
            if not task:
                task = row_to_dict(conn.execute(
                    "SELECT * FROM tasks WHERE object_id=? ORDER BY id DESC LIMIT 1",
                    (object_id,)).fetchone())
        return obj, task
    finally:
        conn.close()


@cases_bp.get("/objects/<int:object_id>/cases")
def list_cases(object_id):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM cases WHERE object_id=? ORDER BY id", (object_id,)).fetchall()
        result = [_serialize(r) for r in rows]
        approved = sum(1 for c in result if c["status"] == "approved")
        return jsonify({"cases": result, "approved_count": approved})
    finally:
        conn.close()


@cases_bp.post("/objects/<int:object_id>/cases/generate")
def generate_cases(object_id):
    """AI 自动生成 case 集（基于被测专家定义 + 任务）。

    mode=replace（默认）：删除旧的 pending/rejected，保留 approved，再插入新一批 pending；
    mode=append：不清除任何旧用例，直接追加新一批 pending 供审核。
    """
    try:
        body = request.get_json(force=True) or {}
        count = int(body.get("count") or 6)
        task_id = body.get("task_id")
        mode = body.get("mode") or "replace"
    except (TypeError, ValueError):
        count = 6
        task_id = None
        mode = "replace"
    if mode not in ("replace", "append"):
        mode = "replace"
    obj, task = _get_task_object(object_id, task_id)
    if not obj or not task:
        return jsonify({"error": "对象或任务不存在"}), 404
    count = max(1, min(count, 12))
    try:
        # 统一走插件脚本（expert_tools.py generate-cases，直接落库），不重复实现 LLM 逻辑
        plugin_cli.generate_cases(object_id, count=count, mode=mode, task_id=task_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"case 生成失败：{exc}"}), 500

    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM cases WHERE object_id=?", (object_id,)).fetchall()
        return jsonify({"cases": [_serialize(r) for r in rows]}), 201
    finally:
        conn.close()


@cases_bp.put("/cases/<int:case_id>")
def update_case(case_id):
    """人工编辑 case 内容（编辑后回到 pending 待审核）。"""
    data = request.get_json(force=True)
    # 安全：output_dir 必须是相对路径（无盘符/前导分隔符/.. 段），防止评测时穿越写文件
    od = (data.get("output_dir") or "").strip().replace("\\", "/")
    if od and (od.startswith("/") or ":" in od or ".." in od.split("/")):
        return jsonify({"error": "output_dir 必须是 eval-runs/ 下的相对路径，禁止绝对路径或 .. 穿越"}), 400
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            return jsonify({"error": "case 不存在"}), 404
        conn.execute(
            """UPDATE cases SET title=?, type=?, prompt=?, output_dir=?, assertions=?,
               status='pending', review_note='', reviewed_at=NULL WHERE id=?""",
            (data.get("title", ""), data.get("type", "hybrid"), data.get("prompt", ""),
             od, jdumps(data.get("assertions", [])), case_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        return jsonify(_serialize(row))
    finally:
        conn.close()


@cases_bp.post("/cases/<int:case_id>/approve")
def approve_case(case_id):
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            return jsonify({"error": "case 不存在"}), 404
        conn.execute(
            "UPDATE cases SET status='approved', reviewed_at=datetime('now','localtime') WHERE id=?",
            (case_id,))
        conn.commit()
        return jsonify({"ok": True, "status": "approved"})
    finally:
        conn.close()


@cases_bp.post("/cases/<int:case_id>/reject")
def reject_case(case_id):
    data = request.get_json(force=True) or {}
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            return jsonify({"error": "case 不存在"}), 404
        conn.execute(
            "UPDATE cases SET status='rejected', review_note=?, reviewed_at=datetime('now','localtime') WHERE id=?",
            (data.get("note", ""), case_id))
        conn.commit()
        return jsonify({"ok": True, "status": "rejected"})
    finally:
        conn.close()


@cases_bp.delete("/cases/<int:case_id>")
def delete_case(case_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "case 不存在"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()
