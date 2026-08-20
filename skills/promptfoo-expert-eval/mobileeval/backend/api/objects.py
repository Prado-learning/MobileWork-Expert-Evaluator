"""被测对象（专家/专家团）CRUD —— 顶层实体。区分专家（single）与专家团（team）。

安全：workspace_dir 必须落在允许评测工作区集合内（config.allowed_workspace_dirs），
防止外界用户登记任意目录（评测时被测 agent 会获得该目录的读写权限）。
"""
import os

from flask import Blueprint, jsonify, request

import config
import expert_upload
from db import get_db, row_to_dict

objects_bp = Blueprint("objects", __name__)


def _check_workspace(ws):
    """校验工作区路径；为空则允许（评测回退默认工作区）。"""
    ws = (ws or "").strip()
    if ws and not config.is_allowed_workspace(ws):
        raise ValueError("workspace_dir 不在允许评测工作区范围内（仅支持 eval-data/ 或 workspaces/ 下的目录）")
    return ws


def _serialize(row):
    return row_to_dict(row)


def _with_counts(conn, o):
    o["task_count"] = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE object_id=?", (o["id"],)).fetchone()[0]
    o["run_count"] = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE object_id=?", (o["id"],)).fetchone()[0]
    o["approved_case_count"] = conn.execute(
        "SELECT COUNT(*) FROM cases WHERE object_id=? AND status='approved'", (o["id"],)).fetchone()[0]
    o["last_run"] = row_to_dict(conn.execute(
        """SELECT id, status, score, created_at FROM runs
           WHERE object_id=? ORDER BY id DESC LIMIT 1""", (o["id"],)).fetchone())
    return o


@objects_bp.get("/objects")
def list_objects():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM objects ORDER BY created_at DESC").fetchall()
        return jsonify([_with_counts(conn, _serialize(r)) for r in rows])
    finally:
        conn.close()


@objects_bp.post("/objects")
def create_object():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name 必填"}), 400
    try:
        ws = _check_workspace(data.get("workspace_dir", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 403
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO objects (name, kind, agent_name, description,
               workspace_dir, provider, model, source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, data.get("kind", "team"), data.get("agent_name", "software-team-lead"),
             data.get("description", ""), ws,
             data.get("provider", "deepseek"), data.get("model", "deepseek-v4-flash"),
             data.get("source", "local")),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM objects WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(_serialize(row)), 201
    finally:
        conn.close()


@objects_bp.get("/objects/<int:object_id>")
def get_object(object_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if not row:
            return jsonify({"error": "对象不存在"}), 404
        return jsonify(_with_counts(conn, _serialize(row)))
    finally:
        conn.close()


@objects_bp.get("/objects/<int:object_id>/agents")
def get_object_agents(object_id):
    """解析该对象评测工作区的专家团成员信息（agents/*.md 或 opencode.jsonc）。"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if not row:
            return jsonify({"error": "对象不存在"}), 404
    finally:
        conn.close()
    obj = _serialize(row)
    ws = obj.get("workspace_dir") or ""
    if not ws or not os.path.isdir(ws):
        return jsonify({"agent_name": obj.get("agent_name"), "workspace_dir": ws,
                        "agents": [], "note": "未配置工作区，无法读取专家团信息"})
    try:
        agents = expert_upload.list_agents(ws)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"读取专家团信息失败：{exc}"}), 500
    return jsonify({"agent_name": obj.get("agent_name"), "workspace_dir": ws,
                    "agents": agents})


@objects_bp.put("/objects/<int:object_id>")
def update_object(object_id):
    data = request.get_json(force=True)
    try:
        ws = _check_workspace(data.get("workspace_dir", ""))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 403
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM objects WHERE id=?", (object_id,)).fetchone():
            return jsonify({"error": "对象不存在"}), 404
        conn.execute(
            """UPDATE objects SET name=?, kind=?, agent_name=?, description=?,
               workspace_dir=?, provider=?, model=?, base_url=? WHERE id=?""",
            (data.get("name", ""), data.get("kind", "team"), data.get("agent_name", "software-team-lead"),
             data.get("description", ""), ws,
             data.get("provider", "deepseek"), data.get("model", "deepseek-v4-flash"),
             data.get("base_url", ""), object_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        return jsonify(_serialize(row))
    finally:
        conn.close()


@objects_bp.delete("/objects/<int:object_id>")
def delete_object(object_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM objects WHERE id=?", (object_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "对象不存在"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()
