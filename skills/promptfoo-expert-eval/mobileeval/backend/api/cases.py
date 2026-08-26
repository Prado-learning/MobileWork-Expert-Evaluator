"""Case 管理：对象导入后 AI 自动生成 case 集，人工审核（通过/拒绝/编辑）。"""
import os

from flask import Blueprint, jsonify, request

import plugin_cli
from db import get_db, jloads, jdumps, row_to_dict, ensure_default_task

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
    if not obj:
        return jsonify({"error": "对象不存在"}), 404
    # 去 task 层后，导入/分析流程不再创建 task；但生成 case 需要 task_id 落库。
    # 若 object 下没有 task，自动确保一条默认 task（幂等），避免「对象或任务不存在」404。
    resolved_task_id = task_id or (task["id"] if task else None)
    if not resolved_task_id:
        resolved_task_id = ensure_default_task(object_id)
    task_id = resolved_task_id
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


@cases_bp.post("/objects/<int:object_id>/cases/import")
def import_cases(object_id):
    """导入 agent 已转换好的标准 case 列表（pending，走审核）。

    body: {"cases": [{"title","type","prompt","output_dir","assertions",...}], "mode": "append|replace"}
    转换由 agent 完成，本接口只校验并落库。
    """
    body = request.get_json(force=True) or {}
    cases = body.get("cases")
    if not isinstance(cases, list) or not cases:
        return jsonify({"error": "cases 必须是非空数组（已转换的标准 case 列表）"}), 400
    mode = body.get("mode") or "append"
    if mode not in ("append", "replace"):
        mode = "append"
    try:
        import json as _json
        result = plugin_cli._run_expert(
            "import-cases",
            {"object-id": object_id, "cases": _json.dumps(cases, ensure_ascii=False), "mode": mode},
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"用例导入失败：{exc}"}), 500
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM cases WHERE object_id=?", (object_id,)).fetchall()
        return jsonify({"imported": result.get("imported", 0), "cases": [_serialize(r) for r in rows]}), 201
    finally:
        conn.close()


@cases_bp.post("/objects/<int:object_id>/cases/upload")
def upload_cases_file(object_id):
    """上传用例文件：保存到暂存区 + 写入 pending_imports（通知 AI 有待转换任务）。

    body: {"content": "文件文本内容", "filename": "原文件名"}
    返回 {saved_path, filename, size, pending_id}。
    """
    body = request.get_json(force=True) or {}
    content = body.get("content") or ""
    filename = (body.get("filename") or "case-upload.txt").strip()
    if not content.strip():
        return jsonify({"error": "文件内容为空"}), 400
    try:
        import config as _cfg
        upload_dir = os.path.join(_cfg.DATA_DIR, "uploads", str(object_id))
        os.makedirs(upload_dir, exist_ok=True)
        safe_name = os.path.basename(filename) or "case-upload.txt"
        path = os.path.join(upload_dir, safe_name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        # 写入待转换任务（agent 轮询/查询的"通知"信号）
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO pending_imports (object_id, filename, saved_path, status) VALUES (?,?,?,'pending')",
                (object_id, safe_name, path))
            conn.commit()
            pending_id = cur.lastrowid
        finally:
            conn.close()
        return jsonify({"ok": True, "saved_path": path, "filename": safe_name,
                        "size": len(content), "pending_id": pending_id}), 201
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"文件保存失败：{exc}"}), 500


@cases_bp.get("/objects/<int:object_id>/cases/pending-imports")
def list_pending_imports(object_id):
    """列出某对象待转换的用例文件（agent 据此感知"有文件待转换"）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, filename, saved_path, status, note, created_at FROM pending_imports "
            "WHERE object_id=? ORDER BY id DESC", (object_id,)).fetchall()
        return jsonify([row_to_dict(r) for r in rows])
    finally:
        conn.close()


@cases_bp.post("/cases/pending-imports/<int:pending_id>/status")
def update_pending_import_status(pending_id):
    """更新待转换任务状态（agent 转换完成后标记 done/failed）。"""
    data = request.get_json(force=True) or {}
    status = data.get("status") or "done"
    note = data.get("note") or ""
    if status not in ("pending", "converting", "done", "failed"):
        return jsonify({"error": f"非法状态：{status}"}), 400
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM pending_imports WHERE id=?", (pending_id,)).fetchone():
            return jsonify({"error": "任务不存在"}), 404
        if status == "done":
            conn.execute(
                "UPDATE pending_imports SET status=?, note=?, finished_at=datetime('now','localtime') WHERE id=?",
                (status, note, pending_id))
        else:
            conn.execute("UPDATE pending_imports SET status=?, note=? WHERE id=?", (status, note, pending_id))
        conn.commit()
        return jsonify({"ok": True, "id": pending_id, "status": status})
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
