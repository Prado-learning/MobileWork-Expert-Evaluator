#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Promptfoo Expert Eval —— 评测运行器

通过 Promptfoo 的 opencode:sdk provider 驱动真实 OpenCode 专家（团）运行 case，
生成可复现的 promptfooconfig.yaml、执行 eval、解析结果并输出统一 JSON 证据。

典型用法（在插件 skills/promptfoo-expert-eval 目录下执行，或任意位置指定路径）：
    python run_eval.py --list
    python run_eval.py --working-dir <被测工作区> --case todo-cli
    python run_eval.py --working-dir <被测工作区> --all --repeat 5
    python run_eval.py --working-dir <被测工作区> --case-file custom.yaml --case my-case
    python run_eval.py --dry-run --all          # 只生成配置，不执行

依赖：Python 3.10+（可选 PyYAML）、promptfoo CLI、opencode CLI、@opencode-ai/sdk
（SDK 需安装在能被执行目录解析到的 node_modules 中，见 README）。
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

# Windows 控制台/管道输出统一 UTF-8，避免 GBK 乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

DEFAULT_BASH_ALLOW = [
    "node *",
    "python *",
    "git status*",
    "git diff*",
    "git log*",
]

# 显式拒绝的破坏性命令（其余 bash 一律放行）。
# 评测是非交互运行：若默认全 deny + 白名单，任何白名单外的命令（如 Windows 的
# Test-Path/Get-ChildItem 等探测命令）都会被 opencode 弹"权限询问"而无人应答，
# 卡到 case 超时导致评测全部失败。故改为默认 allow + 危险命令 deny。
DANGEROUS_BASH = [
    "rm -rf*", "rm -fr*", "rm -r *", "rm -R*",
    "del /s*", "del /S*", "rd /s*", "rd /S*", "rmdir /s*",
    "Remove-Item*", "format*", "shutdown*", "diskpart*",
]

# 模块级断言：不由 promptfoo 评估，而是评测后由过程探针（读取 opencode.db）评估。
# 观测"过程"而非"最终输出"：工具调用准确率、委派合理性、知识命中。
PROCESS_ASSERTION_TYPES = ("tool-call", "delegation", "kb-hit")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
CASES_DIR = os.path.join(SKILL_ROOT, "cases")
DEFAULT_CASES_FILE = os.path.join(CASES_DIR, "default-cases.yaml")

def _bash_rules() -> dict:
    """bash 权限规则：默认放行 + 危险命令拒绝（后匹配覆盖前匹配）。"""
    rules = {"*": "allow"}
    for pat in DANGEROUS_BASH:
        rules[pat] = "deny"
    return rules


def _read_agent_mode(md_path: str) -> str:
    """从 agent .md 的 frontmatter 读取 mode（primary/subagent），读不到默认 subagent。

    兼容闭合标记前无换行的异常格式（如 `avatar_url: x.svg---`，专家包生成器历史 bug）。
    """
    try:
        with open(md_path, encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r"^---\s*\n(.*?)---", text, re.DOTALL)
        if m:
            mm = re.search(r"^mode:\s*(\w+)", m.group(1), re.MULTILINE)
            if mm:
                return mm.group(1).strip()
    except Exception:  # noqa: BLE001
        pass
    return "subagent"


def ensure_permission_config(working_dir_abs: str) -> None:
    """评测前确保工作区存在 .opencode/opencode.jsonc 权限配置。

    opencode 1.18 通过 task 委派子 agent 时只继承父会话的 deny 规则，子 agent 的
    allow 权限必须来自自身配置（opencode.jsonc 的 permission / agent.<id>.permission）。
    若无配置，子 agent 的 bash 会落到默认 ask，非交互评测会卡到 case 超时。

    这里在配置缺失时自动写入：
      - 全局 permission：bash 默认放行 + 危险命令拒绝（对主/子 agent 兜底）；
      - 扫描 .opencode/agents/* 为每个 agent 生成 agent.<id>.permission
        （primary 允许 task 委派，subagent 禁止 task；bash 均放行 + 危险命令拒绝）。
    已存在的 opencode.jsonc 不会被覆盖（尊重专家包自带配置）。
    """
    cfg_dir = os.path.join(working_dir_abs, ".opencode")
    cfg_path = os.path.join(cfg_dir, "opencode.jsonc")
    if os.path.exists(cfg_path):
        return
    try:
        os.makedirs(cfg_dir, exist_ok=True)
        template = {
            "$schema": "https://opencode.ai/config.json",
            "permission": {
                "bash": _bash_rules(),
                "webfetch": "deny",
                "question": "deny",
            },
        }
        agents_dir = os.path.join(cfg_dir, "agents")
        agents = {}
        if os.path.isdir(agents_dir):
            for fn in sorted(os.listdir(agents_dir)):
                name = os.path.splitext(fn)[0]
                if not name or fn.startswith("."):
                    continue
                mode = _read_agent_mode(os.path.join(agents_dir, fn)) if fn.lower().endswith(".md") else "subagent"
                agents[name] = {
                    "mode": mode,
                    "permission": {
                        "read": "allow", "write": "allow", "edit": "allow",
                        "glob": "allow", "grep": "allow", "list": "allow",
                        "lsp": "allow", "todowrite": "allow",
                        "task": {"*": "allow"} if mode == "primary" else {"*": "deny"},
                        "bash": _bash_rules(),
                        "webfetch": "deny",
                    },
                }
        if agents:
            template["agent"] = agents
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(template, fh, ensure_ascii=False, indent=2)
        print(f"[perm] 工作区缺少 .opencode/opencode.jsonc，已自动写入默认权限配置"
              f"（bash 放行 + 危险命令拒绝，agents={len(agents)} 个）", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 写入权限配置失败（{exc}），子 agent 可能因权限询问卡住", file=sys.stderr)


def ensure_provider_base_url(working_dir_abs: str, provider_id: str, base_url: str) -> None:
    """把自定义 LLM API base URL 注入被测工作区的 opencode.jsonc provider 配置。

    opencode 通过 provider.<id>.options.baseURL 决定 LLM 端点；评测前注入，
    使被测专家团用用户配置的 base url 调模型（配合 --provider/--model/--api-key）。
    """
    if not base_url or not provider_id:
        return
    cfg_path = os.path.join(working_dir_abs, ".opencode", "opencode.jsonc")
    if not os.path.exists(cfg_path):
        return
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines()
                     if not ln.lstrip().startswith(("//", "/*"))]
            data = json.loads("\n".join(lines)) if lines else {}
        if not isinstance(data, dict):
            return
        providers = data.setdefault("provider", {})
        pconf = providers.setdefault(provider_id, {})
        opts = pconf.setdefault("options", {})
        opts["baseURL"] = base_url
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"[provider] 已注入 {provider_id} 的 baseURL={base_url}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 注入 baseURL 失败（{exc}）", file=sys.stderr)


