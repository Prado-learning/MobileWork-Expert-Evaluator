"""评测引擎：复用 mobilework-expert-eval-plugin 的 run_eval.py 执行真实评测。

- 从任务定义生成临时 case 文件（固定提示词 + 用户断言 + 人类指标）
- 后台线程 subprocess 调 run_eval.py（--case-file / --all）
- 解析 summary.json / results.json → 写 runs + case_results
- 进度通过 run.status 轮询暴露
"""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

import config
from db import get_db, jloads, jdumps, row_to_dict

THREADS = {}  # run_id -> thread


# --------------------------------------------------------------------------- #
# case 生成（任务 → 临时 case 文件）
# --------------------------------------------------------------------------- #

def build_case_from_task(task, run_id):
    """根据任务定义构造一个 case dict（prompt 模板 + 断言 + 人类指标说明）。

    - autonomy_level=high：开放式任务，不强制确定性断言（由人工评审承接）
    - 用户可在任务中自定义断言（结构化/混合式）
    """
    assertions = jloads(task.get("assertions")) or []
    scenario = task.get("scenario_type", "hybrid")
    prompt = task.get("prompt_template", "").strip()
    if not prompt:
        return None
    case = {
        "id": f"task-{task['id']}",
        "title": task.get("name", "任务 case"),
        "type": scenario,
        "description": "由 MobileEval 任务生成：" + task.get("description", ""),
        "prompt": prompt,
        "output_dir": f"eval-runs/{run_id}/task-{task['id']}",
        "assertions": assertions if assertions else [
            # 开放式任务不强制断言；结构化/混合式给宽松的产物检查
            {"type": "javascript", "value": (
                "const fsp = import('node:fs');\n"
                f"return fsp.then(m => m.default.existsSync({json.dumps('eval-runs/' + run_id + '/task-' + str(task['id']))}));"
            )} if scenario != "open_ended" else {"type": "javascript", "value": "return true;"}
        ],
    }
    return case


