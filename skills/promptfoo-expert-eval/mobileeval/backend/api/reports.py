"""运行报告：聚合 case 结果、断言明细、双视角指标（技术 + 业务）。"""
import glob
import json
import os
import sqlite3

from flask import Blueprint, jsonify

from db import get_db, jloads, row_to_dict

reports_bp = Blueprint("reports", __name__)


def _fmt_tokens(n):
    """Token 数量格式化为 K/M 单位（>1000 用 K，>1000000 用 M）。"""
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _tech_metrics(run, cases):
    """底层算法/技术性能指标（自动计算）。"""
    total = len(cases)
    passed = sum(1 for c in cases if c["pass"])
    total_assertions = sum(len(c["assertions"]) for c in cases)
    passed_assertions = sum(
        sum(1 for a in c["assertions"] if a.get("pass")) for c in cases)
    duration_min = round((run.get("duration_ms") or 0) / 60000, 2)
    return [
        {"key": "pass_rate", "name": "case 通过率", "value": round(passed / total, 4) if total else 0,
         "unit": "%", "display": f"{passed}/{total}"},
        {"key": "assertion_pass_rate", "name": "断言通过率",
         "value": round(passed_assertions / total_assertions, 4) if total_assertions else 0,
         "unit": "%", "display": f"{passed_assertions}/{total_assertions}"},
        {"key": "artifact_integrity", "name": "产物完整性",
         "value": round(sum(1 for c in cases if c["output_length"] > 0) / total, 4) if total else 0,
         "unit": "%", "display": f"{sum(1 for c in cases if c['output_length'] > 0)}/{total}"},
        {"key": "session_count", "name": "会话数", "value": len(run.get("session_ids") or []),
         "unit": "个", "display": str(len(run.get("session_ids") or []))},
        {"key": "duration_ms", "name": "运行耗时", "value": run.get("duration_ms") or 0,
         "unit": "min", "display": f"{duration_min} 分钟"},
        {"key": "token_count", "name": "Token 消耗", "value": run.get("token_count") or 0,
         "unit": "tokens", "display": _fmt_tokens(run.get("token_count") or 0)},
    ]


def _business_metrics(run, cases, reviews):
    """用户可感知业务指标：LLM 裁判自动打分（llm-rubric）+ 人工评审。

    业务视角（产品可用性/相关性/可交付）由 LLM 裁判自动打分，无需人工；
    人工评审与自定义指标作为补充。
    """
    result = []
    # 1) 自动化业务指标：聚合 llm-rubric 断言的 metric 分（LLM-as-judge）
    rubric_by_metric = {}
    for c in cases:
        for a in (c.get("assertions") or []):
            if a.get("type") in ("llm-rubric", "model-graded", "rubric"):
                s = a.get("score")
                if isinstance(s, (int, float)):
                    m = a.get("metric") or "综合体验"
                    rubric_by_metric.setdefault(m, []).append(s)
    for m, scores in rubric_by_metric.items():
        avg = round(sum(scores) / len(scores), 3)
        result.append({"key": f"rubric_{m}", "name": m, "value": avg, "unit": "/1",
                       "display": f"{round(avg * 100)}%·{len(scores)} 次"})
    # 2) 人工综合评分（可空）
    human = {"key": "human_rating", "name": "人工综合评分", "value": None, "unit": "/5",
             "display": "未评审"}
    if reviews:
        ratings = [r["rating"] for r in reviews if r["rating"]]
        avg = round(sum(ratings) / len(ratings), 2) if ratings else None
        if avg is not None:
            human = {"key": "human_rating", "name": "人工综合评分", "value": avg,
                     "unit": "/5", "display": f"{avg}/5（{len(ratings)} 次）"}
    result.append(human)
    # 3) 人类自定义指标（对象 human_metrics，去 task 层后由对象承接）逐项聚合
    obj = None
    conn = get_db()
    try:
        obj = conn.execute("SELECT * FROM objects WHERE id=?", (run["object_id"],)).fetchone()
    finally:
        conn.close()
    if obj:
        for m in jloads(obj["human_metrics"] or "[]"):
            result.append({"key": m.get("name", "自定义指标"),
                           "name": m.get("name", "自定义指标"),
                           "value": None, "unit": m.get("criteria", ""),
                           "display": "待人工评审"})
    return result


