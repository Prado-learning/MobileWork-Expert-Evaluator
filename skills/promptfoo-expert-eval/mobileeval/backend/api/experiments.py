"""对照实验：同一组 case 在不同变量（专家版本/基础模型/是否启用专家团）下对比。"""
from flask import Blueprint, jsonify, request

from db import get_db, jloads, row_to_dict

experiments_bp = Blueprint("experiments", __name__)


def _variant_summary(conn, experiment_id):
    """按 variant 聚合实验下各 run 的得分与通过率。"""
    rows = conn.execute(
        """SELECT id, variant, status, score, pass_count, fail_count, error_count,
                  total_cases, model, created_at
           FROM runs WHERE experiment_id=? ORDER BY id""",
        (experiment_id,)).fetchall()
    groups = {}
    for r in rows:
        v = r["variant"] or "(未标注)"
        groups.setdefault(v, []).append(row_to_dict(r))
    variants = []
    for v, runs in groups.items():
        scores = [r["score"] for r in runs if isinstance(r["score"], (int, float))]
        total_cases = sum(r["total_cases"] or 0 for r in runs)
        pass_count = sum(r["pass_count"] or 0 for r in runs)
        variants.append({
            "variant": v,
            "runs": runs,
            "run_count": len(runs),
            "score_avg": round(sum(scores) / len(scores), 4) if scores else None,
            "pass_rate": round(pass_count / total_cases, 4) if total_cases else None,
            "models": sorted({r["model"] for r in runs if r["model"]}),
        })
    return variants


@experiments_bp.post("/experiments")
def create_experiment():
    data = request.get_json(force=True) or {}
    object_id = data.get("object_id")
    name = (data.get("name") or "").strip()
    variable = data.get("variable") or "model"
    if variable not in ("version", "model", "agent_on"):
        variable = "model"
    if not object_id or not name:
        return jsonify({"error": "object_id 与 name 必填"}), 400
    conn = get_db()
    try:
        obj = conn.execute("SELECT id FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            return jsonify({"error": "对象不存在"}), 404
        cur = conn.execute(
            """INSERT INTO experiments (object_id, name, variable, description)
               VALUES (?,?,?,?)""",
            (object_id, name, variable, data.get("description") or ""))
        conn.commit()
        return jsonify({"id": cur.lastrowid, "name": name, "variable": variable}), 201
    finally:
        conn.close()


@experiments_bp.get("/experiments")
def list_experiments():
    object_id = request.args.get("object_id")
    conn = get_db()
    try:
        sql = "SELECT * FROM experiments WHERE 1=1"
        params = []
        if object_id:
            sql += " AND object_id=?"
            params.append(object_id)
        sql += " ORDER BY id DESC"
        rows = conn.execute(sql, params).fetchall()
        return jsonify([row_to_dict(r) for r in rows])
    finally:
        conn.close()


@experiments_bp.get("/experiments/<int:experiment_id>")
def get_experiment(experiment_id):
    conn = get_db()
    try:
        exp = conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        if not exp:
            return jsonify({"error": "实验不存在"}), 404
        result = row_to_dict(exp)
        result["variants"] = _variant_summary(conn, experiment_id)
        return jsonify(result)
    finally:
        conn.close()
