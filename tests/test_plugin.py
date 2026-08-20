#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Promptfoo Expert Eval —— 插件自测脚本

覆盖 5 层：
  S1 静态/结构：manifest、YAML、语法、目录、case/断言 schema
  F2 功能：--list / --dry-run / --case 过滤 / 自定义 case / setup fixture / 越界防护
  P3 解析与内部：parse_results（新旧结构）、resolve_command、占位符渲染
  I4 集成：promptfoo / opencode / @opencode-ai/sdk / javascript 断言写法（echo）
  E5 端到端：真实 opencode:sdk + 模型（无 API key 时标记 blocked）

用法：
    python tests/test_plugin.py                 # 全部测试
    python tests/test_plugin.py --only F        # 只跑指定前缀（S/F/P/I/E）

输出：<repo>/tests/test-report.json（结构化结果，供 render_report.py 渲染）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "promptfoo-expert-eval")
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
RUN_EVAL = os.path.join(SCRIPTS_DIR, "run_eval.py")
DEFAULT_CASES = os.path.join(SKILL_DIR, "cases", "default-cases.yaml")
# 被测工作区（绝对路径，避免 cwd 不同导致相对路径解析错误）
WORKSPACE = os.path.abspath(os.path.join(REPO_ROOT, "..", "workspaces", "test01"))

sys.path.insert(0, SCRIPTS_DIR)
import run_eval  # noqa: E402

RESULTS = []  # list[dict]
E2E_EVIDENCE = None  # 端到端真实运行证据文件（results.json）


def record(test_id, category, name, status, detail="", duration_ms=None):
    RESULTS.append({
        "id": test_id,
        "category": category,
        "name": name,
        "status": status,  # pass | fail | blocked | skipped
        "detail": detail,
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
    })
    mark = {"pass": "PASS", "fail": "FAIL", "blocked": "BLOCKED", "skipped": "SKIP"}[status]
    print(f"  [{mark:7s}] {test_id} {name}" + (f" — {detail[:90]}" if detail else ""))


def section(title):
    print(f"\n== {title} ==")


