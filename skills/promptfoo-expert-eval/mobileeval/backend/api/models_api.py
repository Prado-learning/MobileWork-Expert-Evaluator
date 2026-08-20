"""全局评测模型管理：发起评测时选择，provider/model/base_url/api_key 传给 promptfoo。"""
from flask import Blueprint, jsonify, request

from db import get_db, row_to_dict

models_bp = Blueprint("models", __name__)


def _mask_key(key):
    """API key 掩码显示（保留前 4 后 4，避免明文回传前端）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def _serialize(row, with_key=False):
    d = row_to_dict(row)
    if d:
        d["api_key_hint"] = _mask_key(d.get("api_key") or "")
        if not with_key:
            d["api_key"] = ""  # 不把明文 key 返回前端
    return d


@models_bp.get("/models")
def list_models():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM models ORDER BY is_default DESC, id ASC").fetchall()
        return jsonify([_serialize(r) for r in rows])
    finally:
        conn.close()


@models_bp.post("/models")
def create_model():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "模型名称必填"}), 400
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"error": "模型 id 必填"}), 400
    conn = get_db()
    try:
        # 设为默认时，先清掉其他默认
        if data.get("is_default"):
            conn.execute("UPDATE models SET is_default=0 WHERE is_default=1")
        cur = conn.execute(
            """INSERT INTO models (name, provider, model, base_url, api_key, is_default)
               VALUES (?,?,?,?,?,?)""",
            (name, data.get("provider") or "deepseek", model,
             data.get("base_url") or "", data.get("api_key") or "",
             1 if data.get("is_default") else 0),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM models WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(_serialize(row)), 201
    finally:
        conn.close()


@models_bp.put("/models/<int:model_id>")
def update_model(model_id):
    data = request.get_json(force=True) or {}
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            return jsonify({"error": "模型不存在"}), 404
        d = row_to_dict(row)
        # api_key 不传或空串 = 保持不变（避免前端编辑时误清 key）
        api_key = d.get("api_key") or ""
        if data.get("api_key"):
            api_key = data["api_key"]
        if data.get("is_default"):
            conn.execute("UPDATE models SET is_default=0 WHERE is_default=1")
        conn.execute(
            """UPDATE models SET name=?, provider=?, model=?, base_url=?, api_key=?, is_default=?
               WHERE id=?""",
            ((data.get("name") or d["name"]).strip(),
             data.get("provider") or d["provider"],
             (data.get("model") or d["model"]).strip(),
             data.get("base_url", d.get("base_url") or ""),
             api_key,
             1 if data.get("is_default") else d.get("is_default") or 0,
             model_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return jsonify(_serialize(row))
    finally:
        conn.close()


@models_bp.delete("/models/<int:model_id>")
def delete_model(model_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM models WHERE id=?", (model_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "模型不存在"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()