def _module_metrics(cases):
    """模块级效能指标：从过程探针（process_metrics）与模块级断言聚合。

    拆解各环节真实效能，而非只看最终输出：
    - 工具调用准确率（tool_accuracy）：工具调用成功占比
    - 多Agent协同（collaboration）：委派次数 + delegation 断言通过率
    - 知识匹配精准度（kb_match）：kb-hit 断言通过率
    - 输出质量（output_quality）：llm-rubric 断言平均分
    """
    tool_total = tool_success = tool_error = 0
    deleg_pass = deleg_total = 0
    kb_pass = kb_total = 0
    rubric_scores = []
    delegation_count = 0
    for c in cases:
        pm = c.get("process_metrics") or {}
        for st in (pm.get("tool_summary") or {}).values():
            tool_total += st.get("total", 0) or 0
            tool_success += st.get("success", 0) or 0
            tool_error += st.get("error", 0) or 0
        delegation_count += len(pm.get("delegation") or [])
        for a in (c.get("assertions") or []):
            at = a.get("type")
            if at == "delegation":
                deleg_total += 1
                if a.get("pass"):
                    deleg_pass += 1
            elif at == "kb-hit":
                kb_total += 1
                if a.get("pass"):
                    kb_pass += 1
            elif at in ("llm-rubric", "model-graded", "rubric"):
                s = a.get("score")
                if isinstance(s, (int, float)):
                    rubric_scores.append(s)
    tool_acc = round(tool_success / tool_total, 4) if tool_total else None
    deleg_rate = round(deleg_pass / deleg_total, 4) if deleg_total else None
    kb_rate = round(kb_pass / kb_total, 4) if kb_total else None
    out_quality = round(sum(rubric_scores) / len(rubric_scores), 2) if rubric_scores else None
    return [
        {"key": "tool_accuracy", "name": "工具调用准确率",
         "value": tool_acc, "unit": "%",
         "display": f"{round(tool_acc * 100, 1)}%（{tool_success}/{tool_total}）" if tool_acc is not None else "—"},
        {"key": "collaboration", "name": "多Agent协同",
         "value": deleg_rate, "unit": "%",
         "display": (f"{round(deleg_rate * 100, 1)}%（{deleg_pass}/{deleg_total} 断言，"
                     f"{delegation_count} 次委派）" if deleg_rate is not None
                     else f"{delegation_count} 次委派（无委派断言）")},
        {"key": "kb_match", "name": "知识匹配精准度",
         "value": kb_rate, "unit": "%",
         "display": f"{round(kb_rate * 100, 1)}%（{kb_pass}/{kb_total}）" if kb_rate is not None else "—"},
        {"key": "output_quality", "name": "输出质量分",
         "value": out_quality, "unit": "/5",
         "display": f"{out_quality}/5" if out_quality is not None else "—"},
    ]


def _stability_metrics(cases):
    """稳定性：多次 repeat 跑测的成功率与波动（高频数据建立产品可信度）。"""
    per_case = []
    success_rates = []
    for c in cases:
        reps = c.get("repeats") or []
        if not reps:
            continue
        passed = sum(1 for r in reps if r.get("pass"))
        rate = round(passed / len(reps), 4)
        scores = [r.get("score") for r in reps if isinstance(r.get("score"), (int, float))]
        per_case.append({"case_id": c.get("case_id"), "title": c.get("case_title"),
                         "success_rate": rate, "runs": len(reps), "passed": passed,
                         "scores": scores})
        success_rates.append(rate)
    if not success_rates:
        return {"per_case": [], "overall": None}
    avg = sum(success_rates) / len(success_rates)
    var = sum((r - avg) ** 2 for r in success_rates) / len(success_rates)
    return {"per_case": per_case,
            "overall": {"avg_success_rate": round(avg, 4),
                        "std": round(var ** 0.5, 4),
                        "case_count": len(per_case)}}