def run_py(args, cwd=None, timeout=120):
    """运行 run_eval.py，返回 (returncode, stdout+stderr)。"""
    proc = subprocess.run(
        [sys.executable, RUN_EVAL] + args,
        cwd=cwd or REPO_ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def tmpdir():
    return tempfile.mkdtemp(prefix="expert-eval-test-")


# run_eval.py 统一工作区参数（绝对路径）
WS = ["--working-dir", WORKSPACE]


# --------------------------------------------------------------------------- #
# S1 静态 / 结构
# --------------------------------------------------------------------------- #

def test_plugin_json():
    p = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
    d = json.load(open(p, encoding="utf-8"))
    req = ("name", "displayName", "version", "description", "skills", "author")
    missing = [k for k in req if k not in d]
    ok = not missing and d.get("skills") == "./skills/"
    return ok, (f"缺少字段: {missing}" if missing else f"name={d['name']} skills={d['skills']}")


def test_marketplace_json():
    p = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
    d = json.load(open(p, encoding="utf-8"))
    plugins = d.get("plugins", [])
    local = [x for x in plugins if x.get("source") == "./"]
    manager = [x for x in plugins if isinstance(x.get("source"), dict)
               and x["source"].get("source") == "github"
               and x["source"].get("repo") == "xiaodong528/mobilework-expert-manager"]
    ok = len(local) == 1 and len(manager) == 1
    return ok, f"本插件 x{len(local)} / 公共 manager x{len(manager)}"


def test_cases_yaml():
    import yaml
    d = yaml.safe_load(open(DEFAULT_CASES, encoding="utf-8"))
    ok = isinstance(d, list) and len(d) >= 4
    return ok, f"{len(d)} 个 case"


def test_run_eval_syntax():
    import ast
    ast.parse(open(RUN_EVAL, encoding="utf-8").read())
    return True, "ast.parse OK"


def test_skill_frontmatter():
    import yaml
    p = os.path.join(SKILL_DIR, "SKILL.md")
    raw = open(p, encoding="utf-8").read()
    parts = raw.split("---", 2)
    ok = len(parts) >= 3
    meta = yaml.safe_load(parts[1]) if ok else {}
    ok = ok and bool(meta.get("name")) and bool(meta.get("description"))
    return ok, f"name={meta.get('name')}"


def test_dir_structure():
    need = [
        os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json"),
        os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json"),
        os.path.join(SKILL_DIR, "SKILL.md"),
        RUN_EVAL,
        DEFAULT_CASES,
        os.path.join(SKILL_DIR, "references", "case-schema.md"),
        os.path.join(SKILL_DIR, "references", "methodology.md"),
        os.path.join(REPO_ROOT, "README.md"),
    ]
    missing = [p for p in need if not os.path.exists(p)]
    return not missing, (f"缺失: {missing}" if missing else f"{len(need)} 个关键文件齐全")


def test_case_schema():
    import yaml
    d = yaml.safe_load(open(DEFAULT_CASES, encoding="utf-8"))
    allowed_types = ("structured", "hybrid", "open-ended")
    allowed_assert = ("contains", "regex", "javascript")
    problems = []
    for c in d:
        for f in ("id", "title", "type", "prompt", "output_dir", "assertions"):
            if f not in c:
                problems.append(f"{c.get('id','?')} 缺 {f}")
        if c.get("type") not in allowed_types:
            problems.append(f"{c['id']} type 非法: {c.get('type')}")
        if "{run_id}" not in c.get("output_dir", ""):
            problems.append(f"{c['id']} output_dir 缺 {{run_id}}")
        if not c.get("assertions"):
            problems.append(f"{c['id']} 无断言")
        for a in c.get("assertions", []):
            if a.get("type") not in allowed_assert:
                problems.append(f"{c['id']} 断言类型非法: {a.get('type')}")
    return not problems, ("; ".join(problems) if problems else "4 个 case 字段/断言类型全部合法")


def test_references_exist():
    ok = all(os.path.exists(os.path.join(SKILL_DIR, "references", f)) for f in
             ("case-schema.md", "methodology.md"))
    return ok, "case-schema.md + methodology.md"


# --------------------------------------------------------------------------- #
# F2 功能
# --------------------------------------------------------------------------- #

def test_list():
    rc, out = run_py(WS + ["--list"])
    ids = ["todo-cli", "prd-priority", "feature-design", "bugfix-utils"]
    ok = rc == 0 and all(i in out for i in ids)
    return ok, ("rc=0, 4 个 case 均在输出中" if ok else f"rc={rc}, tail={out[-300:]}")


def test_dryrun_all():
    out_dir = tmpdir()
    rc, out = run_py(WS + ["--dry-run", "--all", "--output-dir", out_dir])
    runs = os.path.join(out_dir, "runs")
    cfgs = [f for f in os.listdir(runs)] if os.path.isdir(runs) else []
    ok = rc == 0 and len(cfgs) == 4
    return ok, (f"rc=0, 生成 {len(cfgs)} 个配置" if ok else f"rc={rc}, tail={out[-300:]}")


def test_config_content():
    out_dir = tmpdir()
    run_py(WS + ["--dry-run", "--all", "--output-dir", out_dir])
    import yaml
    cfg = yaml.safe_load(open(os.path.join(out_dir, "runs", "todo-cli-01", "promptfooconfig.yaml"), encoding="utf-8"))
    prov = cfg["providers"][0]["config"]
    problems = []
    if prov.get("agent") != "software-team-lead":
        problems.append("agent 错误")
    if not str(prov.get("working_dir", "")).replace("\\", "/").endswith("workspaces/test01"):
        problems.append("working_dir 错误")
    if prov.get("permission", {}).get("external_directory") != "deny":
        problems.append("external_directory 未 deny")
    if prov.get("permission", {}).get("doom_loop") != "deny":
        problems.append("doom_loop 未 deny")
    if prov.get("permission", {}).get("task") != "allow":
        problems.append("task 未 allow")
    bash = prov.get("permission", {}).get("bash", {})
    if bash.get("*") != "deny" or "node *" not in bash:
        problems.append("bash 白名单异常")
    js_values = [a["value"] for a in cfg["tests"][0]["assert"] if a["type"] == "javascript"]
    if not js_values or any("{output_dir_abs}" in v for v in js_values):
        problems.append("javascript 断言占位符未替换")
    if js_values and not any("import('node:fs')" in v for v in js_values):
        problems.append("javascript 断言未使用已验证的 import 写法")
    return not problems, ("; ".join(problems) if problems else "agent/permission/bash/占位符全部正确")


def test_case_filter():
    out_dir = tmpdir()
    rc, out = run_py(WS + ["--dry-run", "--case", "todo-cli", "--output-dir", out_dir])
    runs = os.path.join(out_dir, "runs")
    cfgs = os.listdir(runs) if os.path.isdir(runs) else []
    ok = rc == 0 and cfgs == ["todo-cli-01"]
    return ok, (f"rc=0, 仅生成 {cfgs}" if ok else f"rc={rc}, {cfgs}, tail={out[-200:]}")


def test_case_not_found():
    rc, out = run_py(WS + ["--case", "not-exist"])
    ok = rc != 0 and "not-exist" in out and "可用 case" in out
    return ok, ("非零退出 + 提示可用 case" if ok else f"rc={rc}, tail={out[-300:]}")


def test_case_file_custom():
    import yaml
    tmp = tmpdir()
    custom = os.path.join(tmp, "custom.yaml")
    yaml.safe_dump([{
        "id": "todo-cli",  # 与默认冲突 → 自定义优先
        "title": "自定义覆盖版",
        "type": "structured",
        "prompt": "自定义 prompt {output_dir}",
        "output_dir": "eval-runs/{run_id}/todo-cli",
        "assertions": [{"type": "contains", "value": "x"}],
    }, {
        "id": "brand-new-case",
        "title": "全新 case",
        "type": "open-ended",
        "prompt": "新任务 {output_dir}",
        "output_dir": "eval-runs/{run_id}/brand-new",
        "assertions": [{"type": "regex", "value": "ok"}],
    }], open(custom, "w", encoding="utf-8"), allow_unicode=True)
    out_dir = os.path.join(tmp, "out")
    rc, out = run_py(WS + ["--dry-run", "--all", "--case-file", custom, "--output-dir", out_dir])
    runs = os.path.join(out_dir, "runs")
    cfgs = sorted(os.listdir(runs)) if os.path.isdir(runs) else []
    # 默认 4 + 新增 1 = 5；todo-cli 被自定义覆盖（标题变化）
    todo_cfg = os.path.join(runs, "todo-cli-01", "promptfooconfig.yaml")
    overridden = os.path.exists(todo_cfg) and "自定义覆盖版" in open(todo_cfg, encoding="utf-8").read()
    has_new = any(c.startswith("brand-new-case-0") for c in cfgs)
    ok = rc == 0 and len(cfgs) == 5 and overridden and has_new
    return ok, (f"5 个配置，todo-cli 已覆盖，brand-new-case 已加入" if ok
                else f"rc={rc}, cfgs={cfgs}, overridden={overridden}, has_new={has_new}")


def test_setup_fixtures():
    """bugfix-utils 含 setup fixture：dry-run 生成的配置应可解析且 prompt 已渲染。"""
    import yaml
    out_dir = tmpdir()
    rc, out = run_py(WS + ["--dry-run", "--case", "bugfix-utils", "--output-dir", out_dir])
    cfg_path = os.path.join(out_dir, "runs", "bugfix-utils-01", "promptfooconfig.yaml")
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else None
    prompt = cfg["prompts"][0] if cfg else ""
    problems = []
    if rc != 0:
        problems.append(f"rc={rc}")
    if cfg is None:
        problems.append("配置缺失")
    if "{output_dir}" in prompt or "{run_id}" in prompt:
        problems.append("占位符未替换")
    if "utils/utils.js" not in prompt:
        problems.append("fixture 说明未进入 prompt")
    return not problems, ("配置生成成功，prompt 已渲染 fixture 说明" if not problems else "; ".join(problems))


def test_setup_traversal_guard():
    """setup.files 路径越界应被拒绝。"""
    tmp = tmpdir()
    bad = os.path.join(tmp, "bad.yaml")
    import yaml
    yaml.safe_dump([{
        "id": "evil",
        "title": "越界",
        "type": "structured",
        "prompt": "x",
        "output_dir": "eval-runs/{run_id}/evil",
        "assertions": [{"type": "contains", "value": "x"}],
        "setup": {"files": [{"path": "../escape.txt", "content": "boom"}]},
    }], open(bad, "w", encoding="utf-8"), allow_unicode=True)
    out_dir = os.path.join(tmp, "out")
    rc, out = run_py(WS + ["--dry-run", "--case-file", bad, "--case", "evil", "--output-dir", out_dir])
    ok = rc != 0 and "越界" in out
    return ok, ("越界路径被拒绝" if ok else f"rc={rc}（应拒绝）")


def test_missing_case_file():
    rc, out = run_py(WS + ["--case-file", "no-such-file.yaml", "--list"])
    ok = rc != 0 and "不存在" in out
    return ok, ("缺失 case 文件报错" if ok else f"rc={rc}")


# --------------------------------------------------------------------------- #
# P3 解析与内部
# --------------------------------------------------------------------------- #

def test_parse_results_new():
    """promptfoo 0.121 新结构（顶层 dict）。"""
    payload = {
        "evalId": "x", "results": {"results": [{
            "success": False, "score": 0.5, "error": None,
            "response": "hello output", "durationMs": 1234,
            "metadata": {"sessionId": "ses-abc"},
            "gradingResult": {"componentResults": [
                {"pass": True, "score": 1, "reason": "ok", "assertion": {"type": "contains", "value": "hello"}},
                {"pass": False, "score": 0, "reason": "no", "assertion": {"type": "javascript"}},
            ]},
        }]}
    }
    p = os.path.join(tmpdir(), "r.json")
    json.dump(payload, open(p, "w", encoding="utf-8"))
    r = run_eval.parse_results(p)
    ok = (r["pass"] is False and r["score"] == 0.5 and len(r["assertions"]) == 2
          and r["assertions"][0]["type"] == "contains" and r["session_ids"] == ["ses-abc"]
          and r["output_preview"].startswith("hello"))
    return ok, f"pass={r['pass']} asserts={len(r['assertions'])} sessions={r['session_ids']}"


def test_parse_results_old():
    """旧结构（顶层 list）。"""
    payload = [{"pass": True, "score": 1, "output": "old out", "assertions": [
        {"type": "contains", "pass": True, "reason": "ok", "value": "old"}]}]
    p = os.path.join(tmpdir(), "r.json")
    json.dump(payload, open(p, "w", encoding="utf-8"))
    r = run_eval.parse_results(p)
    ok = r["pass"] is True and len(r["assertions"]) == 1 and r["output_preview"] == "old out"
    return ok, f"pass={r['pass']}"


def test_parse_results_empty():
    p = os.path.join(tmpdir(), "r.json")
    json.dump({}, open(p, "w", encoding="utf-8"))
    r = run_eval.parse_results(p)
    ok = r["pass"] is False and "empty" in (r.get("error") or "")
    return ok, f"error={r.get('error')}"


def test_parse_results_error():
    payload = {"results": {"results": [{"success": False, "error": "boom", "response": ""}]}}
    p = os.path.join(tmpdir(), "r.json")
    json.dump(payload, open(p, "w", encoding="utf-8"))
    r = run_eval.parse_results(p)
    ok = r["pass"] is False and r["error"] == "boom"
    return ok, f"pass={r['pass']} error={r['error']}"


def test_resolve_command_cmd_shim():
    """Windows .CMD shim 应被包装为 cmd.exe /c。"""
    class _A:  # 简化 args 对象
        pass
    if sys.platform == "win32":
        import run_eval as re
        orig_which = shutil.which
        shutil.which = lambda name: "C:/fake/promptfoo.CMD"
        try:
            cmd = re.resolve_command("promptfoo")
        finally:
            shutil.which = orig_which
        ok = len(cmd) == 3 and cmd[0].lower().endswith("cmd.exe") and cmd[2].endswith(".CMD")
        return ok, f"cmd={cmd}"
    # 非 Windows：直接返回路径
    cmd = run_eval.resolve_command("promptfoo")
    return len(cmd) >= 1, f"cmd={cmd}"


def test_render_placeholders():
    out = run_eval.render_placeholders(
        "dir={output_dir} abs={output_dir_abs}", "rel/path", r"C:\abs\path")
    ok = "dir=rel/path" in out and '"C:\\\\abs\\\\path"' in out or '"C:\\\\abs\\\\path"' in out
    # 绝对路径应作为 JSON 字符串字面量出现
    ok = "dir=rel/path" in out and out.count('"') >= 2
    return ok, f"out={out[:80]}"


# --------------------------------------------------------------------------- #
# I4 集成（环境，无需 API key）
# --------------------------------------------------------------------------- #

def test_promptfoo_version():
    v = run_eval._promptfoo_version("promptfoo")
    ok = v and v != "unknown" and v.split(".")[0].isdigit()
    return ok, f"promptfoo {v}"


def test_opencode_version():
    try:
        cmd = run_eval.resolve_command("opencode")
        out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=15)
        v = (out.stdout or out.stderr).strip()
    except Exception as exc:
        return False, f"opencode 不可用: {exc}"
    ok = bool(v)
    return ok, f"opencode {v}"