def write_case_file(task, run_id, out_dir):
    """把任务生成的 case 写入临时 case 文件，返回文件路径。"""
    case = build_case_from_task(task, run_id)
    if case is None:
        return None
    path = os.path.join(out_dir, f"case-task-{task['id']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([case], fh, ensure_ascii=False, indent=2)
    return path


def _sanitize_case_assertions(assertions):
    """规范化 AI 生成的断言以适配 run_eval.py / promptfoo 运行时：
    - regex: 去除 Python 风格 (?i)（promptfoo 用 JS 引擎，不支持）
    - javascript: require() 在 promptfoo 断言环境不可用，改写为 import('node:fs') 产物检查
    """
    out = []
    for a in assertions or []:
        if not isinstance(a, dict):
            continue
        t = a.get("type")
        v = str(a.get("value") or "")
        if t == "regex" and v.startswith("(?i)"):
            a = dict(a, value=v[4:])
        elif t == "javascript" and "require(" in v:
            a = dict(a, value=(
                "const fsp = import('node:fs');\n"
                "return fsp.then(m => m.default.existsSync({output_dir_abs}));"
            ))
        out.append(a)
    return out


def _sanitize_output_dir(od, fallback):
    """规范化 case 的 output_dir，防止路径穿越/绝对路径逃逸出评测工作区。

    只允许相对路径（无盘符/前导分隔符、无 .. 段）；非法则回退默认值。
    """
    od = (od or "").strip().replace("\\", "/")
    if not od or od.startswith("/") or ":" in od or ".." in od.split("/"):
        return fallback
    return od


def write_cases_file(approved_rows, out_dir):
    """把对象审核通过的 cases（sqlite3.Row）写入临时 case 文件，返回文件路径。

    case schema 对齐 run_eval.py：id/title/type/prompt/output_dir/assertions。
    """
    cases = []
    for row in approved_rows:
        r = dict(row)
        ctype = r.get("type") or "hybrid"
        if ctype == "open_ended":
            ctype = "open-ended"  # run_eval schema 使用连字符
        fallback_od = f"eval-runs/{{run_id}}/case-{r['id']}"
        cases.append({
            "id": r.get("case_id") or f"case-{r['id']}",
            "title": r.get("title") or "",
            "type": ctype,
            "dimension": r.get("dimension") or "",
            "prompt": r.get("prompt") or "",
            "output_dir": _sanitize_output_dir(r.get("output_dir"), fallback_od),
            "assertions": _sanitize_case_assertions(jloads(r.get("assertions"))),
        })
    if not cases:
        return None
    path = os.path.join(out_dir, "cases-approved.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, ensure_ascii=False, indent=2)
    return path


# --------------------------------------------------------------------------- #
# 执行
# --------------------------------------------------------------------------- #

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def launch_run(run_id):
    """启动后台评测线程。"""
    t = threading.Thread(target=_run_worker, args=(run_id,), daemon=True)
    THREADS[run_id] = t
    t.start()
    return t


def _run_worker(run_id):
    conn = get_db()
    try:
        run = row_to_dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        if not run:
            return
        obj = row_to_dict(conn.execute("SELECT * FROM objects WHERE id=?", (run["object_id"],)).fetchone())
        conn.execute("UPDATE runs SET status='running', started_at=? WHERE id=?",
                     (_now(), run_id))
        conn.commit()
    finally:
        conn.close()

    try:
        run_dir = os.path.join(config.RUNS_DIR, str(run_id))
        os.makedirs(run_dir, exist_ok=True)
        log_path = os.path.join(run_dir, "eval.log")

        # 评测模型：优先用 run 关联的全局模型（models 表）的 api_key/base_url；
        # 其次回退环境变量（DEEPSEEK_API_KEY）与对象 base_url。
        api_key = config.resolve_eval_key()
        base_url = run.get("base_url") or obj.get("base_url") or ""
        if run.get("model_id"):
            mconn = get_db()
            try:
                mrow = mconn.execute("SELECT * FROM models WHERE id=?",
                                     (run["model_id"],)).fetchone()
                if mrow:
                    if mrow["api_key"]:
                        api_key = mrow["api_key"]
                    if mrow["base_url"]:
                        base_url = mrow["base_url"]
            finally:
                mconn.close()
        workspace = obj["workspace_dir"] or config.DEFAULT_WORKSPACE
        if not config.is_allowed_workspace(workspace):
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                    ("对象工作区不在允许评测范围内，已拒绝执行评测", _now(), run_id))
                conn.commit()
            finally:
                conn.close()
            return

        # 参数一律用 --key=value 形式拼接，避免可控值以 "-" 开头被 argparse 误解析
        # agent：agent_on=1 用对象专家团；agent_on=0 用 opencode 内置通用 agent（无专家 baseline，量化专家介入价值）
        agent = (obj.get("agent_name") or "software-team-lead") if run.get("agent_on", 1) else "build"
        cmd = [sys.executable, config.RUN_EVAL_PY,
               f"--working-dir={workspace}",
               f"--agent={agent}",
               f"--output-dir={run_dir}",
               f"--repeat={run.get('repeat') or 1}",
               f"--concurrency={run.get('concurrency') or 1}",
               f"--case-timeout-sec={os.environ.get('MOBILEEVAL_CASE_TIMEOUT', '480')}",
               "--verbose"]
        if run.get("provider"):
            cmd += [f"--provider={run['provider']}"]
        if run.get("model"):
            cmd += [f"--model={run['model']}"]
        if base_url:
            cmd += [f"--base-url={base_url}"]
        if api_key:
            cmd += [f"--api-key={api_key}"]

        case_file = None
        # 优先使用该对象已审核通过的 case 集（人工审核工作流）
        cconn = get_db()
        try:
            approved = cconn.execute(
                "SELECT * FROM cases WHERE object_id=? AND status='approved'",
                (run["object_id"],)).fetchall()
        finally:
            cconn.close()
        if not approved:
            # 去 task 层：不再用任务模板兜底，必须先生成并审核 case
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                    ("该对象没有审核通过的 case，请先生成并审核用例（generate-cases + review-cases）",
                     _now(), run_id))
                conn.commit()
            finally:
                conn.close()
            return
        # case_filter（异常/失败重跑）：只跑指定 case 集，跳过其余已审核 case
        filter_ids = jloads(run.get("case_filter"))
        if filter_ids:
            wanted = {str(x) for x in filter_ids}
            approved = [r for r in approved if (r["case_id"] or "") in wanted]
        if not approved:
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                    ("重跑的 case 均不在该对象已审核用例中（可能已被删除/驳回）",
                     _now(), run_id))
                conn.commit()
            finally:
                conn.close()
            return
        # 只跑审核通过的 case 集，不合并插件默认 case 库
        case_file = write_cases_file(approved, run_dir)
        cmd += ["--case-file", case_file, "--case-file-only"]
        case_ids = [r["case_id"] for r in approved]

        # 记录本次评测的总 case 数（用于前端展示"已完成/总数"进度）+ 本次跑的 case 集
        total_cases = len(approved)
        conn = get_db()
        try:
            conn.execute("UPDATE runs SET total_cases=?, case_ids=? WHERE id=?",
                         (total_cases, jdumps(case_ids), run_id))
            conn.commit()
        finally:
            conn.close()

        # 后台进程 + 轮询 progress.json：评测过程中实时更新 runs 的通过/失败计数
        progress_path = os.path.join(run_dir, "progress.json")
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                    encoding="utf-8", errors="replace")
            while proc.poll() is None:
                _apply_progress(run_id, progress_path)
                time.sleep(0.5)
            _apply_progress(run_id, progress_path)
        rc = proc.returncode

        summary = _load_summary(run_dir)
        _persist_results(run_id, run_dir, summary, rc)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        conn = get_db()
        try:
            conn.execute("UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                         (str(exc)[:1000], _now(), run_id))
            conn.commit()
        finally:
            conn.close()


def _load_summary(run_dir):
    p = os.path.join(run_dir, "summary.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _apply_progress(run_id, progress_path):
    """读取 run_eval.py 实时写出的 progress.json，更新 runs 的通过/失败/总数计数。

    前端轮询 /api/runs 时即可看到"已完成 x / 总数 y"的实时进度。
    """
    if not os.path.exists(progress_path):
        return
    try:
        with open(progress_path, encoding="utf-8") as fh:
            p = json.load(fh)
    except Exception:  # noqa: BLE001
        return
    conn = get_db()
    try:
        conn.execute(
            """UPDATE runs SET pass_count=?, fail_count=?, error_count=?, total_cases=?
               WHERE id=?""",
            (p.get("passed", 0), p.get("failed", 0), p.get("errors", 0),
             p.get("total", 0), run_id))
        conn.commit()
    finally:
        conn.close()


def _persist_results(run_id, run_dir, summary, rc):
    conn = get_db()
    try:
        if summary is None:
            conn.execute(
                "UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?",
                (f"评测未生成 summary.json（退出码 {rc}），详见 eval.log", _now(), run_id))
            conn.commit()
            return
        cases = summary.get("cases", [])
        stats = summary.get("stats", {})
        total = len(cases)
        # 互斥三分类（passed+failed+errors == total）：
        #   passed = 最终通过（error 仅作链路备注）；failed = 未通过且无链路异常（真失败）；
        #   errors = 链路异常且未通过（不重复计入 failed，避免重叠计数）。
        passed = sum(1 for c in cases if c.get("pass") is True)
        failed = sum(1 for c in cases if c.get("pass") is False and not c.get("error"))
        errors = sum(1 for c in cases if c.get("pass") is not True and c.get("error"))
        scores = [c.get("score") for c in cases if isinstance(c.get("score"), (int, float))]
        score = sum(scores) / len(scores) if scores else (1.0 if passed == total and total else 0.0)
        session_ids = []
        for c in cases:
            sids = c.get("session_ids") or []
            session_ids.extend(sids)
            conn.execute(
                """INSERT INTO case_results
                   (run_id, case_id, case_title, case_type, pass, score,
                    output_length, error, output_preview, assertions, session_ids, token_count,
                    process_metrics, repeats, needs_review)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, c.get("id", ""), c.get("title", ""), c.get("type", ""),
                 1 if c.get("pass") is True else 0,
                 c.get("score"), c.get("output_length", 0),
                 c.get("error") or "", c.get("output_preview") or "",
                 jdumps(c.get("assertions") or []), jdumps(sids),
                 c.get("token_count") or 0,
                 jdumps(c.get("process_metrics") or {}),
                 jdumps(c.get("repeats") or []),
                 c.get("needs_review") or 0))
        status = "passed" if errors == 0 and failed == 0 else ("failed" if failed or errors else "passed")
        # 耗时：优先用各 case 的 elapsed_sec（真实墙钟耗时，单位秒），兜底 latency_ms/duration_ms
        dur_ms = int(sum(
            (c.get("elapsed_sec") or 0) * 1000 for c in cases
        ) or sum(c.get("latency_ms") or c.get("duration_ms") or 0 for c in cases))
        # 成本：聚合各 case 的 cost（若都存在则求和）
        costs = [c.get("cost") for c in cases if isinstance(c.get("cost"), (int, float))]
        cost_total = round(sum(costs), 8) if costs else None
        # token：聚合各 case 的 token_count
        token_total = sum(c.get("token_count") or 0 for c in cases) or None
        conn.execute(
            """UPDATE runs SET status=?, score=?, pass_count=?, fail_count=?, error_count=?,
               total_assertions=?, output_length=?, duration_ms=?, cost=?, token_count=?,
               total_cases=?,
               results_path=?, log_path=?, session_ids=?, finished_at=? WHERE id=?""",
            (status, score, passed, failed, errors, stats.get("total", 0),
             sum(c.get("output_length", 0) for c in cases),
             dur_ms, cost_total, token_total, total,
             os.path.join(run_dir, "summary.json"),
             os.path.join(run_dir, "eval.log"),
             jdumps(list(dict.fromkeys(session_ids))), _now(), run_id))
        conn.commit()
    finally:
        conn.close()


def get_run_status(run_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
