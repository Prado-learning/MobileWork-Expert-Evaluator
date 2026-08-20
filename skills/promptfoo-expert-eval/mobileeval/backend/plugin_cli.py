"""后端调用 promptfoo-expert-eval 插件脚本的封装（无 Claude SDK 依赖）。

架构：所有 AI 生成能力（分析专家团/生成 case/生成建议）统一由插件脚本 expert_tools.py
产生并直接落库；本模块只做：解析对象 → 拼参数 → subprocess 调用 → 返回 JSON。
评测执行仍由 eval_engine.py 调度 run_eval.py（同样无 Claude SDK 依赖）。
"""
import json
import os
import subprocess
import sys

import config
from db import get_db, row_to_dict, jloads


def _run_expert(subcmd, args, timeout=600):
    """调用插件 expert_tools.py 子命令，返回 stdout JSON 解析结果。"""
    cmd = [sys.executable, config.EXPERT_TOOLS_PY, subcmd]
    for k, v in args.items():
        if v is None or v == "":
            continue
        # --key=value 形式：值以 "-" 开头也不会被 argparse 误解析为选项
        cmd += [f"--{k.replace('_', '-')}={v}"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f"退出码 {proc.returncode}")[:4000])
    return json.loads(proc.stdout)


def _resolve_object(object_id):
    """返回 (workspace_dir, agent_name)，强制使用对象记录的工作区（安全边界）。"""
    conn = get_db()
    try:
        obj = row_to_dict(conn.execute("SELECT * FROM objects WHERE id=?", (object_id,)).fetchone())
    finally:
        conn.close()
    if not obj:
        raise RuntimeError(f"对象 {object_id} 不存在")
    ws = obj["workspace_dir"] or config.DEFAULT_WORKSPACE
    if not config.is_allowed_workspace(ws):
        raise RuntimeError("对象工作区不在允许评测范围内")
    return ws, obj.get("agent_name") or "software-team-lead"


def _db():
    return config.DB_PATH


# --------------------------------------------------------------------------- #
# 工具映射（OpenWork/Claude Code / 网页按钮共用同一插件脚本）
# --------------------------------------------------------------------------- #

def analyze_expert(object_id, name="", description=""):
    """分析专家（团）并创建评测任务（落库）。返回 {task_id, config}。"""
    ws, agent = _resolve_object(object_id)
    return _run_expert("analyze-expert", {
        "workspace": ws, "agent": agent, "name": name, "description": description,
        "object_id": object_id, "db_path": _db()})


def generate_cases(object_id, count=6, mode="replace", task_id=None):
    """生成评测 case（落库）。返回 {generated, task_id, mode}。"""
    ws, agent = _resolve_object(object_id)
    return _run_expert("generate-cases", {
        "workspace": ws, "agent": agent, "count": count, "object_id": object_id,
        "task_id": task_id, "mode": mode, "db_path": _db()})


def review_cases(object_id, action="approve", scope="all", case_ids=None, note=""):
    """批量审核用例。返回 {action, scope, updated, cases}。"""
    return _run_expert("review-cases", {
        "object_id": object_id, "action": action, "scope": scope,
        "case_ids": ",".join(str(int(x)) for x in (case_ids or [])),
        "note": note, "db_path": _db()})


def list_expert_context(object_id):
    ws, agent = _resolve_object(object_id)
    return _run_expert("context", {"workspace": ws, "agent": agent})


def import_expert(name="", source_type="global", source_path=None):
    """从 OpenWork 全局或 workspace 导入专家（团）到隔离工作区并创建对象。"""
    return _run_expert("import-expert", {
        "name": name, "source_type": source_type, "source_path": source_path,
        "db_path": _db()}, timeout=120)


def optimize_expert(object_id, run_id, note="", only_agents=None):
    """基于评测建议迭代优化专家（团）。

    建议由「生成建议」产生（generate_suggestions 会把全部人工评审喂入 AI，
    因此 AI 建议本身已含人工意见）；无建议时 expert_tools 会明确报错提示先生成。
    返回 {version_from, version_to, optimized}。
    """
    return _run_expert("optimize-expert", {
        "object_id": object_id, "run_id": run_id, "note": note,
        "only_agents": ",".join(only_agents) if only_agents else "",
        "db_path": _db()}, timeout=600)


def restore_version(object_id, version):
    """把专家（团）恢复到历史版本 v<N>。返回 {version, restored, current_version, global}。"""
    return _run_expert("restore-version", {
        "object_id": object_id, "version": version, "db_path": _db()}, timeout=120)