def test_sdk_installed():
    p = os.path.join(REPO_ROOT, "..", "workspaces", "test01", "node_modules", "@opencode-ai", "sdk")
    p = os.path.abspath(p)
    ok = os.path.isdir(p)
    return ok, (p if ok else f"未找到: {p}")


def test_js_assertion_echo():
    """用 echo provider 验证 javascript 断言写法（import('node:fs')）。"""
    tmp = tmpdir()
    os.makedirs(os.path.join(tmp, "out"), exist_ok=True)
    open(os.path.join(tmp, "out", "app.js"), "w").write("console.log(1)")
    cfg = os.path.join(tmp, "promptfooconfig.yaml")
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write("""providers:
  - echo
prompts:
  - "p"
tests:
  - vars: {}
    assert:
      - type: javascript
        value: |
          const fsp = import('node:fs');
          return fsp.then(m => m.default.existsSync('out/app.js'));
      - type: javascript
        value: |
          const fsp = import('node:fs');
          return fsp.then(m => m.default.existsSync('out/missing.js'));
""")
    cmd = run_eval.resolve_command("promptfoo") + ["eval", "--config", cfg, "--output",
                                                   os.path.join(tmp, "r.json"), "--no-cache", "--no-share"]
    try:
        proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=90)
    except Exception as exc:
        return False, f"promptfoo 执行失败: {exc}"
    if proc.returncode not in (0, 100):
        return False, f"rc={proc.returncode}: {(proc.stdout or proc.stderr)[-200:]}"
    # promptfoo 约定：有断言失败时退出码 100，仍继续解析结果
    r = run_eval.parse_results(os.path.join(tmp, "r.json"))
    comps = r["assertions"]
    ok = len(comps) == 2 and comps[0]["pass"] is True and comps[1]["pass"] is False
    return ok, f"存在断言 PASS、缺失断言 FAIL（共 {len(comps)} 条，rc={proc.returncode}）"


