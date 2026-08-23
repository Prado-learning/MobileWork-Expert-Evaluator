"""MobileEval 配置。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# 数据目录
DATA_DIR = os.environ.get("MOBILEEVAL_DATA", os.path.join(PROJECT_ROOT, "eval-data"))
RUNS_DIR = os.path.join(DATA_DIR, "runs")
DB_PATH = os.environ.get("MOBILEEVAL_DB", os.path.join(DATA_DIR, "mobileeval.db"))

# 评测插件（mobilework-expert-eval-plugin）路径：
# 优先 MOBILEEVAL_PLUGIN 环境变量（由 mobileeval_ctl.py start 注入 skill 真实目录）；
# 其次项目内 vendor（Windows junction 链接，单一来源不复制）；缺失时回退上级目录。
# 兜底：当三者均不存在时，回退到"本 backend 同级"的 skill 目录结构
# （workspace-local 部署时，skill 就在 .../skills/promptfoo-expert-eval/，
#  而 backend 被 bootstrap 复制到 MobileEval/backend，故从启动目录向上找含 skills/ 的位置）。
def _resolve_plugin_dir():
    env = os.environ.get("MOBILEEVAL_PLUGIN")
    if env and os.path.isdir(env):
        return env
    vendor = os.path.join(PROJECT_ROOT, "vendor", "mobilework-expert-eval-plugin")
    if os.path.isdir(vendor):
        return vendor
    fallback = os.path.normpath(os.path.join(PROJECT_ROOT, "..", "mobilework-expert-eval-plugin"))
    if os.path.isdir(fallback):
        return fallback
    # 兜底：从 BASE_DIR 向上探测含 skills/promptfoo-expert-eval/scripts/expert_tools.py 的目录
    cur = BASE_DIR
    for _ in range(6):
        cand = os.path.join(cur, "skills", "promptfoo-expert-eval")
        if os.path.isfile(os.path.join(cand, "scripts", "expert_tools.py")):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return fallback  # 最终回退（路径可能无效，但保留原行为以便报错定位）


PLUGIN_DIR = _resolve_plugin_dir()


def _script_path(name):
    """自适应定位插件脚本：兼容两种部署形态。

    - 插件外层目录：PLUGIN_DIR/skills/promptfoo-expert-eval/scripts/<name>
    - workspace-local skill 目录（MOBILEEVAL_PLUGIN 直接指向 skill 目录）：
      PLUGIN_DIR/scripts/<name>
    """
    as_outer = os.path.join(PLUGIN_DIR, "skills", "promptfoo-expert-eval", "scripts", name)
    if os.path.isfile(as_outer):
        return as_outer
    as_skill = os.path.join(PLUGIN_DIR, "scripts", name)
    return as_skill


RUN_EVAL_PY = _script_path("run_eval.py")
EXPERT_TOOLS_PY = _script_path("expert_tools.py")

# 默认评测工作区（权限已适配非交互；被测专家包只读）
DEFAULT_WORKSPACE = os.path.normpath(os.path.join(
    PROJECT_ROOT, "..", "workspaces", "test01-eval"))
DEFAULT_AGENT = "software-team-lead"

# 模型凭据
# 评测执行：promptfoo opencode:sdk 需要 --api-key（deepseek 不在其 env 映射表）
# AI 助手（评测解读/建议）：Anthropic 兼容端点；未配置 ANTHROPIC_API_KEY 时回退 DeepSeek 兼容端点
def resolve_model_credentials():
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or _registry_env("ANTHROPIC_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY") or _registry_env("DEEPSEEK_API_KEY")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if anthropic_key:
        return {"api_key": anthropic_key, "base_url": base_url, "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")}
    if deepseek_key:
        # DeepSeek 提供 Anthropic 兼容端点
        return {"api_key": deepseek_key,
                "base_url": "https://api.deepseek.com/anthropic",
                "model": os.environ.get("ANTHROPIC_MODEL", "deepseek-chat")}
    return None


def resolve_eval_key():
    """评测执行用的 provider api key（DEEPSEEK_API_KEY）。"""
    return os.environ.get("DEEPSEEK_API_KEY") or _registry_env("DEEPSEEK_API_KEY")


def _registry_env(name):
    """Windows 用户级注册表环境变量（当前 shell 未继承时）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
            v, _ = winreg.QueryValueEx(k, name)
            return v
    except Exception:  # noqa: BLE001
        return None


def ensure_dirs():
    os.makedirs(RUNS_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "artifacts"), exist_ok=True)


# --------------------------------------------------------------------------- #
# 文件访问边界（安全）：
# 用户/模型能触达的文件范围 = 默认评测工作区 + 已登记对象的工作区（含上传副本）。
# 任何用户可控的路径参数（如工具的 workspace_dir、fs 浏览）都必须落在该集合内，
# 防止"外界用户引导 Claude 读取/浏览工作区之外的文件"。
# --------------------------------------------------------------------------- #

def allowed_workspace_dirs():
    """允许访问的评测工作区根目录集合（realpath 规范化去重）。

    基准 = eval-data（上传副本/uploads、评测产物/runs、artifacts）+ 默认工作区的父目录（workspaces/），
    再并入已登记对象的工作区。评测工作区必须位于这两个根之下，防止对象接口注入任意路径放大白名单。
    """
    dirs = {os.path.realpath(DATA_DIR)}
    dirs.add(os.path.realpath(os.path.dirname(DEFAULT_WORKSPACE)))  # workspaces/
    try:
        from db import get_db
        conn = get_db()
        try:
            for (ws,) in conn.execute(
                    "SELECT workspace_dir FROM objects WHERE workspace_dir IS NOT NULL AND workspace_dir != ''").fetchall():
                dirs.add(os.path.realpath(ws))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001（库不可用时至少保留基准）
        pass
    return dirs


def is_allowed_workspace(path):
    """判断给定路径是否落在允许集合内（realpath 后前缀匹配，防 ../ 穿越）。"""
    if not path:
        return False
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return any(real == d or real.startswith(d + os.sep) for d in allowed_workspace_dirs())


def fs_browse_allowed():
    """fs 浏览是否放开到任意目录（默认 False=限制在允许工作区内；本地管理员可设 1 放开）。"""
    return os.environ.get("MOBILEEVAL_FS_BROWSE_ALL", "0").strip() in ("1", "true", "yes")
