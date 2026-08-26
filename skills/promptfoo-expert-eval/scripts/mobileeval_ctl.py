#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MobileEval 控制工具 —— 由 SKILL.md 驱动（OpenWork/Claude Code 均可调用）。

子命令：
  start      启动 MobileEval 后端 + 迁移数据库，输出网页 URL（OpenWork 内置浏览器打开）
  status     检查后端是否在运行
  run-eval   对某对象/任务发起一次完整评测（创建 run → 调 run_eval.py → 结果落库）
  import-summary  把已有 summary.json 落库（调试/补录用）

依赖：Python 3.10+；start 需要 flask（缺失时自动 pip install）；run-eval 需要 promptfoo/opencode CLI。
"""
import argparse
import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))  # .../mobilework-expert-eval-plugin（安装副本时为 ~/.agents/skills）
PROJECT_ROOT = os.path.dirname(PLUGIN_ROOT)                                   # 源码仓库同级（安装副本时此推导失效）


CONF_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), ".mobileeval-home.conf")  # skill 目录缓存
TEMPLATE_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "mobileeval")          # skill 内置项目模板
BOOTSTRAP_TARGET = os.path.join(os.path.expanduser("~"), "MobileEval")          # 新机器首次初始化位置


def _read_conf():
    try:
        with open(CONF_FILE, encoding="utf-8") as fh:
            p = fh.read().strip()
            return p if p and os.path.isdir(p) else None
    except OSError:
        return None


def _write_conf(root):
    try:
        with open(CONF_FILE, "w", encoding="utf-8") as fh:
            fh.write(root)
    except OSError:
        pass


def _search_ancestors():
    """从当前工作目录向上逐级找含 backend/app.py 的项目根（最多 6 级）。"""
    cur = os.getcwd()
    for _ in range(6):
        if os.path.isfile(os.path.join(cur, "backend", "app.py")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _bootstrap_project():
    """新机器自举：skill 内置项目模板首次使用时复制到用户目录。

    目标已存在项目则直接用用户的；复制失败则原地使用模板目录。
    """
    import shutil
    if not os.path.isfile(os.path.join(TEMPLATE_DIR, "backend", "app.py")):
        return None
    target = BOOTSTRAP_TARGET
    if os.path.isfile(os.path.join(target, "backend", "app.py")):
        return target
    try:
        os.makedirs(target, exist_ok=True)
        shutil.copytree(os.path.join(TEMPLATE_DIR, "backend"), os.path.join(target, "backend"),
                        dirs_exist_ok=True)
        shutil.copytree(os.path.join(TEMPLATE_DIR, "frontend"), os.path.join(target, "frontend"),
                        dirs_exist_ok=True)
        return target
    except Exception:  # noqa: BLE001 复制失败时原地使用模板（只读场景）
        return TEMPLATE_DIR if os.path.isfile(os.path.join(TEMPLATE_DIR, "backend", "app.py")) else None


def resolve_project_root():
    """自动定位 MobileEval 项目根（含 backend/app.py）。

    优先级：环境变量 MOBILEEVAL_HOME > 插件目录缓存 > 当前工作目录向上探测 > 插件仓库同级
    > skill 内置模板自举（新机器首次自动复制到用户目录）。全部失败才报错（不误建目录）。
    """
    candidates = []
    home = os.environ.get("MOBILEEVAL_HOME")
    if home:
        candidates.append(home)
    conf = _read_conf()
    if conf:
        candidates.append(conf)
    hit = _search_ancestors()
    if hit:
        candidates.append(hit)
    candidates.append(os.path.join(PROJECT_ROOT, "MobileEval"))
    boot = _bootstrap_project()
    if boot:
        candidates.append(boot)
    for cand in candidates:
        if cand and os.path.isfile(os.path.join(cand, "backend", "app.py")):
            _write_conf(cand)
            return cand
    raise RuntimeError(
        "无法定位 MobileEval 项目根（需包含 backend/app.py）。"
        "请设置环境变量 MOBILEEVAL_HOME 指向项目根，例如 C:\\project\\mobile_intern\\MobileEval")


MOBILEEVAL_DIR = os.environ.get("MOBILEEVAL_HOME") or os.path.join(PROJECT_ROOT, "MobileEval")
BACKEND_DIR = os.path.join(MOBILEEVAL_DIR, "backend")
RUNS_DIR = os.path.join(MOBILEEVAL_DIR, "eval-data", "runs")
APP_PY = os.path.join(BACKEND_DIR, "app.py")
RUN_EVAL_PY = os.path.join(SCRIPT_DIR, "run_eval.py")
PORT = int(os.environ.get("MOBILEEVAL_PORT", "7891"))
BASE_URL = f"http://127.0.0.1:{PORT}"

sys.path.insert(0, SCRIPT_DIR)
from db import get_db, init_db, jdumps, jloads, row_to_dict  # noqa: E402


# --------------------------------------------------------------------------- #
# 启动 / 状态
# --------------------------------------------------------------------------- #

def _flask_available():
    try:
        import flask  # noqa: F401
        return True
    except ImportError:
        return False


def _which(name):
    import shutil
    return shutil.which(name)


def _run_cmd(cmd, timeout=180):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"命令超时：{' '.join(cmd)[:120]}（>{timeout}s）") from None


def _install_flask():
    print("[deps] 未检测到 flask，自动安装…", file=sys.stderr)
    r = _run_cmd([sys.executable, "-m", "pip", "install", "flask"])
    if not _flask_available():
        raise RuntimeError(f"flask 安装失败：{r.stderr[-300:]}\n请手动执行：{sys.executable} -m pip install flask")
    return "flask 已自动安装"


def _install_npm_global(pkg, bin_name):
    if not _which("npm"):
        raise RuntimeError(f"未找到 npm，无法自动安装 {pkg}；请先安装 Node.js 18+")
    print(f"[deps] 未检测到 {bin_name}，自动安装 {pkg}…", file=sys.stderr)
    r = _run_cmd([_which("npm"), "install", "-g", pkg])
    if not _which(bin_name):
        raise RuntimeError(f"{pkg} 安装失败：{r.stderr[-300:]}")
    return f"{pkg} 已自动安装"


def ensure_deps(args=None):
    """检测并自动安装运行所需依赖：

    - flask（Python，网页后端）—— 缺失时 pip install
    - promptfoo（CLI，评测执行）—— 缺失时 npm install -g promptfoo
    - opencode（CLI，opencode:sdk provider）—— 缺失时 npm install -g opencode-ai
    """
    done = []
    if not _flask_available():
        done.append(_install_flask())
    else:
        done.append("flask 已就绪")
    if not _which("promptfoo"):
        done.append(_install_npm_global("promptfoo", "promptfoo"))
    else:
        done.append("promptfoo 已就绪")
    if not _which("opencode"):
        done.append(_install_npm_global("opencode-ai", "opencode"))
    else:
        done.append("opencode 已就绪")
    return {"status": "ok", "deps": done}


def _is_mobileeval(port):
    """端口上是否已是 MobileEval 服务（健康检查返回 service=MobileEval）。"""
    try:
        import json as _json
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
            if resp.status != 200:
                return False
            try:
                return _json.loads(resp.read().decode("utf-8")).get("service") == "MobileEval"
            except Exception:  # noqa: BLE001
                return False
    except Exception:
        return False


def _port_free(port):
    """端口是否可被绑定（未被任何进程占用）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _port_owner_pid(port):
    """返回占用端口的监听进程 PID（无则 None）。"""
    if os.name == "nt":
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                                 capture_output=True, text=True, timeout=10,
                                 encoding="utf-8", errors="replace").stdout or ""
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] in ("LISTENING", "LISTEN"):
                    try:
                        return int(parts[-1])
                    except ValueError:
                        return None
        except Exception:  # noqa: BLE001
            pass
        return None
    # Linux/macOS
    try:
        out = subprocess.run(["lsof", "-t", f"-i:{port}"],
                             capture_output=True, text=True, timeout=10).stdout or ""
        for pid in out.split():
            if pid.strip().isdigit():
                return int(pid.strip())
    except Exception:  # noqa: BLE001
        pass
    return None


