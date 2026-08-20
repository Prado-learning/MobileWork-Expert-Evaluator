"""专家包上传：远程用户通过浏览器上传专家/专家团文件夹（或 zip），服务器重建评测工作区。

两种模式：
- 文件夹模式（推荐）：前端用 <input type="file" webkitdirectory> 选择文件夹，
  FormData 以 `files` 字段携带全部文件（filename=相对路径），后端重建目录结构。
- zip 模式（兼容）：单个 `file` 字段上传 zip，后端解压。
"""
import os

from flask import Blueprint, jsonify, request

import config
import expert_upload
from db import get_db, row_to_dict

uploads_bp = Blueprint("uploads", __name__)


@uploads_bp.post("/objects/upload")
def upload_object():
    """multipart/form-data：files[]（文件夹模式）或 file（zip 模式）+
    name、kind、provider、model、description。

    服务器端重建/解压 → 定位 .opencode 评测工作区 → 非交互权限适配 → 创建对象（source=uploaded）。
    """
    uploads_root = os.path.join(config.DATA_DIR, "uploads")
    try:
        files = request.files.getlist("files")
        if files:
            # 文件夹模式：多文件 + 相对路径
            name = (request.form.get("name") or "").strip() or "上传的专家包"
            workspace, agent_name = expert_upload.store_upload_files(files, uploads_root)
        elif "file" in request.files:
            # zip 模式（兼容）
            f = request.files["file"]
            name = (request.form.get("name") or "").strip() or os.path.splitext(f.filename or "专家包")[0]
            if not f.filename or not f.filename.lower().endswith(".zip"):
                return jsonify({"error": "请上传 .zip 格式的专家包"}), 400
            workspace, agent_name = expert_upload.store_upload(f, uploads_root)
        else:
            return jsonify({"error": "缺少 files（文件夹）或 file（zip）字段"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"上传处理失败：{exc}"}), 500

    agent_name = agent_name or "software-team-lead"
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO objects (name, kind, agent_name, description,
               workspace_dir, provider, model, source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, request.form.get("kind", "team"), agent_name,
             request.form.get("description", ""), workspace,
             request.form.get("provider", "deepseek"),
             request.form.get("model", "deepseek-v4-flash"), "uploaded"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM objects WHERE id=?", (cur.lastrowid,)).fetchone()
        obj = row_to_dict(row)
        obj["agent_name"] = agent_name
        return jsonify(obj), 201
    finally:
        conn.close()
