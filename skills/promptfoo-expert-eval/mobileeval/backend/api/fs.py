"""本地目录浏览 API：评测工作区等路径选择用（本地单机应用，后端与前端同机）。

安全：默认只允许浏览"允许评测工作区集合"（默认工作区 + 已登记对象工作区）内部的目录，
防止外界用户遍历服务器任意目录结构；本地管理员设 MOBILEEVAL_FS_BROWSE_ALL=1 可放开全盘浏览。
"""
import os
import string

from flask import Blueprint, jsonify, request

import config

fs_bp = Blueprint("fs", __name__)


@fs_bp.get("/fs/browse")
def browse():
    """列出指定目录下的子目录。path 为空时返回可用盘符（Windows）或根目录。"""
    path = (request.args.get("path") or "").strip()
    if not path:
        if not config.fs_browse_allowed():
            # 受限模式：根直接列出允许评测工作区集合，避免泄露服务器全盘目录
            dirs = sorted(set(config.allowed_workspace_dirs()))
            return jsonify({"path": "", "parent": None, "dirs": dirs, "is_root": True})
        if os.name == "nt":
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]
            return jsonify({"path": "", "parent": None, "dirs": drives, "is_root": True})
        root = "/"
        dirs = sorted(d for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d)) and not d.startswith("."))
        return jsonify({"path": root, "parent": None, "dirs": dirs, "is_root": True})

    # 安全边界：非管理员放开模式下，只允许浏览允许评测工作区集合内的目录
    if not config.fs_browse_allowed() and not config.is_allowed_workspace(path):
        return jsonify({"error": "路径不在允许浏览范围内"}), 403

    p = os.path.abspath(path)
    if not os.path.isdir(p):
        return jsonify({"error": "目录不存在"}), 400
    try:
        dirs = sorted(d for d in os.listdir(p)
                      if os.path.isdir(os.path.join(p, d))
                      and not d.startswith((".", "$")))
    except PermissionError:
        dirs = []
    parent = None
    dp = os.path.dirname(p)
    if dp and dp != p:
        parent = dp
    return jsonify({"path": p, "parent": parent, "dirs": dirs, "is_root": False})