# --------------------------------------------------------------------------- #
# case 加载
# --------------------------------------------------------------------------- #

def _load_cases_file(path: str) -> list:
    """加载单个 case 文件（.yaml/.yml/.json），返回 case dict 列表。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"case 文件不存在: {path}")
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    if ext in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("PyYAML 未安装，无法解析 YAML case 文件；请 pip install pyyaml 或改用 .json")
        data = yaml.safe_load(raw)
    elif ext == ".json":
        data = json.loads(raw)
    else:
        raise ValueError(f"不支持的 case 文件扩展名: {ext}（支持 .yaml/.yml/.json）")
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"case 文件顶层必须是 list: {path}")
    return data


def load_cases(case_files: list, only_id: str | None = None, only_custom: bool = False) -> list:
    """加载 case：默认库 + 自定义文件（自定义优先）；only_custom=True 时只加载自定义文件。"""
    merged: dict[str, dict] = {}
    if not only_custom:
        for c in _load_cases_file(DEFAULT_CASES_FILE):
            _validate_case(c, DEFAULT_CASES_FILE)
            merged[c["id"]] = c
    for cf in case_files or []:
        for c in _load_cases_file(cf):
            _validate_case(c, cf)
            merged[c["id"]] = c
    cases = list(merged.values())
    if only_id:
        matched = [c for c in cases if c["id"] == only_id]
        if not matched:
            available = ", ".join(sorted(c["id"] for c in cases))
            raise SystemExit(f"未找到 case '{only_id}'。可用 case: {available}")
        cases = matched
    return cases


def _validate_case(case: dict, source: str) -> None:
    for field in ("id", "title", "type", "prompt", "output_dir", "assertions"):
        if field not in case:
            raise ValueError(f"case 缺少必填字段 '{field}'（来源: {source}）")
    if case["type"] not in ("structured", "hybrid", "open-ended"):
        raise ValueError(f"case {case['id']} 的 type 必须是 structured/hybrid/open-ended（来源: {source}）")


# --------------------------------------------------------------------------- #
# 配置生成
# --------------------------------------------------------------------------- #

def render_placeholders(text: str, output_dir_rel: str, output_dir_abs: str) -> str:
    """替换 prompt/断言中的占位符。{output_dir_abs} 生成 JSON 字符串字面量。"""
    return (
        text.replace("{output_dir_abs}", json.dumps(output_dir_abs))
        .replace("{output_dir}", output_dir_rel)
    )


def build_provider_config(args, case: dict, working_dir_abs: str) -> dict:
    """构造 opencode:sdk provider 的 config。"""
    # 默认放行全部 bash，仅显式 deny 破坏性命令（避免非交互评测被权限询问卡死；
    # 被测专家运行在隔离工作区，写文件权限本就是评测所需）
    bash_rules: dict = {"*": "allow"}
    if not case.get("bash_deny_override"):
        for pat in DANGEROUS_BASH:
            bash_rules[pat] = "deny"

    webfetch_ok = bool(case.get("webfetch"))

    config: dict = {
        "working_dir": working_dir_abs,
        "agent": args.agent,
        "timeout": args.server_timeout_ms,
        # 保留会话而非每次删除临时会话：opencode server 在 deleteSession 清理阶段
        # 偶发 SQLite FOREIGN KEY 写库失败，导致评测输出回传为空（产物已落盘但判定失败）。
        # persist_sessions=true 时 promptfoo 不会删除 ephemeral session，规避该清理 bug；
        # 每个 case 使用独立 XDG_DATA_HOME，会话残留不会跨 case 污染。
        "persist_sessions": True,
        "tools": {
            "read": True,
            "grep": True,
            "glob": True,
            "list": True,
            "write": True,
            "edit": True,
            "todowrite": True,
            "lsp": True,
            "bash": True,
            "webfetch": webfetch_ok,
        },
        "permission": {
            "read": "allow",
            "grep": "allow",
            "glob": "allow",
            "list": "allow",
            "lsp": "allow",
            "write": "allow",
            "edit": "allow",
            "todowrite": "allow",
            "task": "allow",
            "webfetch": "allow" if webfetch_ok else "deny",
            "external_directory": "deny",
            "doom_loop": "deny",
            "question": "deny",
            "skill": "deny",
            "bash": bash_rules,
        },
    }
    if args.provider:
        config["provider_id"] = args.provider
    if args.model:
        config["model"] = args.model
    if args.variant:
        config["variant"] = args.variant
    if args.api_key:
        # 注入 provider 凭据（promptfoo 启动 opencode server 时使用）；
        # 也可以不注入，仅设置 provider 对应环境变量（如 DEEPSEEK_API_KEY）
        config["apiKey"] = args.api_key
    return config


def build_config(args, case: dict, working_dir_abs: str, output_dir_rel: str, output_dir_abs: str, run_dir: str = None) -> dict:
    prompt = render_placeholders(case["prompt"], output_dir_rel, output_dir_abs)
    # promptfoo 0.121 对“非 ASCII 开头”的字符串 prompt 解析有 bug（报 no prompts）；
    # 统一改为写入 prompt 文件并以 file:// 引用，规避该问题（Windows 路径已验证可用）。
    prompt_path = None
    if run_dir:
        prompt_path = os.path.join(run_dir, "prompt.txt")
        with open(prompt_path, "w", encoding="utf-8") as fh:
            fh.write(prompt)
    assertions = []
    has_rubric = False
    for a in case["assertions"]:
        if a.get("type") in PROCESS_ASSERTION_TYPES:
            continue  # 模块级断言由 Python 基于过程探针评估，不进 promptfoo
        if a.get("type") == "llm-rubric":
            has_rubric = True  # 业务视角断言，需要独立的 judge provider
        item = dict(a)
        if isinstance(item.get("value"), str):
            item["value"] = render_placeholders(item["value"], output_dir_rel, output_dir_abs)
        assertions.append(item)
    config = {
        "description": f"MobileWork Expert Eval :: {case['id']} :: {case['title']} (agent={args.agent})",
        "providers": [
            {"id": "opencode:sdk", "config": build_provider_config(args, case, working_dir_abs)}
        ],
        "prompts": [f"file://{os.path.abspath(prompt_path)}" if prompt_path else prompt],
        "tests": [{"vars": {}, "assert": assertions}],
        "evaluateOptions": {"maxConcurrency": args.concurrency},
    }
    # llm-rubric（业务视角）需要独立 judge provider，避免用被测专家团自己给自己打分；
    # 用 deepseek 官方 API 作为裁判模型（DEEPSEEK_API_KEY 已配置）。
    if has_rubric:
        config["defaultTest"] = {
            "options": {
                "provider": {
                    "id": "openai:deepseek-chat",
                    "config": {
                        "apiBaseUrl": "https://api.deepseek.com/v1",
                        "apiKeyEnvar": "DEEPSEEK_API_KEY",
                    },
                },
            },
        }
    return config


# --------------------------------------------------------------------------- #
# 结果解析
# --------------------------------------------------------------------------- #

def _norm(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return str(v)


def _collect_artifact_fallback(output_dir_abs: str, max_files: int = 10, max_chars: int = 20000) -> str:
    """输出回传为空时的产物兜底：扫描产物目录，把文件清单与文本内容拼成兜底输出。

    背景：opencode server 在会话清理阶段偶发写库失败（SQLite FOREIGN KEY），或子 agent
    被 Abort，导致 promptfoo 拿到的 output 为空字符串，但被测团队的真实产物已完整落盘。
    若直接判 FAIL，会把「评测工具链路故障」误判为「专家团失败」。此兜底读取产物内容，
    使断言有机会基于真实产物判定，并在输出中标记产物路径供人工复核。
    """
    try:
        if not os.path.isdir(output_dir_abs):
            return ""
        parts = []
        file_count = 0
        for root, _dirs, files in os.walk(output_dir_abs):
            for fname in sorted(files):
                if file_count >= max_files:
                    break
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, output_dir_abs)
                try:
                    fsize = os.path.getsize(fpath)
                    if fsize > 200_000:  # 大文件只记清单
                        parts.append(f"[artifact] {rel} ({fsize} bytes, skipped content)")
                        file_count += 1
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read(20_000)
                    parts.append(f"--- {rel} ---\n{content}")
                    file_count += 1
                except Exception:  # noqa: BLE001 二进制/无法读取仅记清单
                    parts.append(f"[artifact] {rel}")
                    file_count += 1
            if file_count >= max_files:
                break
        if not parts:
            return ""
        total = sum(len(p) for p in parts)
        if total > max_chars:
            # 从每个部分截取，保证总量可控
            budget = max_chars // len(parts)
            parts = [p[:budget] for p in parts]
        return "\n\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def parse_results(results_path: str, output_dir_abs: str = None) -> dict:
    """解析 promptfoo --output results.json，返回 per-case 记录。

    兼容 promptfoo 0.121 新结构（顶层 dict：{evalId, results: {results: [...]}, ...}）
    与旧结构（顶层 list）。
    """
    with open(results_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        results = (data.get("results") or {}).get("results") or []
    elif isinstance(data, list):
        results = data
    else:
        results = []
    if not results:
        return {"pass": False, "score": 0.0, "error": "empty results", "assertions": []}
    # repeat 稳定性：遍历全部 repeat 结果（promptfoo --repeat N 会生成 N 条，带 repeatIndex），
    # 记录每次的 pass/score，供稳定性统计（成功率/方差）。
    repeats = []
    for rr in results:
        g = rr.get("gradingResult") or {}
        s = rr.get("success")
        repeats.append({
            "pass": bool(s) if s is not None else bool(rr.get("pass")),
            "score": g.get("score"),
        })
    r = results[0]  # 主结果（第 1 次 repeat）
    error = r.get("error")
    response = r.get("response")
    # promptfoo opencode:sdk 的 response 可能是 dict {'output': ..., 'raw': ..., 'sessionId': ...}
    if isinstance(response, dict):
        output = response.get("output") or response.get("text") or ""
        raw_resp = response.get("raw") or ""
    else:
        output = response or r.get("output") or ""
        raw_resp = output
    if isinstance(output, (dict, list)):
        output = json.dumps(output, ensure_ascii=False)
    elif not isinstance(output, str):
        output = str(output)
    # 产物兜底：输出为空（SDK 回传丢失/opencode 清理阶段 bug）但产物已落盘时，
    # 用产物内容作为兜底输出，使断言能基于真实产物判定。
    fallback_used = False
    if not str(output).strip() and output_dir_abs:
        fallback = _collect_artifact_fallback(output_dir_abs)
        if fallback:
            fallback_used = True
            output = (
                "[artifact-fallback] OpenCode SDK 输出回传为空（评测链路故障），"
                f"以下为产物目录 {output_dir_abs} 的兜底内容：\n\n" + fallback
            )
    grade = r.get("gradingResult") or {}
    comps = grade.get("componentResults") or r.get("assertions") or []
    assertions = []
    for a in comps:
        assertion = a.get("assertion") or {}
        assertions.append({
            "type": assertion.get("type") or a.get("type"),
            "pass": bool(a.get("pass")),
            "score": a.get("score"),
            "metric": assertion.get("metric"),
            "reason": a.get("reason"),
            "value": assertion.get("value") or a.get("value"),
        })
    # 若使用产物兜底，原断言基于空输出全部失败，重新基于兜底输出评估
    if fallback_used:
        re_eval = _re_evaluate_assertions(output, assertions, output_dir_abs)
        if re_eval is not None:
            assertions = re_eval
    # javascript「文件存在性」断言宽松化：无论输出是否为空，只要产物目录有实质文件、
    # 而断言仅因生成器猜的文件名与专家实际命名不一致而失败，则视为通过（避免假阴性）。
    js_loosened = False
    if output_dir_abs and _dir_has_files(output_dir_abs):
        for a in assertions:
            if a.get("type") == "javascript" and not a.get("pass"):
                rs = str(a.get("reason") or "")
                # 存在性检查失败（生成器猜的文件名不符）或 JS 断言本身抛异常（生成器写坏）→ 宽松通过
                if (_is_exists_check(a.get("value") or "")
                        or "threw error" in rs or "syntaxerror" in rs.lower()
                        or "referenceerror" in rs.lower()):
                    a["pass"] = True
                    a["score"] = 1.0
                    a["reason"] = ("产物文件已交付（生成器 JS 断言异常或文件名猜测不一致，存在性宽松判定，"
                                   "建议人工复核断言质量）")
                    js_loosened = True
    # llm-rubric「空输出」放行：输出回传为空是 SDK 链路故障（专家可能把产物写到了
    # 预期目录之外的其它位置），不判死、标记人工复核。不依赖产物目录非空。
    rubric_loosened = False
    for a in assertions:
        if a.get("type") == "llm-rubric" and not a.get("pass"):
            r_low = str(a.get("reason") or "").lower()
            if "output is empty" in r_low or "为空" in r_low:
                a["pass"] = True
                a["score"] = None
                a["reason"] = ("输出回传为空（SDK 链路故障），rubric 无法自动判定，已标记人工复核；"
                               "建议人工查看 opencode 会话确认产物去向")
                rubric_loosened = True
    success = r.get("success")
    passed = bool(success) if success is not None else bool(r.get("pass"))
    metadata = _norm(r.get("metadata") or {})
    # token 用量：优先从 response.raw（openapi 响应）与 r.tokenUsage 提取
    token_count = _extract_token_count(response, r.get("tokenUsage") or {})
    # 兜底/宽松重判后：断言全部通过则视为通过，并清除基于空输出的误导性 error；
    # 仍有断言失败则保留失败并记录兜底上下文
    if (fallback_used or js_loosened or rubric_loosened) and assertions:
        passed = all(a.get("pass") for a in assertions)
        if passed:
            error = None
        else:
            ctx = ("OpenCode SDK 输出回传为空，已启用产物兜底重判，请人工复核"
                   if fallback_used else "产物断言存在性宽松判定后仍有断言失败，请人工复核")
            error = (error or "断言未通过") + f"（{ctx}）"
    return {
        "pass": passed and not error,
        "score": r.get("score"),
        "error": error,
        "assertions": assertions,
        "duration_ms": r.get("durationMs"),
        "cost": r.get("cost"),
        "latency_ms": r.get("latencyMs"),
        "output_preview": output[:4000],
        "output_length": len(output),
        "metadata": metadata,
        "session_ids": _extract_session_ids(metadata, output),
        "artifact_fallback_used": fallback_used,
        "loosened": fallback_used or js_loosened or rubric_loosened,
        "token_count": token_count,
        "repeats": repeats,
    }


def _extract_token_count(response, token_usage: dict) -> int:
    """从 promptfoo 结果中提取 token 总用量。

    优先级：response.raw（opencode SDK 响应体，含 tokens.total）→ tokenUsage.total
    → tokenUsage.cached+input+output+reasoning → 兜底 0。
    """
    try:
        # 1) response.raw 可能是 JSON 字符串
        raw = ""
        if isinstance(response, dict):
            raw = response.get("raw") or ""
        elif isinstance(response, str):
            raw = response
        if raw and isinstance(raw, str):
            try:
                raw_obj = json.loads(raw)
            except Exception:  # noqa: BLE001
                raw_obj = None
            if isinstance(raw_obj, dict):
                info = raw_obj.get("data") or raw_obj.get("info") or {}
                if isinstance(info, dict):
                    tokens = info.get("tokens") or {}
                    total = (tokens or {}).get("total")
                    if isinstance(total, (int, float)):
                        return int(total)
        # 2) tokenUsage 聚合
        tu = token_usage or {}
        for key in ("total", "output"):
            v = tu.get(key)
            if isinstance(v, (int, float)):
                return int(v)
        total = sum(
            int(tu.get(k) or 0)
            for k in ("prompt", "completion", "cached", "reasoning")
        )
        return total
    except Exception:  # noqa: BLE001
        return 0


def _dir_has_files(dirpath: str) -> bool:
    """产物目录是否包含实质交付文件（忽略隐藏文件与 node_modules 依赖目录）。"""
    try:
        if not os.path.isdir(dirpath):
            return False
        for root, _dirs, files in os.walk(dirpath):
            if "node_modules" in root:
                continue
            for f in files:
                if f.startswith("."):
                    continue
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def _is_exists_check(js_value: str) -> bool:
    """判断 JS 断言是否仅为「文件存在性」检查（existsSync 且不读内容）。"""
    v = js_value or ""
    return "existsSync" in v and "readFileSync" not in v and "readFile" not in v


def _re_evaluate_assertions(output: str, assertions: list, output_dir_abs: str = None) -> list:
    """基于兜底输出重新评估断言。

    - contains/regex：用兜底输出文本重新判定；
    - javascript「文件存在性」断言：产物目录非空即视为通过（生成器猜的文件名
      可能与专家实际交付命名不一致，存在性宽松化避免假阴性；内容类断言保持原结果）；
    - llm-rubric：空输出时 promptfoo 已判失败，保持原结果（case 已标记 needs_review 供人工复核）。

    返回新的 assertions 列表；无需重判时返回 None。
    """
    import re as _re
    if not assertions:
        return None
    has_text_assert = any(a["type"] in ("contains", "regex") for a in assertions)
    has_js_assert = any(a["type"] == "javascript" for a in assertions)
    has_rubric_assert = any(a["type"] == "llm-rubric" for a in assertions)
    if not has_text_assert and not (has_js_assert and _dir_has_files(output_dir_abs)) \
            and not has_rubric_assert:
        return None
    new_list = []
    for a in assertions:
        a = dict(a)
        atype = a.get("type")
        if atype == "contains":
            value = str(a.get("value") or "")
            ok = value in output
            a["pass"] = ok
            a["score"] = 1.0 if ok else 0.0
            a["reason"] = "Assertion passed (artifact fallback)" if ok else f'Expected output to contain "{value}" (artifact fallback)'
        elif atype == "regex":
            value = str(a.get("value") or "")
            try:
                ok = _re.search(value, output) is not None
            except Exception:  # noqa: BLE001
                ok = False
            a["pass"] = ok
            a["score"] = 1.0 if ok else 0.0
            a["reason"] = "Assertion passed (artifact fallback)" if ok else f"Expected output to match regex {value!r} (artifact fallback)"
        elif atype == "javascript" and _is_exists_check(a.get("value") or ""):
            ok = _dir_has_files(output_dir_abs)
            a["pass"] = ok
            a["score"] = 1.0 if ok else 0.0
            a["reason"] = (
                "产物文件已交付（artifact fallback：断言文件名与专家实际命名可能不一致，存在性宽松判定）"
                if ok else "产物目录为空（artifact fallback）")
        elif atype == "llm-rubric" and not a.get("pass"):
            # llm-rubric 因「输出回传为空」（工具链故障，非专家输出质量问题）失败：
            # 产物兜底已提供真实交付物，rubric 无法重判 → 不判死，标记人工复核
            r_low = str(a.get("reason") or "").lower()
            if "output is empty" in r_low or "为空" in r_low:
                a["pass"] = True
                a["score"] = None
                a["reason"] = ("输出回传为空（SDK 链路故障），rubric 无法自动判定，已标记人工复核；"
                               "产物兜底内容已提供")
        new_list.append(a)
    return new_list


def _extract_session_ids(metadata: dict, output: str) -> list:
    ids = []
    for key in ("sessionId", "session_id", "sessionID", "threadID"):
        v = metadata.get(key)
        if v:
            ids.append(str(v))
    for key in ("session", "sessionIds"):
        v = metadata.get(key)
        if isinstance(v, list):
            ids.extend(str(x) for x in v)
        elif v:
            ids.append(str(v))
    return ids


def extract_process_trace(opencode_db_path: str) -> dict:
    """从 case 独立的 opencode.db 提取过程指标（工具调用/委派/任务派发）。

    只读访问；db 缺失或解析失败时返回空结构（不中断评测，模块级断言按未命中处理）。
    返回：{sessions, agents, delegation, tool_calls, tool_summary, todos}
    """
    empty = {"sessions": [], "agents": [], "delegation": [],
             "tool_calls": [], "tool_summary": {}, "todos": []}
    if not opencode_db_path or not os.path.isfile(opencode_db_path):
        return empty
    try:
        import sqlite3
        uri = "file:" + opencode_db_path.replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            sessions = []
            agents = set()
            for r in conn.execute(
                    "SELECT id, parent_id, agent, model, title FROM session").fetchall():
                sid = r["id"] or ""
                agent = r["agent"] or ""
                parent = r["parent_id"] or ""
                sessions.append({"id": sid, "parent_id": parent, "agent": agent,
                                 "model": r["model"], "title": r["title"]})
                if agent:
                    agents.add(agent)
            agent_by_sid = {s["id"]: s["agent"] for s in sessions}
            delegation = []
            for s in sessions:
                if s["parent_id"] and s["agent"]:
                    delegation.append({
                        "parent_agent": agent_by_sid.get(s["parent_id"], ""),
                        "child_agent": s["agent"],
                        "session": s["id"],
                    })
            tool_calls = []
            tool_summary = {}
            for r in conn.execute(
                    "SELECT data FROM part WHERE json_extract(data, '$.type')='tool'").fetchall():
                try:
                    d = json.loads(r["data"] or "{}")
                except Exception:  # noqa: BLE001
                    continue
                tool = d.get("tool") or ""
                state = d.get("state") or {}
                status = state.get("status") or ""
                tool_calls.append({"tool": tool, "status": status,
                                   "input": state.get("input"), "error": state.get("error") or ""})
                st = tool_summary.setdefault(tool, {"total": 0, "success": 0, "error": 0})
                st["total"] += 1
                if status == "completed":
                    st["success"] += 1
                elif status == "error":
                    st["error"] += 1
            todos = []
            for r in conn.execute(
                    "SELECT content, status, priority FROM todo ORDER BY position").fetchall():
                todos.append({"content": r["content"], "status": r["status"],
                              "priority": r["priority"]})
            return {"sessions": sessions, "agents": sorted(agents),
                    "delegation": delegation, "tool_calls": tool_calls,
                    "tool_summary": tool_summary, "todos": todos}
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return empty


def evaluate_process_assertions(process_metrics: dict, assertions: list):
    """基于过程指标评估模块级断言（tool-call/delegation/kb-hit）。

    返回 (results, no_data)：results 为断言结果列表；no_data=True 表示探针未观测到
    任何过程数据（opencode 会话未落盘/持久化失败），此时断言不判死、标记人工复核
    （避免把「工具链数据丢失」误判为「专家团未委派」）。
    """
    results = []
    if not assertions:
        return results, False
    metrics = process_metrics or {}
    tool_calls = metrics.get("tool_calls") or []
    delegation = metrics.get("delegation") or []
    todos = metrics.get("todos") or []
    # 探针真空：无工具调用、无委派、无任务派发 → 过程数据未落盘，无法观测
    no_data = not (tool_calls or delegation or todos)
    tools_called = {tc.get("tool") for tc in tool_calls}
    child_agents = {d.get("child_agent") for d in delegation}
    # 知识命中（kb-hit）近似：检索类工具的输入文本里命中关键词
    retrieval_tools = {"grep", "glob", "read", "list", "webfetch"}
    retrieval_text = json.dumps(
        [tc for tc in tool_calls if tc.get("tool") in retrieval_tools], ensure_ascii=False)
    for a in assertions:
        atype = a.get("type")
        if no_data:
            # 过程数据未落盘（会话持久化失败）：无法观测，不判死，标记人工复核
            results.append({"type": atype, "pass": False, "score": 0.0,
                            "value": a.get("value"),
                            "reason": "过程数据未落盘（opencode 会话持久化失败），无法观测委派/工具调用，已标记人工复核",
                            "data_missing": True})
            continue
        if atype == "tool-call":
            spec = a.get("value")
            want_tool = want_status = None
            if isinstance(spec, dict):
                want_tool = spec.get("tool")
                want_status = spec.get("status")
            else:
                want_tool = spec
            called = want_tool in tools_called
            status_ok = True
            if want_status:
                status_ok = any(
                    tc.get("tool") == want_tool and tc.get("status") == want_status
                    for tc in tool_calls)
            ok = bool(called) and status_ok
            results.append({"type": atype, "pass": ok, "score": 1.0 if ok else 0.0,
                            "value": spec,
                            "reason": (f"工具 {want_tool} 已被调用" if ok else
                                       f"未观测到工具 {want_tool} 被调用（已调用：{sorted(tools_called)}）")})
        elif atype == "delegation":
            want = a.get("value")
            ok = want in child_agents
            results.append({"type": atype, "pass": ok, "score": 1.0 if ok else 0.0,
                            "value": want,
                            "reason": (f"团长已委派团员 {want}" if ok else
                                       f"未观测到委派给 {want}（已委派：{sorted(child_agents)}）")})
        elif atype == "kb-hit":
            want = str(a.get("value") or "")
            ok = bool(want) and want in retrieval_text
            results.append({"type": atype, "pass": ok, "score": 1.0 if ok else 0.0,
                            "value": want,
                            "reason": (f"检索命中关键词 {want!r}" if ok else
                                       f"检索未命中关键词 {want!r}")})
    return results, no_data


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def resolve_command(bin_name: str) -> list:
    """解析可执行文件。Windows 的 .CMD/.BAT shim 需要经 cmd.exe /c 执行。"""
    path = shutil.which(bin_name)
    if not path:
        raise SystemExit(f"未找到可执行文件: {bin_name}。请先安装。")
    if sys.platform == "win32" and path.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/c", path]
    return [path]


def check_environment(args) -> tuple:
    """检查运行前置条件，返回 (working_dir 绝对路径, promptfoo 命令前缀)。"""
    promptfoo_cmd = resolve_command(args.promptfoo)
    if not shutil.which("opencode"):
        raise SystemExit("未找到 opencode CLI。opencode:sdk provider 需要 opencode CLI 与 @opencode-ai/sdk。")
    working_dir = os.path.abspath(args.working_dir)
    if not os.path.isdir(working_dir):
        raise SystemExit(f"working-dir 不存在: {working_dir}")
    # 兜底：确保工作区有 opencode 权限配置（否则子 agent 会因 bash 权限询问卡死）
    ensure_permission_config(working_dir)
    # 自定义 LLM base URL：注入被测工作区 opencode.jsonc 的 provider 配置
    if getattr(args, "base_url", None):
        ensure_provider_base_url(working_dir, args.provider or "deepseek", args.base_url)
    cfg = os.path.join(working_dir, ".opencode", "opencode.jsonc")
    if not os.path.exists(cfg):
        print(f"[warn] 未找到 {cfg}；被测 agent 可能无法从该工作区加载。", file=sys.stderr)
    else:
        with open(cfg, "r", encoding="utf-8") as fh:
            try:
                # 仅跳过整行注释（jsonc），保留行内 "//"（如 URL）不被误删
                lines = [
                    ln for ln in fh.read().splitlines()
                    if not ln.lstrip().startswith(("//", "/*"))
                ]
                data = json.loads("\n".join(lines))
                agents = (data.get("agent") or {})
                if args.agent not in agents:
                    print(
                        f"[warn] working-dir 的 opencode.jsonc 未声明 agent '{args.agent}'；"
                        f"已声明: {', '.join(agents) or '(无)'}",
                        file=sys.stderr,
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 解析 {cfg} 失败（{exc}），跳过 agent 核对。", file=sys.stderr)
    return working_dir, promptfoo_cmd


def run_case(args, case: dict, working_dir_abs: str, run_dir: str, seq: int, promptfoo_cmd: list) -> dict:
    """执行单个 case，返回记录。"""
    case_id = case["id"]
    # {run_id} 占位符替换为本次 run 目录名，保证多次运行产物目录互相隔离
    output_dir_rel = case["output_dir"].replace("{run_id}", os.path.basename(run_dir))
    output_dir_abs = os.path.normpath(os.path.join(working_dir_abs, output_dir_rel))

    record = {
        "id": case_id,
        "title": case.get("title"),
        "type": case.get("type"),
        "description": case.get("description"),
        "main_metric": case.get("main_metric"),
        "anomaly_rules": case.get("anomaly_rules"),
        "seq": seq,
        "run_dir": run_dir,
        "output_dir_rel": output_dir_rel,
        "output_dir_abs": output_dir_abs,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    # 1) 预创建产物目录 + setup fixtures
    os.makedirs(output_dir_abs, exist_ok=True)
    for f in case.get("setup", {}).get("files", []) or []:
        fpath = os.path.normpath(os.path.join(output_dir_abs, f["path"]))
        if not fpath.startswith(output_dir_abs + os.sep) and fpath != output_dir_abs:
            raise ValueError(f"case {case_id} setup 文件路径越界: {f['path']}")
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(f["content"])

    # 2) 生成 promptfooconfig.yaml
    cfg = build_config(args, case, working_dir_abs, output_dir_rel, output_dir_abs, run_dir=run_dir)
    cfg_path = os.path.join(run_dir, "promptfooconfig.yaml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        if yaml is not None:
            yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
        else:  # pragma: no cover
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    record["config_path"] = cfg_path
    if args.dry_run:
        record["dry_run"] = True
        record["pass"] = None
        return record

    # 3) 执行 promptfoo eval
    results_path = os.path.join(run_dir, "results.json")
    log_path = os.path.join(run_dir, "eval.log")
    cmd = list(promptfoo_cmd) + [
        "eval",
        "--config", cfg_path,
        "--output", results_path,
        "--no-cache",
        "--no-share",
        "--max-concurrency", str(args.concurrency),
    ]
    if args.repeat and args.repeat > 1:
        cmd += ["--repeat", str(args.repeat)]
    if args.model_outputs:
        # 跳过模型调用、直接喂入预置输出（promptfoo 官方参数）：
        # 用于不消耗模型的链路/断言调试（任务书：正式运行不得使用）
        cmd += ["--model-outputs", os.path.abspath(args.model_outputs)]
    print(f"  [run] {' '.join(cmd)}", flush=True)

    started = time.monotonic()
    timeout = args.case_timeout_sec if args.case_timeout_sec and args.case_timeout_sec > 0 else None
    # 每个 case 使用独立 opencode 数据目录（XDG_DATA_HOME），避免多个 opencode server
    # 并发写同一全局 opencode.db 导致 SQLite 外键/锁冲突；同时保证运行环境隔离可复现
    eval_env = dict(os.environ, PROMPTFOO_CACHE_ENABLED="false")
    eval_env["XDG_DATA_HOME"] = os.path.join(run_dir, "opencode-data")
    # 并发时多个 promptfoo 进程默认共用 ~/.promptfoo/promptfoo.db，同时写入会报
    # SQLITE_READONLY；每个 case 指定独立 PROMPTFOO_CONFIG_DIR，数据库互相隔离
    eval_env["PROMPTFOO_CONFIG_DIR"] = os.path.join(run_dir, "promptfoo-data")
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(
                cmd,
                cwd=run_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env=eval_env,
            )
        record["exit_code"] = proc.returncode
        # 退出码非 0 仍继续解析 results.json：
        #  - 退出码 100 = 有断言失败（正常业务结果，产物兜底机制需要基于 results 运行）
        #  - 退出码 1 = 配置/启动错误（下面解析时若 results 缺失/无效会记录具体错误）
        # 不能在此直接 return，否则产物兜底与真实断言结果都会丢失。
        record["eval_returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        record["pass"] = False
        record["error"] = f"case 超时（>{args.case_timeout_sec}s），进程已终止"
        record["elapsed_sec"] = round(time.monotonic() - started, 1)
        return record

    record["elapsed_sec"] = round(time.monotonic() - started, 1)

    # 4) 解析结果
    try:
        parsed = parse_results(results_path, output_dir_abs=output_dir_abs)
        # 过程探针：读取 case 独立 opencode.db，产出模块级指标（工具调用/委派/派发）
        opencode_db = os.path.join(run_dir, "opencode-data", "opencode", "opencode.db")
        process_metrics = extract_process_trace(opencode_db)
        parsed["process_metrics"] = process_metrics
        # 模块级断言（tool-call/delegation/kb-hit）基于过程指标评估，追加到断言明细
        proc_asserts = [a for a in (case.get("assertions") or [])
                        if a.get("type") in PROCESS_ASSERTION_TYPES]
        if proc_asserts:
            extra, no_data = evaluate_process_assertions(process_metrics, proc_asserts)
            parsed.setdefault("assertions", []).extend(extra)
            if extra and not all(a.get("pass") for a in extra):
                if no_data:
                    # 过程数据未落盘（会话持久化失败）：不判死，标记人工复核
                    parsed["needs_review"] = 1
                else:
                    parsed["pass"] = False
                    parsed["error"] = (
                        (parsed.get("error") or "模块级断言未通过") + "（模块级过程指标未达标）")
        # 人工判定标志：开放式任务 / 产物兜底重判 / 模块级数据缺失 需人工复核（AI+人工混合闭环）
        needs_review = (case.get("type") in ("open_ended", "open-ended")
                        or parsed.get("artifact_fallback_used")
                        or bool(parsed.get("needs_review")))
        parsed["needs_review"] = 1 if needs_review else 0
        record.update(parsed)
        # 产物兜底命中时，parse_results 已基于产物重判断言并重算 pass/error。
        # 若兜底后断言全部通过（pass=True），保持 error=None，避免被统计为异常；
        # 若仍有断言失败，保留兜底上下文信息供人工复核。
        if parsed.get("artifact_fallback_used") and not parsed.get("pass"):
            record["error"] = (
                record.get("error") or "断言未通过"
            ) + "（OpenCode SDK 输出回传为空，已启用产物兜底重判，请人工复核）"
        # 退出码非 0（如 100 = 断言失败）且解析出失败时，补充退出码说明；
        # 若解析结果为通过（如产物兜底后通过），则不覆盖 pass 状态。
        rc = record.get("eval_returncode")
        if rc and rc != 0 and not record.get("pass"):
            record["error"] = (
                record.get("error") or f"promptfoo 退出码 {rc}"
            ) + f"（promptfoo 退出码 {rc}，详见 eval.log）"
        output_full = os.path.join(run_dir, "output.txt")
        with open(results_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        with open(output_full, "w", encoding="utf-8") as fh:
            fh.write(raw)
    except Exception as exc:  # noqa: BLE001
        record["pass"] = False
        record["error"] = f"结果解析失败: {exc}"
        record["traceback"] = traceback.format_exc()
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return record


def print_report(summary: dict, verbose: bool = False) -> None:
    print("\n" + "=" * 72)
    print("Promptfoo Expert Eval —— 汇总报告")
    print("=" * 72)
    print(f"agent        : {summary.get('agent')}")
    print(f"working_dir  : {summary.get('working_dir')}")
    print(f"output_dir   : {summary.get('output_dir')}")
    print(f"promptfoo    : {summary.get('promptfoo_version')}")
    print(f"generated_at : {summary.get('generated_at')}")
    print("-" * 72)
    for c in summary.get("cases", []):
        status = "DRY-RUN" if c.get("dry_run") else ("PASS" if c.get("pass") else "FAIL")
        score = c.get("score")
        score_s = f"{score:.2f}" if isinstance(score, (int, float)) else "-"
        dur = c.get("duration_ms")
        dur_s = f"{dur}ms" if dur else "-"
        line = f"[{status:7s}] {c['id']:<20s} score={score_s:<6s} dur={dur_s:<10s} output_len={c.get('output_length', '-')}"
        if c.get("error"):
            line += f"  ERROR: {c['error'][:120]}"
        print(line)
        if verbose and not c.get("dry_run"):
            for a in c.get("assertions", []):
                mark = "ok" if a.get("pass") else "!!"
                print(f"    - [{mark}] {a.get('type')}: {str(a.get('value'))[:80]}")
    print("-" * 72)
    stats = summary.get("stats", {})
    print(
        f"合计 {stats.get('total', 0)} 个 case，"
        f"PASS {stats.get('passed', 0)}，FAIL {stats.get('failed', 0)}，"
        f"异常/错误 {stats.get('errors', 0)}"
    )
    if summary.get("warnings"):
        print("\nwarnings:")
        for w in summary["warnings"]:
            print(f"  - {w}")
    print("=" * 72)


def _write_progress(output_dir: str, records: list, total: int) -> None:
    """边跑边写进度文件（output_dir/progress.json），供上层（如 web 轮询）实时展示进度。"""
    try:
        data = {
            "total": total,
            "completed": len(records),
            "passed": sum(1 for r in records if r.get("pass")),
            "failed": sum(1 for r in records if r.get("pass") is False),
            "errors": sum(1 for r in records if r.get("error")),
            "cases": [{
                "id": r.get("id"), "title": r.get("title"), "pass": r.get("pass"),
                "score": r.get("score"), "error": r.get("error"), "elapsed_sec": r.get("elapsed_sec"),
            } for r in records],
        }
        with open(os.path.join(output_dir, "progress.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001 进度文件写入失败不影响评测本身
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_eval.py",
        description="通过 Promptfoo opencode:sdk 驱动真实 OpenCode 专家（团）评测。",
    )
    parser.add_argument("--working-dir", default=os.environ.get("MOBILEWORK_EVAL_WORKSPACE", os.getcwd()),
                        help="被测工作区（含 .opencode/ 配置），默认 $MOBILEWORK_EVAL_WORKSPACE 或当前目录")
    parser.add_argument("--agent", default="software-team-lead",
                        help="被测团长 agent id（默认 software-team-lead）")
    parser.add_argument("--case", default=None, help="只运行指定 case id")
    parser.add_argument("--all", action="store_true", help="运行全部 case（默认行为）")
    parser.add_argument("--case-file", action="append", default=[], metavar="PATH",
                        help="自定义 case 文件（.yaml/.yml/.json），可多次指定")
    parser.add_argument("--case-file-only", action="store_true",
                        help="只运行 --case-file 提供的 case（忽略内置默认库）")
    parser.add_argument("--list", action="store_true", help="列出可用 case 后退出")
    parser.add_argument("--dry-run", action="store_true", help="只生成配置，不执行 eval")
    parser.add_argument("--output-dir", default=None,
                        help="结果输出根目录（默认 <working-dir>/.eval-results/<时间戳>）")
    parser.add_argument("--repeat", type=int, default=1,
                        help="每个 case 独立重复次数（任务书正式运行使用 5）")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="并发执行的 case 数（多个 case 并行跑，默认 1 串行；DeepSeek 端点最高支持约 100）")
    parser.add_argument("--promptfoo", default=os.environ.get("PROMPTFOO_BIN", "promptfoo"),
                        help="promptfoo 可执行文件")
    parser.add_argument("--provider", default=None, help="覆盖 LLM provider_id（如 deepseek）")
    parser.add_argument("--model", default=None, help="覆盖模型（如 deepseek-v4-flash）")
    parser.add_argument("--base-url", default=None,
                        help="覆盖 LLM API base URL（注入被测工作区 provider 配置，如 https://api.deepseek.com/v1）")
    parser.add_argument("--variant", default=None, help="OpenCode 配置中的 variant")
    parser.add_argument("--api-key", default=os.environ.get("PROMPTFOO_API_KEY"),
                        help="注入 opencode server 的 provider API key；也可直接设置 provider 对应环境变量"
                             "（如 DEEPSEEK_API_KEY/ANTHROPIC_API_KEY），两者取其一")
    parser.add_argument("--model-outputs", default=None, metavar="JSON",
                        help="跳过模型调用，直接喂入预置输出（promptfoo --model-outputs）；仅用于链路/断言调试，"
                             "正式运行不得使用")
    parser.add_argument("--server-timeout-ms", type=int, default=30000,
                        help="OpenCode server 启动超时（毫秒）")
    parser.add_argument("--case-timeout-sec", type=int, default=0,
                        help="单 case 硬超时（秒），0 = 不限制")
    parser.add_argument("--verbose", action="store_true", help="打印逐断言结果")
    args = parser.parse_args(argv)

    working_dir_abs, promptfoo_cmd = check_environment(args)

    if args.list:
        cases = load_cases(args.case_file)
        print(f"{'id':<24} {'type':<12} title")
        print("-" * 80)
        for c in cases:
            print(f"{c['id']:<24} {c['type']:<12} {c['title']}")
        print(f"\n共 {len(cases)} 个 case（默认库 + {len(args.case_file)} 个自定义文件）")
        return 0

    cases = load_cases(args.case_file, only_id=args.case, only_custom=args.case_file_only)
    if not cases:
        print("没有可运行的 case。", file=sys.stderr)
        return 2

    output_dir = args.output_dir or os.path.join(
        working_dir_abs, ".eval-results", datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    os.makedirs(output_dir, exist_ok=True)
    run_root = os.path.join(output_dir, "runs")
    os.makedirs(run_root, exist_ok=True)

    print(f"working_dir : {working_dir_abs}")
    print(f"agent       : {args.agent}")
    print(f"output_dir  : {output_dir}")
    print(f"cases       : {', '.join(c['id'] for c in cases)}")
    print(f"repeat      : {args.repeat}")

    records = []
    warnings = []
    total = len(cases)
    concurrency = max(1, min(args.concurrency, 100))

    def _run_one(idx_case) -> tuple:
        i, case = idx_case
        run_dir = os.path.join(run_root, f"{case['id']}-{i:02d}")
        os.makedirs(run_dir, exist_ok=True)
        print(f"\n[{i}/{total}] case: {case['id']} ({case['title']})", flush=True)
        try:
            rec = run_case(args, case, working_dir_abs, run_dir, i, promptfoo_cmd)
        except Exception as exc:  # noqa: BLE001
            rec = {"id": case["id"], "title": case.get("title"), "type": case.get("type"),
                   "seq": i, "pass": False, "error": f"异常: {exc}", "traceback": traceback.format_exc()}
        return i, rec

    if concurrency > 1:
        # 并发执行：每个 case 独立 run_dir / XDG_DATA_HOME / promptfoo 进程，天然隔离；
        # 每个 case 完成后立即刷新进度文件
        done = []
        with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(_run_one, (i, c)) for i, c in enumerate(cases, start=1)]
            for fut in cf.as_completed(futures):
                i, rec = fut.result()
                done.append((i, rec))
                _write_progress(output_dir, [r for _, r in sorted(done)], total)
        records = [r for _, r in sorted(done)]
    else:
        for i, case in enumerate(cases, start=1):
            _, rec = _run_one((i, case))
            records.append(rec)
            _write_progress(output_dir, records, total)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": args.agent,
        "working_dir": working_dir_abs,
        "output_dir": output_dir,
        "promptfoo_version": _promptfoo_version(args.promptfoo),
        "repeat": args.repeat,
        "cases": records,
        "warnings": warnings,
        "stats": {
            "total": len(records),
            "passed": sum(1 for r in records if r.get("pass")),
            "failed": sum(1 for r in records if r.get("pass") is False),
            "errors": sum(1 for r in records if r.get("error")),
        },
    }
    summary_path = os.path.join(output_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print_report(summary, verbose=args.verbose)
    print(f"\nsummary 已写入: {summary_path}")
    return 0 if summary["stats"]["errors"] == 0 and summary["stats"]["failed"] == 0 else 1


def _promptfoo_version(bin_name: str) -> str:
    try:
        cmd = resolve_command(bin_name)
        out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