def _kill_pid(pid):
    """强制结束进程（Windows 用 taskkill，其余用 kill -9）。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    else:
        os.kill(pid, 9)


def ensure_port_free(port=PORT):
    """确保端口可用：被占用则结束占用进程并等待释放。返回是否清理过。"""
    if _port_free(port):
        return False
    # 占用者是 MobileEval 自身（健康实例）→ 直接复用，不杀
    if _is_mobileeval(port):
        return False
    owner = _port_owner_pid(port)
    if owner:
        print(f"[port] 端口 {port} 被进程 {owner} 占用，正在结束该进程…", file=sys.stderr)
        _kill_pid(owner)
        for _ in range(10):
            time.sleep(0.5)
            if _port_free(port):
                return True
        raise RuntimeError(f"端口 {port} 的占用进程 {owner} 未能结束，请手动释放")
    raise RuntimeError(f"端口 {port} 被占用但找不到占用进程，请手动释放")


def is_running(port=PORT):
    return _is_mobileeval(port)


def _ensure_project():
    """需要 backend/runs 的命令先定位项目根（支持 MOBILEEVAL_HOME）。"""
    global MOBILEEVAL_DIR, BACKEND_DIR, RUNS_DIR
    root = resolve_project_root()
    MOBILEEVAL_DIR = root
    BACKEND_DIR = os.path.join(root, "backend")
    RUNS_DIR = os.path.join(root, "eval-data", "runs")


def _ensure_frontend_dist(project_root):
    """确保前端构建产物存在：dist/index.html 缺失时自动用源码打包（npm install + build）。

    返回 dist 目录是否可用；前端源码缺失时返回 True（只跑后端，页面不可用）。
    """
    fe_dir = os.path.join(project_root, "frontend")
    dist = os.path.join(fe_dir, "dist")
    if os.path.isfile(os.path.join(dist, "index.html")):
        return True
    if not os.path.isfile(os.path.join(fe_dir, "package.json")):
        print("[frontend] 前端源码缺失，仅提供后端 API（页面不可用）", file=sys.stderr)
        return True
    npm = _which("npm")
    if not npm:
        raise RuntimeError("未找到 npm，无法构建前端（请安装 Node.js 18+）")
    if not os.path.isdir(os.path.join(fe_dir, "node_modules")):
        print(f"[frontend] 首次运行，安装前端依赖（约 1-2 分钟）…", file=sys.stderr)
        r = subprocess.run([npm, "install"], cwd=fe_dir, capture_output=True, text=True,
                           timeout=600)
        if r.returncode != 0 or not os.path.isdir(os.path.join(fe_dir, "node_modules")):
            raise RuntimeError(f"npm install 失败：{r.stderr[-300:]}")
    print("[frontend] 未检测到构建产物，自动打包源码（npm run build）…", file=sys.stderr)
    r = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "run", "build"],
                       cwd=fe_dir, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.isfile(os.path.join(dist, "index.html")):
        raise RuntimeError(f"前端构建失败：{r.stderr[-300:]}")
    return True


def _start_backend(port=PORT):
    """确保服务已启动（复用/占清理/装依赖/迁移库/构建前端）。单进程：Flask 7891 同时提供 API 与网页。"""
    _ensure_project()
    if is_running(port):
        return True
    _ensure_frontend_dist(MOBILEEVAL_DIR)
    ensure_port_free(port)
    ensure_deps()
    # 数据库迁移（幂等；仅需 sqlite，不依赖 flask）
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, '.'); from db import init_db; init_db()"],
                       cwd=BACKEND_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"数据库初始化失败：{r.stderr[-300:]}")
    # 启动后端（独立进程，Windows 下不弹窗）。常驻模式：不绑定调用进程生命周期
    # （OpenWork 工具调用是独立 shell，命令返回 shell 即退，绑定会导致服务被误杀）。
    # 注入 MOBILEEVAL_PLUGIN：指向本 skill 真实目录，使后端能定位 expert_tools.py/run_eval.py
    # （workspace-local 部署时，bootstrap 把 mobileeval/ 复制到用户目录，原有 vendor/fallback 路径失效）。
    plugin_dir = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
    env = dict(os.environ, MOBILEEVAL_PORT=str(port), MOBILEEVAL_PLUGIN=plugin_dir)
    # 注入 AI 凭据：从数据库 models 表读取默认模型（用户在网页配置的 deepseek key），
    # 供 expert_tools.py 的 AI 生成路径（分析/生成 case/建议）使用。
    # 该路径走 Anthropic 兼容端点，DeepSeek 用 https://api.deepseek.com/anthropic + deepseek-chat。
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT provider, model, base_url, api_key FROM models WHERE is_default=1 "
                "OR id=(SELECT MIN(id) FROM models) ORDER BY is_default DESC LIMIT 1").fetchone()
            if row and row["api_key"]:
                if (row["provider"] or "deepseek").lower() == "deepseek":
                    env["DEEPSEEK_API_KEY"] = row["api_key"]
                    # 注意：DB 里的 base_url（如 https://api.deepseek.com）是 OpenAI 兼容端点，
                    # 而 AI 生成路径走 Anthropic SDK，必须用 DeepSeek 的 Anthropic 兼容端点。
                    env["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com/anthropic"
                    # DeepSeek Anthropic 兼容端点的标准模型名为 deepseek-chat/deepseek-reasoner
                    env["DEEPSEEK_MODEL"] = row["model"] if row["model"] in (
                        "deepseek-chat", "deepseek-reasoner") else "deepseek-chat"
                else:
                    env["ANTHROPIC_API_KEY"] = row["api_key"]
                    if row["base_url"]:
                        env["ANTHROPIC_BASE_URL"] = row["base_url"]
                    if row["model"]:
                        env["ANTHROPIC_MODEL"] = row["model"]
        finally:
            conn.close()
    except Exception as _e:  # noqa: BLE001 读不到模型配置不阻断启动，仅跳过凭据注入
        print(f"[warn] 未能从数据库读取模型凭据注入环境：{_e}", file=sys.stderr)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([sys.executable, "app.py"], cwd=BACKEND_DIR, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    for _ in range(30):
        time.sleep(0.5)
        if is_running(port):
            return True
    raise RuntimeError("后端启动超时，请查看 eval-data/ 下的日志或手动执行 python app.py 排查")


def cmd_start(args):
    # 固定端口 7891：已运行的 MobileEval 直接复用；其他进程占用则先结束再启动。
    # 服务为常驻模式（不绑定调用进程生命周期）：OpenWork 的工具调用是独立 shell，
    # 命令返回后 shell 即退出，绑定会导致服务被误杀。重复调用直接复用，无需重启。
    if is_running(PORT):
        return {"status": "already_running", "url": f"http://127.0.0.1:{PORT}", "port": PORT,
                "options": _START_OPTIONS}
    _start_backend(PORT)
    return {"status": "started", "url": f"http://127.0.0.1:{PORT}", "port": PORT,
            "note": "服务常驻运行；重复 start 会复用；用 stop 命令停止",
            "options": _START_OPTIONS}


_START_OPTIONS = [
    {"key": "1", "label": "打开评测中心页面", "action": "在 OpenWork 内置浏览器打开 http://127.0.0.1:7891",
     "default": True},
    {"key": "2", "label": "继续评测流程", "action": "list-models 检查模型 → list-objects 确认对象 → 生成/审核 case → run-eval"},
    {"key": "3", "label": "停止服务", "action": "mobileeval_ctl.py stop"},
]


def cmd_stop(args):
    """停止常驻评测中心：结束 7891 上的 MobileEval 进程。"""
    import json as _json
    import urllib.request
    # 1) 若是 MobileEval 自身，先请求优雅退出接口（如有）
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2) as resp:
            if resp.status == 200:
                try:
                    _json.loads(resp.read().decode("utf-8")).get("service") == "MobileEval"
                except Exception:
                    pass
    except Exception:
        pass
    # 2) 找占用进程并结束
    owner = _port_owner_pid(PORT)
    if owner:
        _kill_pid(owner)
        for _ in range(10):
            time.sleep(0.5)
            if _port_free(PORT):
                return {"status": "stopped", "port": PORT, "killed_pid": owner}
        raise RuntimeError(f"进程 {owner} 未能结束")
    if not _port_free(PORT):
        raise RuntimeError("7891 被占用但找不到占用进程，请手动释放")
    return {"status": "stopped", "port": PORT, "note": "7891 未被占用（服务未在运行）"}


# --------------------------------------------------------------------------- #
# 打开页面（OpenWork 内置浏览器跳转）
# --------------------------------------------------------------------------- #

PAGE_ROUTES = {
    "objects": "/objects",
    "object": "/objects/{object_id}",
    "report": "/runs/{run_id}",
    "versions": "/objects/{object_id}/versions",
    "experiments": "/objects/{object_id}/experiments",
    "optimize": "/objects/{object_id}/optimize",
    "compare": "/compare/{object_id}",
}

PAGE_DOC = {
    "objects": "全部专家/专家团列表（--db-path）",
    "object": "评测中心：用例/评测记录（--object-id）",
    "report": "评测报告（--run-id）",
    "versions": "版本历史（--object-id）",
    "experiments": "对照实验（--object-id）",
    "optimize": "迭代优化（--object-id）",
    "compare": "优化对比报告（--object-id --base --opt，opt 可后补）",
}


def cmd_open(args):
    """调用页面 CLI：确保后端启动 → 返回对应路由的 URL（OpenWork 内置浏览器打开）。"""
    route = PAGE_ROUTES.get(args.page)
    if not route:
        raise RuntimeError(f"未知页面 {args.page}，可用：{', '.join(PAGE_ROUTES)}")
    params = {"object_id": args.object_id,
              "run_id": args.run_id, "base": args.base}
    missing = [ph for ph in ("object_id", "run_id", "base")
               if "{" + ph + "}" in route and not params.get(ph)]
    if missing:
        raise RuntimeError(f"页面 {args.page} 需要参数：{', '.join(missing)}")
    path = route.format(**params)
    port = args.port or PORT
    _start_backend(port)
    query = ""
    if args.page == "compare":
        if args.base:
            query += f"?base={args.base}"
            if args.opt:
                query += f"&opt={args.opt}"
    url = f"http://127.0.0.1:{port}{path}{query}"
    return {"status": "ok", "page": args.page, "url": url,
            "hint": "在 OpenWork 内置浏览器打开该地址"}


def cmd_status(args):
    return {"status": "running" if is_running(PORT) else "stopped",
            "url": f"http://127.0.0.1:{PORT}", "port": PORT}


# --------------------------------------------------------------------------- #
# 评测执行（run-eval）
# --------------------------------------------------------------------------- #

def _sanitize_output_dir(od, fallback):
    od = (od or "").strip().replace("\\", "/")
    if not od or od.startswith("/") or ":" in od or ".." in od.split("/"):
        return fallback
    return od


def write_cases_file(object_id, out_dir, db_path=None, task_id=None):
    """把对象审核通过的 cases 写入临时 case 文件，返回 (文件路径, case 数量)。

    task_id 非空时只取该任务下的 approved cases（run-eval --task-id 语义）；
    为空时取对象全部 approved cases（兼容旧调用）。
    """
    init_db(db_path)
    conn = get_db(db_path)
    try:
        if task_id is not None:
            rows = conn.execute(
                "SELECT * FROM cases WHERE object_id=? AND task_id=? AND status='approved' ORDER BY id",
                (object_id, task_id)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cases WHERE object_id=? AND status='approved' ORDER BY id",
                (object_id,)).fetchall()
    finally:
        conn.close()
    cases = []
    for row in rows:
        r = dict(row)
        ctype = r.get("type") or "hybrid"
        if ctype == "open_ended":
            ctype = "open-ended"
        fallback_od = f"eval-runs/{{run_id}}/case-{r['id']}"
        cases.append({
            "id": r.get("case_id") or f"case-{r['id']}",
            "title": r.get("title") or "",
            "type": ctype,
            "description": "",
            "prompt": r.get("prompt") or "",
            "output_dir": _sanitize_output_dir(r.get("output_dir"), fallback_od),
            "assertions": jloads(r.get("assertions")) or [],
        })
    if not cases:
        return None, 0
    path = os.path.join(out_dir, "cases-approved.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, ensure_ascii=False, indent=2)
    return path, len(cases)


def _persist_results(run_id, run_dir, summary, rc, db_path=None):
    init_db(db_path)
    conn = get_db(db_path)
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
        passed = sum(1 for c in cases if c.get("pass") is True)
        failed = sum(1 for c in cases if c.get("pass") is False)
        errors = sum(1 for c in cases if c.get("error"))
        scores = [c.get("score") for c in cases if isinstance(c.get("score"), (int, float))]
        score = sum(scores) / len(scores) if scores else (1.0 if passed == total and total else 0.0)
        session_ids = []
        for c in cases:
            sids = c.get("session_ids") or []
            session_ids.extend(sids)
            conn.execute(
                """INSERT INTO case_results
                   (run_id, case_id, case_title, case_type, pass, score,
                    output_length, error, output_preview, assertions, session_ids, token_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, c.get("id", ""), c.get("title", ""), c.get("type", ""),
                 1 if c.get("pass") is True else 0,
                 c.get("score"), c.get("output_length", 0),
                 c.get("error") or "", c.get("output_preview") or "",
                 jdumps(c.get("assertions") or []), jdumps(sids),
                 c.get("token_count") or 0))
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


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _resolve_run_params(args, obj):
    """解析一次评测的完整参数（与 web 发起评测弹窗一致）。

    返回 dict：object_id/name/agent/version/model_id/model_name/provider/model/base_url/
    repeat/concurrency/agent_on/experiment_id/variant/approved_cases/api_key。
    """
    init_db(args.db_path)
    conn = get_db(args.db_path)
    try:
        concurrency = max(1, min(args.concurrency, 100))
        agent_on = 0 if str(getattr(args, "agent_on", 1)) == "0" else 1
        version = getattr(args, "version", None) or f"v{obj.get('current_version') or 1}"
        provider = args.provider or obj.get("provider") or "deepseek"
        model = args.model or obj.get("model") or "deepseek-v4-flash"
        base_url = obj.get("base_url") or ""
        model_id = getattr(args, "model_id", None)
        model_name = ""
        api_key = os.environ.get("OPENCODE_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("PROMPTFOO_API_KEY")
        if model_id:
            mrow = row_to_dict(conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone())
            if not mrow:
                raise RuntimeError(f"评测模型 {model_id} 不存在（models 表）")
            provider = mrow.get("provider") or provider
            model = mrow.get("model") or model
            base_url = mrow.get("base_url") or ""
            model_name = mrow.get("name") or ""
            if mrow.get("api_key"):
                api_key = mrow["api_key"]
        approved_cases = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE object_id=? AND status='approved'",
            (args.object_id,)).fetchone()[0]
        return {
            "object_id": args.object_id,
            "name": obj.get("name"),
            "agent": (obj.get("agent_name") or "software-team-lead") if agent_on else "build（无专家 baseline）",
            "version": version,
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "model": model,
            "base_url": base_url or "（provider 默认端点）",
            "repeat": max(1, args.repeat),
            "concurrency": concurrency,
            "agent_on": agent_on,
            "experiment_id": getattr(args, "experiment_id", None),
            "variant": getattr(args, "variant", None) or "",
            "approved_cases": approved_cases,
            "api_key_set": bool(api_key),
        }
    finally:
        conn.close()


