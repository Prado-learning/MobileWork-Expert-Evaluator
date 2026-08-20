"""测试任务 CRUD —— 挂在专家/专家团（object）下。任务 = 场景化评测定义（提示词模板 + 断言 + 人类自定义指标）。"""
from flask import Blueprint, jsonify, request

from db import get_db, jloads, jdumps, row_to_dict

tasks_bp = Blueprint("tasks", __name__)


def _serialize(row):
    d = row_to_dict(row)
    if d:
        d["assertions"] = jloads(d.get("assertions"))
        d["human_metrics"] = jloads(d.get("human_metrics"))
    return d


@tasks_bp.get("/objects/<int:object_id>/tasks")
def list_tasks(object_id):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE object_id=? ORDER BY updated_at DESC", (object_id,)).fetchall()
        result = [_serialize(r) for r in rows]
        for t in result:
            t["run_count"] = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE task_id=?", (t["id"],)).fetchone()[0]
            t["approved_case_count"] = conn.execute(
                "SELECT COUNT(*) FROM cases WHERE object_id=? AND status='approved'",
                (object_id,)).fetchone()[0]
        return jsonify(result)
    finally:
        conn.close()


@tasks_bp.post("/objects/<int:object_id>/tasks")
def create_task(object_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name 必填"}), 400
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM objects WHERE id=?", (object_id,)).fetchone():
            return jsonify({"error": "对象不存在"}), 404
        cur = conn.execute(
            """INSERT INTO tasks (object_id, name, description, scenario_type, autonomy_level,
               prompt_template, assertions, human_metrics)
               VALUES (?,?,?,?,?,?,?,?)""",
            (object_id, name,
             data.get("description", ""),
             data.get("scenario_type", "hybrid"),
             data.get("autonomy_level", "low"),
             data.get("prompt_template", ""),
             jdumps(data.get("assertions", [])),
             jdumps(data.get("human_metrics", []))),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(_serialize(row)), 201
    finally:
        conn.close()


@tasks_bp.get("/tasks/<int:task_id>")
def get_task(task_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(_serialize(row))
    finally:
        conn.close()


@tasks_bp.put("/tasks/<int:task_id>")
def update_task(task_id):
    data = request.get_json(force=True)
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return jsonify({"error": "任务不存在"}), 404
        conn.execute(
            """UPDATE tasks SET name=?, description=?, scenario_type=?, autonomy_level=?,
               prompt_template=?, assertions=?, human_metrics=?, updated_at=datetime('now','localtime')
               WHERE id=?""",
            (data.get("name", ""), data.get("description", ""),
             data.get("scenario_type", "hybrid"), data.get("autonomy_level", "low"),
             data.get("prompt_template", ""),
             jdumps(data.get("assertions", [])), jdumps(data.get("human_metrics", [])),
             task_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return jsonify(_serialize(row))
    finally:
        conn.close()


@tasks_bp.delete("/tasks/<int:task_id>")
def delete_task(task_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()