@reports_bp.get("/runs/<int:run_id>/report")
def get_report(run_id):
    """聚合报告：运行概要 + case 明细 + 技术/业务双视角指标 + 评审。"""
    conn = get_db()
    try:
        run_row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run_row:
            return jsonify({"error": "运行不存在"}), 404
        run = row_to_dict(run_row)
        run["session_ids"] = jloads(run.get("session_ids"))
        case_rows = conn.execute(
            "SELECT * FROM case_results WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        cases = []
        for r in case_rows:
            c = row_to_dict(r)
            c["assertions"] = jloads(c.get("assertions"))
            c["session_ids"] = jloads(c.get("session_ids"))
            c["process_metrics"] = jloads(c.get("process_metrics"))
            c["repeats"] = jloads(c.get("repeats"))
            cases.append(c)
        review_rows = conn.execute(
            "SELECT * FROM reviews WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        reviews = [row_to_dict(r) for r in review_rows]
        for r in reviews:
            r["metrics"] = jloads(r.get("metrics"))
        suggestions = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM ai_suggestions WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
        obj = conn.execute("SELECT name, kind FROM objects WHERE id=?", (run["object_id"],)).fetchone()
        return jsonify({
            "run": run,
            "object_name": obj["name"] if obj else "",
            "object_kind": obj["kind"] if obj else "",
            "cases": cases,
            "reviews": reviews,
            "suggestions": suggestions,
            "metrics": {
                "tech": _tech_metrics(run, cases),
                "module": _module_metrics(cases),
                "business": _business_metrics(run, cases, reviews),
            },
            "stability": _stability_metrics(cases),
        })
    finally:
        conn.close()


def _extract_session(db_path, session_id):
    """从单个 case 的 opencode.db 提取指定会话的完整消息流。

    返回 None 表示该 db 无此会话；否则返回 {session, agent, model, title, case, messages}。
    """
    try:
        conn = sqlite3.connect(f"file:{db_path.replace(os.sep, '/')}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            s = conn.execute(
                "SELECT id, parent_id, agent, model, title FROM session WHERE id=?",
                (session_id,)).fetchone()
            if not s:
                return None
            # 从 db 路径反推 case 目录名：.../runs/<cid>/opencode-data/opencode/opencode.db
            case_dir = os.path.basename(
                os.path.dirname(os.path.dirname(os.path.dirname(db_path))))
            messages = []
            for m in conn.execute(
                    "SELECT id, time_created, data FROM message WHERE session_id=? ORDER BY time_created",
                    (session_id,)):
                try:
                    md = json.loads(m["data"] or "{}")
                except Exception:  # noqa: BLE001
                    md = {}
                role = md.get("role", "unknown")
                agent = md.get("agent") or ""
                parts = []
                for p in conn.execute(
                        "SELECT data FROM part WHERE message_id=? ORDER BY time_created",
                        (m["id"],)):
                    try:
                        pd = json.loads(p["data"] or "{}")
                    except Exception:  # noqa: BLE001
                        continue
                    ptype = pd.get("type", "")
                    if ptype == "text":
                        parts.append({"type": "text", "text": pd.get("text", "")})
                    elif ptype == "tool":
                        st = pd.get("state") or {}
                        parts.append({"type": "tool", "tool": pd.get("tool", ""),
                                      "status": st.get("status", ""),
                                      "input": st.get("input"),
                                      "output": st.get("output"),
                                      "error": st.get("error") or ""})
                    elif ptype == "reasoning":
                        parts.append({"type": "reasoning",
                                      "text": (pd.get("text") or "")[:300]})
                    # step-start/step-finish 等过程标记跳过
                messages.append({"id": m["id"], "role": role, "agent": agent,
                                 "time": m["time_created"], "parts": parts})
            return {"session": s["id"], "parent_id": s["parent_id"], "agent": s["agent"],
                    "model": s["model"], "title": s["title"], "case": case_dir,
                    "messages": messages}
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


@reports_bp.get("/runs/<int:run_id>/session/<session_id>")
def get_session_detail(run_id, session_id):
    """报告页会话证据弹窗：按 session_id 在 run 目录各 case 的 opencode.db 中查找并返回完整消息流。"""
    conn = get_db()
    try:
        run = conn.execute("SELECT results_path FROM runs WHERE id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    if not run or not run["results_path"]:
        return jsonify({"error": "run 不存在或无 results_path"}), 404
    run_dir = os.path.dirname(run["results_path"])
    dbs = sorted(glob.glob(
        os.path.join(run_dir, "runs", "*", "opencode-data", "opencode", "opencode.db")))
    for db in dbs:
        data = _extract_session(db, session_id)
        if data:
            return jsonify({"session": data})
    return jsonify({"error": f"未找到会话 {session_id}"}), 404
