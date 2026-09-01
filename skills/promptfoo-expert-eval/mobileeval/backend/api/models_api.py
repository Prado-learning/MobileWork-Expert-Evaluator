"""全局评测模型管理：发起评测时选择，provider/model/base_url/api_key 传给 promptfoo。"""
import json
import time
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from db import get_db, row_to_dict

models_bp = Blueprint("models", __name__)

# provider 缺省端点（base_url 留空时使用）
_DEFAULT_BASE = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "openrouter": "https://openrouter.ai/api/v1",
}


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


def _probe_model(provider, model, base_url, api_key, timeout=20):
    """向模型端点发一次最小请求验证连通性/凭据。返回 (ok, detail, latency_ms)。

    - anthropic：POST <base>/v1/messages（x-api-key 认证）
    - 其余（deepseek/openai/openrouter/自定义）：OpenAI 兼容 POST <base>/chat/completions
    """
    if not api_key:
        return False, "未配置 API Key，无法测试", 0
    base = (base_url or _DEFAULT_BASE.get(provider, "")).rstrip("/")
    if not base:
        return False, "该 provider 无默认端点，请先填写 Base URL", 0
    payload = {"model": model, "max_tokens": 8,
               "messages": [{"role": "user", "content": "连通性测试，请回复 ok"}]}
    start = time.time()
    try:
        if provider == "anthropic":
            url = base if base.endswith("/messages") else base + "/v1/messages"
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-api-key": api_key,
                         "anthropic-version": "2023-06-01"}, method="POST")
        else:
            url = base if base.endswith("/chat/completions") else base + "/chat/completions"
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {api_key}"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
        latency = int((time.time() - start) * 1000)
        reply = ""
        if provider == "anthropic":
            reply = "".join(b.get("text", "") for b in body.get("content", [])
                            if isinstance(b, dict))
        else:
            reply = ((body.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return True, (reply or "连接成功")[:120], latency
    except urllib.error.HTTPError as e:
        latency = int((time.time() - start) * 1000)
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        return False, f"HTTP {e.code}：{detail or e.reason}", latency
    except urllib.error.URLError as e:
        return False, f"网络错误：{e.reason}", int((time.time() - start) * 1000)
    except Exception as e:  # noqa: BLE001
        return False, f"请求异常：{e}", int((time.time() - start) * 1000)


@models_bp.post("/models/<int:model_id>/test")
def test_model(model_id):
    """测试模型连通性：用已保存凭据发一次最小请求，验证端点/Key/模型 id 可用。"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"error": "模型不存在"}), 404
    ok, detail, latency = _probe_model(
        row["provider"], row["model"], row["base_url"], row["api_key"])
    return jsonify({"ok": ok, "detail": detail, "latency_ms": latency,
                    "provider": row["provider"], "model": row["model"]})


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
            """INSERT INTO models (name, provider, model, base_url, api_key, is_default,
               price_input, price_output)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, data.get("provider") or "deepseek", model,
             data.get("base_url") or "", data.get("api_key") or "",
             1 if data.get("is_default") else 0,
             float(data.get("price_input") or 0), float(data.get("price_output") or 0)),
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
            """UPDATE models SET name=?, provider=?, model=?, base_url=?, api_key=?, is_default=?,
               price_input=?, price_output=?
               WHERE id=?""",
            ((data.get("name") or d["name"]).strip(),
             data.get("provider") or d["provider"],
             (data.get("model") or d["model"]).strip(),
             data.get("base_url", d.get("base_url") or ""),
             api_key,
             1 if data.get("is_default") else d.get("is_default") or 0,
             float(data.get("price_input", d.get("price_input") or 0)),
             float(data.get("price_output", d.get("price_output") or 0)),
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
