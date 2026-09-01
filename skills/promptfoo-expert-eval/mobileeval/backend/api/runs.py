"""评测运行：触发（后台线程）、状态轮询、历史、多运行对比、原始过程数据导出。"""
import io
import os
import zipfile

from flask import Blueprint, jsonify, request, send_file

import config
from db import get_db, jdumps, jloads, row_to_dict
import eval_engine

runs_bp = Blueprint("runs", __name__)


def _serialize(run_row, with_cases=False):
    d = row_to_dict(run_row)
    if d:
        d["session_ids"] = jloads(d.get("session_ids"))
        d["case_ids"] = jloads(d.get("case_ids"))
        d["case_filter"] = jloads(d.get("case_filter"))
        # 附带全局模型名（前端展示用）
        d["model_name"] = ""
        if d.get("model_id"):
            conn = get_db()
            try:
                mrow = conn.execute("SELECT name FROM models WHERE id=?",
                                    (d["model_id"],)).fetchone()
                d["model_name"] = mrow["name"] if mrow else ""
            finally:
                conn.close()
        d["cases"] = []
        if with_cases:
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT * FROM case_results WHERE run_id=? ORDER BY id", (d["id"],)).fetchall()
                d["cases"] = [row_to_dict(r) for r in rows]
                for c in d["cases"]:
                    c["assertions"] = jloads(c.get("assertions"))
                    c["session_ids"] = jloads(c.get("session_ids"))
            finally:
                conn.close()
    return d