def cmd_run_eval(args):
    """对对象发起完整评测（去 task 层）：创建 run（实验记录）→ 写 case 文件 → 调 run_eval.py → 落库。

    --dry-run：只解析并打印将使用的完整参数（供展示给用户确认），不创建 run、不执行。
    """
    init_db(args.db_path)
    conn = get_db(args.db_path)
    try:
        obj = row_to_dict(conn.execute("SELECT * FROM objects WHERE id=?", (args.object_id,)).fetchone())
        if not obj:
            raise RuntimeError(f"对象 {args.object_id} 不存在")
        p = _resolve_run_params(args, obj)
        if getattr(args, "dry_run", False):
            return {"status": "preview",
                    "hint": "以上为本次评测将使用的参数，用户确认后再执行 run-eval",
                    "params": p,
                    "options": [
                        {"key": "1", "label": "确认发起评测",
                         "action": "去掉 --dry-run 重新执行 run-eval（参数与本预览一致）",
                         "default": True},
                        {"key": "2", "label": "修改参数",
                         "action": "用户指定 model-id/version/agent-on/repeat/concurrency/experiment 后重跑 dry-run"},
                        {"key": "3", "label": "取消", "action": "本次不发起评测"},
                    ]}
        concurrency = p["concurrency"]
        agent_on = p["agent_on"]
        version = p["version"]
        provider = p["provider"]
        model = p["model"]
        base_url = p["base_url"]
        model_id = p["model_id"]
        # 正式执行时重新取 api_key（预览不返回明文）：models 表 > 环境变量
        api_key = os.environ.get("OPENCODE_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("PROMPTFOO_API_KEY")
        if model_id:
            mrow = row_to_dict(conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone())
            if mrow and mrow.get("api_key"):
                api_key = mrow["api_key"]
        cur = conn.execute(
            """INSERT INTO runs (task_id, object_id, status, provider, model, base_url, model_id,
               repeat, concurrency, version, agent_on, experiment_id, variant)
               VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (args.object_id, "running", provider, model, base_url, model_id,
             max(1, args.repeat), concurrency, version, agent_on,
             p["experiment_id"], p["variant"]))
        conn.commit()
        run_id = cur.lastrowid
        run_dir = os.path.join(RUNS_DIR, str(run_id))
        os.makedirs(run_dir, exist_ok=True)
    finally:
        conn.close()

    workspace = obj["workspace_dir"] or ""
    if not workspace or not os.path.isdir(workspace):
        raise RuntimeError(f"对象工作区不存在：{workspace}")
    case_file, total = write_cases_file(args.object_id, run_dir, args.db_path)
    if not case_file or total == 0:
        # 失败：无 approved case，标记 run 失败
        conn = get_db(args.db_path)
        try:
            conn.execute("UPDATE runs SET status='error', error=? WHERE id=?",
                         ("该对象没有审核通过的 case，请先生成并审核用例", run_id))
            conn.commit()
        finally:
            conn.close()
        raise RuntimeError("该对象没有审核通过的 case，请先生成并审核用例（generate-cases + review-cases）")
    # promptfoo opencode:sdk provider 需要 apiKey 才能启动 opencode server；
    # 优先级：全局模型(api_key) > 环境变量 OPENCODE_API_KEY/DEEPSEEK_API_KEY/PROMPTFOO_API_KEY
    agent = (obj.get("agent_name") or "software-team-lead") if agent_on else "build"
    cmd = [sys.executable, RUN_EVAL_PY,
           f"--working-dir={workspace}",
           f"--agent={agent}",
           f"--output-dir={run_dir}",
           f"--repeat={max(1, args.repeat)}",
           f"--concurrency={concurrency}",
           "--verbose"]
    if api_key:
        cmd.append(f"--api-key={api_key}")
    if provider:
        cmd.append(f"--provider={provider}")
    if model:
        cmd.append(f"--model={model}")
    if case_file:
        cmd += ["--case-file", case_file, "--case-file-only"]
    else:
        cmd += ["--all"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # OpenWork 运行时会在环境里设置 OPENCODE_SERVER_USERNAME/OPENCODE_SERVER_PASSWORD
    # （用于 OpenWork 自己的 opencode server Basic Auth）。promptfoo spawn 新的 opencode server
    # 时会继承这些变量，导致新 server 也启用 Basic Auth，而 promptfoo SDK 客户端不携带凭据，
    # session.create 返回 401（报 "Failed to get session ID from OpenCode SDK response"）。
    # 这里从评测子进程环境中剥离这些 OpenWork 专属变量，恢复无认证的评测链路。
    for _k in ("OPENCODE_SERVER_USERNAME", "OPENCODE_SERVER_PASSWORD", "OPENCODE_PID"):
        env.pop(_k, None)
    # promptfoo 的 opencode:sdk provider 会 spawn opencode CLI 并动态加载 @opencode-ai/sdk。
    # SDK 与 CLI 版本必须匹配（当前 promptfoo 自带 SDK 1.18.11）；而 OpenWork 自带的 sidecar
    # opencode 1.17.11 在 PATH 中更靠前，会导致 SDK 与 server 版本不兼容（session.create 失败）。
    # 这里把 nvm4w（opencode 1.18.x）的目录前移到 sidecar 之前，确保 spawn 到匹配版本。
    NVM4W_BIN = r"C:\nvm4w\nodejs"
    current_path = env.get("PATH", "")
    entries = [p for p in current_path.split(";") if p]
    nvm_entries = [p for p in entries if p.lower().startswith(NVM4W_BIN.lower())]
    other_entries = [p for p in entries if not p.lower().startswith(NVM4W_BIN.lower())]
    env["PATH"] = ";".join(nvm_entries + other_entries)
    log_path = os.path.join(run_dir, "eval.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace", env=env)
    rc = proc.returncode
    summary = None
    sp = os.path.join(run_dir, "summary.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as fh:
            summary = json.load(fh)
    _persist_results(run_id, run_dir, summary, rc, args.db_path)
    if summary:
        return {"run_id": run_id, "status": summary.get("stats"),
                "exit_code": rc, "url": f"http://127.0.0.1:{PORT}/runs/{run_id}"}
    return {"run_id": run_id, "error": f"未生成 summary.json（退出码 {rc}）", "exit_code": rc,
            "log": log_path}


def cmd_import_summary(args):
    sp = os.path.join(RUNS_DIR, str(args.run_id), "summary.json")
    if not os.path.exists(sp):
        raise RuntimeError(f"不存在 {sp}")
    with open(sp, encoding="utf-8") as fh:
        summary = json.load(fh)
    _persist_results(args.run_id, os.path.dirname(sp), summary, 0, args.db_path)
    return {"run_id": args.run_id, "status": "imported"}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(prog="mobileeval_ctl", description="MobileEval 控制工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("start", help="检测并安装依赖，启动 MobileEval 后端并输出网页 URL（随调用进程生命周期退出）")
    p_s.add_argument("--port", type=int, default=PORT)

    p_d = sub.add_parser("deps", help="检测并自动安装运行依赖（flask/promptfoo/opencode）")

    p_st = sub.add_parser("status", help="检查后端是否在运行")
    p_st.add_argument("--port", type=int, default=PORT)

    p_sp = sub.add_parser("stop", help="停止常驻评测中心（结束 7891 上的 MobileEval 进程）")
    p_sp.add_argument("--port", type=int, default=PORT)

    p_r = sub.add_parser("run-eval", help="对对象发起完整评测（创建 run 实验记录 + 执行 + 落库）")
    p_r.add_argument("--object-id", type=int, required=True)
    p_r.add_argument("--version", default=None, help="专家版本标签（默认对象当前版本 vN）")
    p_r.add_argument("--agent-on", type=int, default=1, help="1=启用专家团（默认）；0=无专家 baseline")
    p_r.add_argument("--repeat", type=int, default=1)
    p_r.add_argument("--concurrency", type=int, default=1)
    p_r.add_argument("--provider", default=None)
    p_r.add_argument("--model", default=None)
    p_r.add_argument("--model-id", type=int, default=None, help="全局评测模型 id（models 表，含 api_key/base_url）")
    p_r.add_argument("--experiment-id", type=int, default=None, help="关联对照实验（可选）")
    p_r.add_argument("--variant", default=None, help="实验 variant 标签（可选）")
    p_r.add_argument("--dry-run", action="store_true",
                     help="只解析并打印本次评测将使用的完整参数（供展示给用户确认），不创建 run、不执行")
    p_r.add_argument("--db-path", default=None)

    p_i = sub.add_parser("import-summary", help="把已有 summary.json 落库（补录）")
    p_i.add_argument("--run-id", type=int, required=True)
    p_i.add_argument("--db-path", default=None)

    p_o = sub.add_parser("open", help="打开网页页面（启动后端并返回对应路由 URL，在 OpenWork 内置浏览器打开）")
    p_o.add_argument("--page", required=True, choices=sorted(PAGE_ROUTES),
                     help=f"目标页面：{', '.join(PAGE_ROUTES)}")
    p_o.add_argument("--object-id", type=int, default=None)
    p_o.add_argument("--task-id", type=int, default=None)
    p_o.add_argument("--run-id", type=int, default=None)
    p_o.add_argument("--base", type=int, default=None)
    p_o.add_argument("--opt", type=int, default=None)
    p_o.add_argument("--port", type=int, default=PORT)

    args = ap.parse_args(argv)
    # start/open/run-eval/import-summary 依赖项目根（backend/app.py 与 runs 目录）
    if args.cmd in ("start", "open", "run-eval", "import-summary"):
        _ensure_project()
    if args.cmd == "start":
        out = cmd_start(args)
    elif args.cmd == "deps":
        out = ensure_deps()
    elif args.cmd == "status":
        out = cmd_status(args)
    elif args.cmd == "stop":
        out = cmd_stop(args)
    elif args.cmd == "run-eval":
        out = cmd_run_eval(args)
    elif args.cmd == "import-summary":
        out = cmd_import_summary(args)
    elif args.cmd == "open":
        out = cmd_open(args)
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