def test_api_key_env():
    keys = ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENCODE_API_KEY"]
    found = [k for k in keys if os.environ.get(k)]
    # Windows 上环境变量可能配置在用户级注册表（当前 shell 未继承）
    if sys.platform == "win32" and not found:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                for name in keys:
                    try:
                        v, _ = winreg.QueryValueEx(k, name)
                        if v:
                            found.append(name)
                    except FileNotFoundError:
                        pass
        except Exception:  # noqa: BLE001
            pass
    if found:
        return True, f"已配置: {found}（进程 env 或注册表用户级）"
    return "blocked", f"未配置模型 API key（{', '.join(keys)}）——真实模型端到端测试受阻"


# --------------------------------------------------------------------------- #
# E5 端到端（需 API key）
# --------------------------------------------------------------------------- #

def test_e2e_real_run():
    # 端到端真实运行证据（--e2e-evidence 指向 run 目录下的 results.json）：
    # 自动测试不发起付费模型调用，但可核对一次真实运行的证据链。
    global E2E_EVIDENCE
    if not E2E_EVIDENCE or not os.path.exists(E2E_EVIDENCE):
        return "blocked", "未提供端到端证据文件（--e2e-evidence <results.json>）"
    r = run_eval.parse_results(E2E_EVIDENCE)
    ok = r["pass"] is True
    detail = (f"真实运行 PASS score={r['score']} output_len={r['output_length']} "
              f"sessions={r.get('session_ids')}" if ok
              else f"真实运行未通过: {r.get('error')}")
    return ok, detail


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

