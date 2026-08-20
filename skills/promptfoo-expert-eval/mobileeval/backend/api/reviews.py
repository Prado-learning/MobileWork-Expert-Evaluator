"""人工评审 CRUD：对话框备注 + 自定义指标逐项打分；AI 可读取。"""
from flask import Blueprint, jsonify, request

from db import get_db, jdumps, jloads, row_to_dict

reviews_bp = Blueprint("reviews", __name__)


@reviews_bp.get("/runs/<int:run_id>/reviews")
def list_reviews(run_id):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        result = [row_to_dict(r) for r in rows]
        for r in result:
            r["metrics"] = jloads(r.get("metrics"))
        return jsonify(result)
    finally:
        conn.close()


@reviews_bp.post("/runs/<int:run_id>/reviews")
def create_review(run_id):
    data = request.get_json(force=True)
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone():
            return jsonify({"error": "运行不存在"}), 404
        cur = conn.execute(
            """INSERT INTO reviews (run_id, rating, comments, metrics, ai_consumed, case_id, verdict)
               VALUES (?,?,?,?,0,?,?)""",
            (run_id, int(data.get("rating") or 0),
             data.get("comments", ""), jdumps(data.get("metrics", [])),
             data.get("case_id", ""), data.get("verdict", "")),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reviews WHERE id=?", (cur.lastrowid,)).fetchone()
        d = row_to_dict(row)
        d["metrics"] = jloads(d.get("metrics"))
        return jsonify(d), 201
    finally:
        conn.close()


@reviews_bp.put("/reviews/<int:review_id>")
def update_review(review_id):
    data = request.get_json(force=True)
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM reviews WHERE id=?", (review_id,)).fetchone():
            return jsonify({"error": "评审不存在"}), 404
        conn.execute(
            "UPDATE reviews SET rating=?, comments=?, metrics=? WHERE id=?",
            (int(data.get("rating") or 0), data.get("comments", ""),
             jdumps(data.get("metrics", [])), review_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        d = row_to_dict(row)
        d["metrics"] = jloads(d.get("metrics"))
        return jsonify(d)
    finally:
        conn.close()


@reviews_bp.delete("/reviews/<int:review_id>")
def delete_review(review_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM reviews WHERE id=?", (review_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "评审不存在"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()
