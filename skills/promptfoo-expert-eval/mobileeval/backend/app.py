"""MobileEval Flask 入口。"""
import os

from flask import Flask, jsonify, send_from_directory

from config import ensure_dirs, PROJECT_ROOT
from db import init_db

FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")


def create_app():
    ensure_dirs()
    init_db()
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False

    from api.tasks import tasks_bp
    from api.objects import objects_bp
    from api.runs import runs_bp
    from api.reports import reports_bp
    from api.reviews import reviews_bp
    from api.assistant import assistant_bp
    from api.cases import cases_bp
    from api.fs import fs_bp
    from api.uploads import uploads_bp
    from api.expert import expert_bp
    from api.experiments import experiments_bp
    from api.models_api import models_bp

    for bp in (tasks_bp, objects_bp, runs_bp, reports_bp, reviews_bp, assistant_bp,
               cases_bp, fs_bp, uploads_bp, expert_bp, experiments_bp, models_bp):
        app.register_blueprint(bp, url_prefix="/api")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "MobileEval"})

    # 生产环境：serve 前端构建产物（开发时前端用 Vite dev server + 代理）
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa(path):
        if os.path.isdir(FRONTEND_DIST):
            full = os.path.join(FRONTEND_DIST, path)
            if path and os.path.isfile(full):
                return send_from_directory(FRONTEND_DIST, path)
            return send_from_directory(FRONTEND_DIST, "index.html")
        return jsonify({"msg": "MobileEval backend running. 前端请用 Vite dev server（npm run dev）。"})

    return app


def _pid_exists(pid):
    """跨平台检查进程是否存在。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        except Exception:  # noqa: BLE001 检测失败时保守视为存活
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid(pid):
    """强制结束进程（Windows 用 taskkill，其余 kill -9）。"""
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=10)
        else:
            os.kill(pid, 9)
    except Exception:  # noqa: BLE001
        pass


def _lifecycle_watchdog(owner_pid, sibling_pids=(), check_interval=5):
    """生命周期守护：随 OpenWork 绑定。owner_pid（OpenWork 侧调用进程）退出后，
    先结束伴随进程（前端 Vite 等），再关闭本服务。"""
    import threading
    import time

    def _run():
        while True:
            time.sleep(check_interval)
            if not _pid_exists(owner_pid):
                for sp in sibling_pids:
                    _kill_pid(sp)
                os._exit(0)  # noqa: PLR1722 归属进程已退出，立即终止后端

    threading.Thread(target=_run, daemon=True).start()


def _parse_sibling_pids(env_val):
    out = []
    for part in (env_val or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


_owner = os.environ.get("MOBILEEVAL_LIFECYCLE_PID")
if _owner:
    try:
        _lifecycle_watchdog(int(_owner), _parse_sibling_pids(os.environ.get("MOBILEEVAL_SIBLING_PIDS")))
    except ValueError:
        pass


app = create_app()

if __name__ == "__main__":
    # 默认关闭 debug/Werkzeug 调试器（外部暴露时避免 RCE 面）；本地开发设 MOBILEEVAL_DEBUG=1
    debug = os.environ.get("MOBILEEVAL_DEBUG", "").strip().lower() in ("1", "true", "yes")
    port = int(os.environ.get("MOBILEEVAL_PORT", "7891"))
    app.run(host="127.0.0.1", port=port, debug=debug)