STATIC = [
    ("S01", "S", "plugin.json 合法且字段齐全", test_plugin_json),
    ("S02", "S", "marketplace.json 双插件声明", test_marketplace_json),
    ("S03", "S", "default-cases.yaml 合法 YAML", test_cases_yaml),
    ("S04", "S", "run_eval.py 语法检查", test_run_eval_syntax),
    ("S05", "S", "SKILL.md frontmatter", test_skill_frontmatter),
    ("S06", "S", "关键目录结构完整", test_dir_structure),
    ("S07", "S", "case schema（字段/类型/断言/占位符）", test_case_schema),
    ("S08", "S", "references 文档存在", test_references_exist),
]
FUNC = [
    ("F10", "F", "--list 列出 4 个内置 case", test_list),
    ("F11", "F", "--dry-run --all 生成 4 个配置", test_dryrun_all),
    ("F12", "F", "配置内容（agent/permission/bash/占位符）", test_config_content),
    ("F13", "F", "--case 过滤单个 case", test_case_filter),
    ("F14", "F", "--case 不存在 id 报错", test_case_not_found),
    ("F15", "F", "--case-file 自定义 case 加载与覆盖", test_case_file_custom),
    ("F16", "F", "bugfix-utils dry-run 配置生成", test_setup_fixtures),
    ("F17", "F", "setup 路径越界防护", test_setup_traversal_guard),
    ("F18", "F", "缺失 case 文件报错", test_missing_case_file),
]
PARSE = [
    ("P19", "P", "parse_results 新结构（dict）", test_parse_results_new),
    ("P20", "P", "parse_results 旧结构（list）", test_parse_results_old),
    ("P21", "P", "parse_results 空结果", test_parse_results_empty),
    ("P22", "P", "parse_results error 字段", test_parse_results_error),
    ("P23", "P", "resolve_command Windows .CMD 包装", test_resolve_command_cmd_shim),
    ("P24", "P", "render_placeholders 占位符渲染", test_render_placeholders),
]
INTEG = [
    ("I25", "I", "promptfoo CLI 版本", test_promptfoo_version),
    ("I26", "I", "opencode CLI 版本", test_opencode_version),
    ("I27", "I", "@opencode-ai/sdk 已安装", test_sdk_installed),
    ("I28", "I", "javascript 断言写法（echo 集成）", test_js_assertion_echo),
    ("I29", "I", "模型 API key 环境", test_api_key_env),
]
E2E = [
    ("E30", "E", "端到端：opencode:sdk 真实运行", test_e2e_real_run),
]