def versions_list(object_id):
    from db import get_db, row_to_dict
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, version, path, score, note, created_at FROM expert_versions "
            "WHERE object_id=? ORDER BY version DESC", (object_id,)).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def optimizations_list(object_id):
    from db import get_db, row_to_dict
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM optimizations WHERE object_id=? ORDER BY id DESC",
            (object_id,)).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def generate_suggestions(run_id, review_id=None):
    """解读评测结果生成优化建议并落库。返回 {suggestion_id, content}。

    AI+人工闭环：人工评审（综合评分 + 逐 case 纠错）全部反哺优化建议——
    无论点击单条「基于此评审生成」（传 review_id）还是报告页「自动生成建议」
    （不传 review_id），都会把该 run 的全部人工评审（综合 + 逐 case）喂给 suggest，
    最终经 ai_suggestions 落到迭代优化（optimize-expert）。
    """
    import tempfile
    conn = get_db()
    try:
        run = row_to_dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        if not run:
            raise RuntimeError(f"运行 {run_id} 不存在")
        obj = row_to_dict(conn.execute("SELECT * FROM objects WHERE id=?", (run["object_id"],)).fetchone())
        review = None
        if review_id:
            review = row_to_dict(conn.execute(
                "SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone())
        # 该 run 全部人工评审：综合（case_id 为空）+ 逐 case（case_id 非空）
        all_reviews = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM reviews WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        case_reviews = [r for r in all_reviews if r.get("case_id")]
        overall = next((r for r in all_reviews if not r.get("case_id")), None)
        # 标记已被 AI 采纳（单条点击 → 仅该条；自动生成 → 该 run 全部人工评审）
        if review_id and review:
            used_ids = {review["id"]}
        elif not review_id:
            used_ids = {r["id"] for r in all_reviews}
        else:
            used_ids = set()
        if used_ids:
            conn.execute(
                f"UPDATE reviews SET ai_consumed=1 WHERE id IN ({','.join('?' * len(used_ids))})",
                tuple(used_ids))
            conn.commit()
    finally:
        conn.close()

    run_dir = os.path.join(config.RUNS_DIR, str(run_id))
    summary_path = os.path.join(run_dir, "summary.json")
    if not os.path.exists(summary_path):
        raise RuntimeError("该运行尚无 summary.json（评测未完成或未生成结果）")
    meta = {"object": obj["name"] if obj else "?",
            "status": run.get("status"), "score": run.get("score"),
            "pass_fail_error": f"{run.get('pass_count')}/{run.get('fail_count')}/{run.get('error_count')}"}
    # 组装评审载荷：优先单条 review，否则用综合评审作为整体意见，并附带逐 case 纠错
    review_payload = None
    if review or overall or case_reviews:
        src = review or overall
        review_payload = {}
        if src:
            review_payload = {"id": src["id"], "rating": src.get("rating"),
                              "comments": src.get("comments"),
                              "metrics": jloads(src.get("metrics"))}
        if case_reviews:
            review_payload["case_reviews"] = case_reviews
    args = {"summary": summary_path, "meta": None, "review": None,
            "run_id": run_id, "db_path": _db()}
    with tempfile.TemporaryDirectory() as td:
        meta_path = os.path.join(td, "meta.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
        args["meta"] = meta_path
        if review_payload:
            review_path = os.path.join(td, "review.json")
            with open(review_path, "w", encoding="utf-8") as fh:
                json.dump(review_payload, fh, ensure_ascii=False)
            args["review"] = review_path
        return _run_expert("suggest", args)


TOOL_IMPL = {
    "list_expert_context": lambda a: list_expert_context(int(a["object_id"])),
    "analyze_expert": lambda a: analyze_expert(int(a["object_id"]), a.get("name", ""), a.get("description", "")),
    "generate_cases": lambda a: generate_cases(
        int(a["object_id"]), int(a.get("count") or 6), a.get("mode") or "replace",
        a.get("task_id") and int(a["task_id"])),
    "review_cases": lambda a: review_cases(
        int(a["object_id"]), a.get("action") or "approve", a.get("scope") or "all",
        a.get("case_ids"), a.get("note", "")),
    "generate_suggestions": lambda a: generate_suggestions(int(a["run_id"]), a.get("review_id")),
    "import_expert": lambda a: import_expert(
        a.get("name", ""), a.get("source_type") or "global", a.get("source_path")),
    "optimize_expert": lambda a: optimize_expert(
        int(a["object_id"]), int(a["run_id"]), a.get("note", ""), a.get("only_agents")),
}


def execute_tool(name, args):
    """直接执行某个工具（供 API 快捷按钮/测试使用）。"""
    impl = TOOL_IMPL.get(name)
    if not impl:
        raise RuntimeError(f"未知工具 {name}")
    return impl(args)