def _create_run_for_object(object_id, data):
    """按对象发起评测（记录实验变量：版本/模型/是否专家团/次数）。返回 (run_id, err, code)。

    body 可选：{repeat, model_id, provider, model, concurrency, version, agent_on,
                experiment_id, variant}
    - model_id: 全局评测模型 id（models 表）；解析出 provider/model/base_url 快照到 runs。
    - provider/model: 直接指定（兼容旧参数，优先于 model_id 的 model 字段）。
    """
    try:
        concurrency = int(data.get("concurrency") or 1)
    except (TypeError, ValueError):
        concurrency = 1
    concurrency = max(1, min(concurrency, 100))
    agent_on = 0 if str(data.get("agent_on", "1")) == "0" else 1
    conn = get_db()
    try:
        obj = conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone()
        if not obj:
            return None, "对象不存在", 404
        # 解析评测模型：model_id（全局模型）> provider/model 直接指定 > 对象默认
        provider = data.get("provider") or obj["provider"]
        model = data.get("model") or obj["model"]
        base_url = obj["base_url"] if "base_url" in obj.keys() else ""
        model_id = data.get("model_id")
        if model_id:
            mrow = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
            if not mrow:
                return None, f"评测模型 {model_id} 不存在（models 表）", 404
            provider = mrow["provider"] or provider
            model = mrow["model"] or model
            base_url = mrow["base_url"] or ""
        cur = conn.execute(
            """INSERT INTO runs (task_id, object_id, status, provider, model, base_url, model_id,
               repeat, concurrency, experiment_id, variant, version, agent_on, case_filter)
               VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (obj["id"], "pending", provider, model, base_url, model_id,
             int(data.get("repeat") or 1), concurrency,
             data.get("experiment_id") or None, data.get("variant") or "",
             data.get("version") or f"v{obj['current_version'] or 1}", agent_on,
             jdumps(data["case_filter"]) if data.get("case_filter") else ""),
        )
        conn.commit()
        return cur.lastrowid, None, None
    finally:
        conn.close()


@runs_bp.post("/objects/<int:object_id>/runs")
def create_run(object_id):
    """按对象发起评测（去 task 层，每次运行即一条实验记录）。

    body 可选：{repeat, model, provider, concurrency, version, agent_on, experiment_id, variant}
    - version: 专家版本标签（默认对象当前版本 vN）
    - agent_on: 1=启用专家团（默认）；0=无专家 baseline（opencode 内置通用 agent）
    """
    data = request.get_json(force=True) or {}
    run_id, err, code = _create_run_for_object(object_id, data)
    if err:
        return jsonify({"error": err}), code
    eval_engine.launch_run(run_id)
    return jsonify({"id": run_id, "status": "pending"}), 201


@runs_bp.post("/tasks/<int:task_id>/runs")
def create_run_from_task(task_id):
    """兼容旧端点：从任务发起（转发到所属对象）。新流程请用 /objects/<id>/runs。"""
    conn = get_db()
    try:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    data = request.get_json(force=True) or {}
    run_id, err, code = _create_run_for_object(task["object_id"], data)
    if err:
        return jsonify({"error": err}), code
    eval_engine.launch_run(run_id)
    return jsonify({"id": run_id, "status": "pending"}), 201


@runs_bp.post("/runs/<int:run_id>/rerun-failed")
def rerun_failed(run_id):
    """一键重跑异常/失败 case：从该运行挑出未通过的 case，沿用原实验变量新建一次运行。

    显著省时省费用：不必整批重跑。新运行仅包含原运行中 pass=0 的 case
    （含链路异常与真失败），其余变量（版本/模型/是否专家团）与原运行一致。
    """
    conn = get_db()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            return jsonify({"error": "运行不存在"}), 404
        if run["status"] in ("pending", "running"):
            return jsonify({"error": "该运行仍在进行中，请等待完成后再重跑"}), 400
        failed = conn.execute(
            "SELECT DISTINCT case_id FROM case_results WHERE run_id=? AND pass=0",
            (run_id,)).fetchall()
        case_ids = [r["case_id"] for r in failed if r["case_id"]]
        if not case_ids:
            return jsonify({"error": "该运行没有失败/异常的 case，无需重跑"}), 400
        object_id = run["object_id"]
    finally:
        conn.close()
    data = {
        "model_id": run["model_id"],
        "provider": run["provider"],
        "model": run["model"],
        "repeat": 1,
        "concurrency": run["concurrency"] or 1,
        "version": run["version"],
        "agent_on": run["agent_on"],
        "experiment_id": run["experiment_id"],
        "variant": (run["variant"] + "-rerun") if run["variant"] else "rerun",
        "case_filter": case_ids,
    }
    new_id, err, code = _create_run_for_object(object_id, data)
    if err:
        return jsonify({"error": err}), code
    eval_engine.launch_run(new_id)
    return jsonify({"id": new_id, "status": "pending", "rerun_cases": case_ids}), 201


@runs_bp.get("/runs/<int:run_id>/export")
def export_run(run_id):
    """导出完整过程数据（eval.log + results.json + summary + 每 case 输出/过程 trace）为 zip。

    满足"提交包含原始过程数据的完整评测结果"要求；排除二进制数据库等大文件。
    """
    run_dir = os.path.join(config.RUNS_DIR, str(run_id))
    if not os.path.isdir(run_dir):
        return jsonify({"error": "运行目录不存在"}), 404
    buf = io.BytesIO()
    skip_ext = (".db", ".db-wal", ".db-shm")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(run_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                if fname.endswith(skip_ext):
                    continue
                try:
                    if os.path.getsize(fpath) > 50_000_000:
                        continue
                    zf.write(fpath, os.path.relpath(fpath, run_dir))
                except OSError:
                    continue
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"run-{run_id}-raw.zip")


@runs_bp.get("/runs")
def list_runs():
    object_id = request.args.get("object_id")
    task_id = request.args.get("task_id")
    conn = get_db()
    try:
        sql = "SELECT * FROM runs WHERE 1=1"
        params = []
        if object_id:
            sql += " AND object_id=?"
            params.append(object_id)
        if task_id:
            sql += " AND task_id=?"
            params.append(task_id)
        sql += " ORDER BY id DESC"
        rows = conn.execute(sql, params).fetchall()
        result = [_serialize(r) for r in rows]
        for r in result:
            o = conn.execute("SELECT name, kind FROM objects WHERE id=?", (r["object_id"],)).fetchone()
            r["object_name"] = o["name"] if o else ""
            r["object_kind"] = o["kind"] if o else ""
        return jsonify(result)
    finally:
        conn.close()


@runs_bp.get("/runs/<int:run_id>")
def get_run(run_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return jsonify({"error": "运行不存在"}), 404
        return jsonify(_serialize(row, with_cases=True))
    finally:
        conn.close()


@runs_bp.delete("/runs/<int:run_id>")
def delete_run(run_id):
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "运行不存在"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()


@runs_bp.get("/runs/compare")
def compare_runs():
    """多运行对比：ids=1,2,3。返回各 run 概要（含 case 级明细）+ 按 case 的断言矩阵。"""
    ids = request.args.get("ids", "")
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        return jsonify({"error": "ids 参数必填，如 ?ids=1,2,3"}), 400
    conn = get_db()
    try:
        placeholders = ",".join("?" * len(id_list))
        rows = conn.execute(
            f"SELECT * FROM runs WHERE id IN ({placeholders}) ORDER BY id", id_list).fetchall()
        runs = [_serialize(r, with_cases=True) for r in rows]
        # 断言矩阵：按 case_id 聚合各 run 的 pass
        matrix = {}
        for r in runs:
            for c in r.get("cases", []):
                matrix.setdefault(c["case_id"], {})[r["id"]] = c["pass"]
        return jsonify({"runs": runs, "matrix": matrix})
    finally:
        conn.close()