ALL = STATIC + FUNC + PARSE + INTEG + E2E


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="只跑指定类别前缀（S/F/P/I/E），可组合如 'SF'")
    ap.add_argument("--e2e-evidence", default=None, metavar="results.json",
                    help="端到端真实运行证据文件（run 目录下的 results.json），供 E30 核对")
    ap.add_argument("--output", default=os.path.join(TESTS_DIR, "test-report.json"))
    args = ap.parse_args()
    global E2E_EVIDENCE
    E2E_EVIDENCE = args.e2e_evidence

    print(f"repo      : {REPO_ROOT}")
    print(f"run_eval  : {RUN_EVAL}")
    print(f"开始时间  : {datetime.now(timezone.utc).isoformat()}")
    print(f"python    : {sys.version.split()[0]}  platform: {sys.platform}")

    selected = [t for t in ALL if not args.only or t[1] in args.only]
    for tid, cat, name, fn in selected:
        print(f"\n{tid} [{cat}] {name}")
        started = time.monotonic()
        try:
            result = fn()
            if isinstance(result, tuple):
                if result[0] == "blocked":
                    status, detail = "blocked", result[1] or ""
                else:
                    ok, detail = result
                    status = "pass" if ok else "fail"
            elif result == "blocked":
                status, detail = "blocked", ""
            else:
                status, detail = ("pass" if result else "fail"), ""
        except Exception as exc:  # noqa: BLE001
            status, detail = "fail", f"异常: {exc}"
            traceback.print_exc()
        record(tid, cat, name, status, detail, (time.monotonic() - started) * 1000)

    stats = {k: sum(1 for r in RESULTS if r["status"] == k) for k in ("pass", "fail", "blocked", "skipped")}
    report = {
        "report_id": f"expert-eval-plugin-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "promptfoo": run_eval._promptfoo_version("promptfoo"),
            "repo_root": REPO_ROOT,
        },
        "stats": stats,
        "total": len(RESULTS),
        "results": RESULTS,
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"测试完成：总 {len(RESULTS)}，PASS {stats['pass']}，FAIL {stats['fail']}，"
          f"BLOCKED {stats['blocked']}，SKIPPED {stats['skipped']}")
    print(f"报告写入：{args.output}")
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
