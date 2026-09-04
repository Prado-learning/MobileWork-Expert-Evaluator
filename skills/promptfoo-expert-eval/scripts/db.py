#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插件侧 SQLite 数据层：连接、建表、迁移。

MobileEval 评测数据统一存在 SQLite（默认 <MobileEval 项目>/eval-data/mobileeval.db）。
插件工具（expert_tools.py / run_eval.py / 启动器）直接读写该库，不依赖 MobileEval 后端运行。

DB 路径解析优先级：
1. 显式参数 --db-path
2. 环境变量 MOBILEEVAL_DB
3. 默认：插件仓库同级目录下的 MobileEval/eval-data/mobileeval.db
"""

import json
import os
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))        # .../skills/promptfoo-expert-eval/scripts
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))  # .../mobilework-expert-eval-plugin
PROJECT_ROOT = os.path.dirname(PLUGIN_ROOT)                    # .../mobile_intern
DEFAULT_DB = os.path.join(PROJECT_ROOT, "MobileEval", "eval-data", "mobileeval.db")


def _search_ancestors():
    """从当前工作目录向上逐级找含 eval-data/mobileeval.db 的项目根（最多 6 级）。"""
    cur = os.getcwd()
    for _ in range(6):
        if os.path.isfile(os.path.join(cur, "eval-data", "mobileeval.db")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _read_conf():
    """读项目根缓存。用户主目录 .mobileeval-home.conf 优先；兼容技能目录旧缓存（只读，不写技能目录）。"""
    for conf in (os.path.join(os.path.expanduser("~"), ".mobileeval-home.conf"),
                 os.path.join(os.path.dirname(SCRIPT_DIR), ".mobileeval-home.conf")):
        try:
            with open(conf, encoding="utf-8") as fh:
                p = fh.read().strip()
                if p and os.path.isfile(os.path.join(p, "eval-data", "mobileeval.db")):
                    return p
        except OSError:
            continue
    return None


def resolve_project_home(path=None):
    """从权威数据库路径反推 MobileEval 项目根（数据库位于 <根>/eval-data/mobileeval.db）。

    与 resolve_db 同源：确保工作区/快照/评测产物都落在 web 所用项目下，
    避免安装副本场景（~/.agents/skills）推导出错误位置。
    """
    db_abs = os.path.abspath(resolve_db(path))
    return os.path.dirname(os.path.dirname(db_abs))


def resolve_db(path=None):
    """解析评测数据库路径。

    优先级：显式 --db-path > MOBILEEVAL_DB > MOBILEEVAL_HOME > skill 目录缓存（conf）>
    当前工作目录向上探测 > 插件仓库同级 MobileEval 项目 > 自举目标（仅新机器无任何线索时）。
    找不到真实库时报错（不创建垃圾库），提示指定路径。
    """
    p = path or os.environ.get("MOBILEEVAL_DB")
    if p:
        return os.path.abspath(p)
    home = os.environ.get("MOBILEEVAL_HOME")
    if home:
        cand = os.path.join(home, "eval-data", "mobileeval.db")
        if os.path.exists(cand):
            return cand
    conf_home = _read_conf()
    if conf_home:
        return os.path.join(conf_home, "eval-data", "mobileeval.db")
    hit = _search_ancestors()
    if hit:
        cand = os.path.join(hit, "eval-data", "mobileeval.db")
        if os.path.exists(cand):
            return cand
    default = os.path.join(PROJECT_ROOT, "MobileEval", "eval-data", "mobileeval.db")
    if os.path.exists(default):
        return default
    # 自举目标（最后兜底：真·新机器首次初始化位置 ~/MobileEval）
    boot = os.path.join(os.path.expanduser("~"), "MobileEval", "eval-data", "mobileeval.db")
    if os.path.exists(boot):
        return boot
    # 安装副本（~/.agents/skills）等场景：仓库同级推导不成立
    raise RuntimeError(
        "无法定位评测数据库（默认期望 <插件仓库同级>/MobileEval/eval-data/mobileeval.db）。"
        "请通过环境变量 MOBILEEVAL_DB / MOBILEEVAL_HOME 或命令参数 --db-path 指定真实数据库路径。")


SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'team',
    agent_name TEXT NOT NULL DEFAULT 'software-team-lead',
    description TEXT DEFAULT '',
    workspace_dir TEXT DEFAULT '',
    provider TEXT DEFAULT 'deepseek',
    model TEXT DEFAULT 'deepseek-v4-flash',
    base_url TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'local',
    source_path TEXT DEFAULT '',               -- 专家来源路径（全局 agents 目录 / workspace 路径）
    source_type TEXT DEFAULT '',               -- global | workspace | local | uploaded
    current_version INTEGER DEFAULT 1,          -- 当前专家版本号（版本管理）
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 专家版本快照：每次优化前保存当前版本，滚动保留
CREATE TABLE IF NOT EXISTS expert_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    path TEXT DEFAULT '',                       -- 快照目录
    score REAL,                                 -- 该版本评测得分
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 优化记录：基线评测 vs 优化后评测
CREATE TABLE IF NOT EXISTS optimizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    baseline_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    optimized_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    suggestion_id INTEGER REFERENCES ai_suggestions(id) ON DELETE SET NULL,
    version_from INTEGER DEFAULT 1,
    version_to INTEGER DEFAULT 2,
    summary TEXT DEFAULT '',                    -- 优化说明（JSON/文本）
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    scenario_type TEXT NOT NULL DEFAULT 'hybrid',
    autonomy_level TEXT NOT NULL DEFAULT 'low',
    prompt_template TEXT NOT NULL DEFAULT '',
    assertions TEXT NOT NULL DEFAULT '[]',
    human_metrics TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    experiment_id INTEGER,
    variant TEXT DEFAULT '',
    repeat INTEGER NOT NULL DEFAULT 1,
    concurrency INTEGER NOT NULL DEFAULT 1,
    total_cases INTEGER DEFAULT 0,
    score REAL,
    pass_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    total_assertions INTEGER DEFAULT 0,
    output_length INTEGER DEFAULT 0,
    duration_ms INTEGER,
    cost REAL,
    results_path TEXT DEFAULT '',
    log_path TEXT DEFAULT '',
    session_ids TEXT DEFAULT '[]',
    error TEXT DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    variable TEXT NOT NULL DEFAULT 'model',
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 全局评测模型（发起评测时选择；provider/model/base_url/api_key 传给 promptfoo 调用）
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'deepseek',
    model TEXT NOT NULL DEFAULT 'deepseek-v4-flash',
    base_url TEXT DEFAULT '',
    api_key TEXT DEFAULT '',
    is_default INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    case_title TEXT DEFAULT '',
    case_type TEXT DEFAULT '',
    pass INTEGER DEFAULT 0,
    score REAL,
    output_length INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    output_preview TEXT DEFAULT '',
    assertions TEXT DEFAULT '[]',
    session_ids TEXT DEFAULT '[]',
    process_metrics TEXT DEFAULT '',
    repeats TEXT DEFAULT '[]',
    needs_review INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rating INTEGER DEFAULT 0,
    comments TEXT DEFAULT '',
    metrics TEXT DEFAULT '[]',
    ai_consumed INTEGER DEFAULT 0,
    case_id TEXT DEFAULT '',
    verdict TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS ai_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    review_id INTEGER REFERENCES reviews(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'auto',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'hybrid',
    dimension TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    output_dir TEXT NOT NULL DEFAULT '',
    assertions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT DEFAULT '',
    auto_generated INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER REFERENCES objects(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '新对话',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    tools TEXT DEFAULT '[]',
    blocks TEXT DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tasks_object ON tasks(object_id);
CREATE INDEX IF NOT EXISTS idx_runs_object ON runs(object_id);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_cases_object ON cases(object_id);
CREATE INDEX IF NOT EXISTS idx_case_results_run ON case_results(run_id);
CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews(run_id);
"""


def get_db(path=None):
    db = resolve_db(path)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path=None):
    """建表 + 迁移到当前结构（幂等，旧库无损补列）。"""
    conn = get_db(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(_INDEXES)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    obj_cols = {r[1] for r in conn.execute("PRAGMA table_info(objects)").fetchall()}
    if "source" not in obj_cols:
        conn.execute("ALTER TABLE objects ADD COLUMN source TEXT NOT NULL DEFAULT 'local'")
    for col, ddl in (("source_path", "TEXT DEFAULT ''"),
                     ("source_type", "TEXT DEFAULT ''"),
                     ("current_version", "INTEGER DEFAULT 1")):
        if col not in obj_cols:
            conn.execute(f"ALTER TABLE objects ADD COLUMN {col} {ddl}")
    if "base_url" not in obj_cols:
        conn.execute("ALTER TABLE objects ADD COLUMN base_url TEXT DEFAULT ''")
    if "task_id" in obj_cols:
        _migrate_hierarchy(conn)
    sess_cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
    if "object_id" not in sess_cols:
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN object_id INTEGER REFERENCES objects(id) ON DELETE SET NULL")
    msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
    if "blocks" not in msg_cols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN blocks TEXT DEFAULT '[]'")
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "concurrency" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN concurrency INTEGER NOT NULL DEFAULT 1")
    if "total_cases" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN total_cases INTEGER DEFAULT 0")
    if "token_count" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN token_count INTEGER DEFAULT 0")
    if "experiment_id" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN experiment_id INTEGER")
    if "variant" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN variant TEXT DEFAULT ''")
    cr_cols = {r[1] for r in conn.execute("PRAGMA table_info(case_results)").fetchall()}
    if "token_count" not in cr_cols:
        conn.execute("ALTER TABLE case_results ADD COLUMN token_count INTEGER DEFAULT 0")
    if "process_metrics" not in cr_cols:
        conn.execute("ALTER TABLE case_results ADD COLUMN process_metrics TEXT DEFAULT ''")
    if "repeats" not in cr_cols:
        conn.execute("ALTER TABLE case_results ADD COLUMN repeats TEXT DEFAULT '[]'")
    if "needs_review" not in cr_cols:
        conn.execute("ALTER TABLE case_results ADD COLUMN needs_review INTEGER DEFAULT 0")
    rv_cols = {r[1] for r in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    if "case_id" not in rv_cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN case_id TEXT DEFAULT ''")
    if "verdict" not in rv_cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN verdict TEXT DEFAULT ''")
    c_cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
    if "dimension" not in c_cols:
        conn.execute("ALTER TABLE cases ADD COLUMN dimension TEXT NOT NULL DEFAULT ''")
    # 去 task 层：runs/cases 的 task_id 可空 + runs 加实验变量列 + objects 加 human_metrics
    _migrate_detask(conn)
    _migrate_models(conn)


def _migrate_models(conn):
    """全局模型迁移（幂等）：runs 补 base_url/model_id 列。"""
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "base_url" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN base_url TEXT DEFAULT ''")
    if "model_id" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN model_id INTEGER")


def _migrate_detask(conn):
    """去 task 层迁移（幂等）：评测任务不再是必选层级，每次运行(run)自带实验变量。"""
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "agent_on" in run_cols:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("""CREATE TABLE runs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            provider TEXT DEFAULT '',
            model TEXT DEFAULT '',
            base_url TEXT DEFAULT '',
            model_id INTEGER,
            experiment_id INTEGER,
            variant TEXT DEFAULT '',
            version TEXT DEFAULT '',
            agent_on INTEGER NOT NULL DEFAULT 1,
            case_ids TEXT DEFAULT '[]',
            repeat INTEGER NOT NULL DEFAULT 1,
            concurrency INTEGER NOT NULL DEFAULT 1,
            total_cases INTEGER DEFAULT 0,
            score REAL,
            pass_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            total_assertions INTEGER DEFAULT 0,
            output_length INTEGER DEFAULT 0,
            duration_ms INTEGER,
            token_count INTEGER DEFAULT 0,
            cost REAL,
            results_path TEXT DEFAULT '',
            log_path TEXT DEFAULT '',
            session_ids TEXT DEFAULT '[]',
            error TEXT DEFAULT '',
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )""")
        old_cols = [c[1] for c in conn.execute("PRAGMA table_info(runs)").fetchall()]
        conn.execute(f"INSERT INTO runs_new ({','.join(old_cols)}) SELECT {','.join(old_cols)} FROM runs")
        conn.execute("DROP TABLE runs")
        conn.execute("ALTER TABLE runs_new RENAME TO runs")
        conn.execute("""CREATE TABLE cases_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
            task_id INTEGER,
            case_id TEXT NOT NULL,
            title TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'hybrid',
            dimension TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            output_dir TEXT NOT NULL DEFAULT '',
            assertions TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT DEFAULT '',
            auto_generated INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            reviewed_at TEXT
        )""")
        old_ccols = [c[1] for c in conn.execute("PRAGMA table_info(cases)").fetchall()]
        conn.execute(f"INSERT INTO cases_new ({','.join(old_ccols)}) SELECT {','.join(old_ccols)} FROM cases")
        conn.execute("DROP TABLE cases")
        conn.execute("ALTER TABLE cases_new RENAME TO cases")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    obj_cols = {r[1] for r in conn.execute("PRAGMA table_info(objects)").fetchall()}
    if "human_metrics" not in obj_cols:
        conn.execute("ALTER TABLE objects ADD COLUMN human_metrics TEXT DEFAULT '[]'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_object ON runs(object_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_object ON cases(object_id)")


def _migrate_hierarchy(conn):
    """旧层级（task → object）→ 新层级（object → task），无损迁移。"""
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("""CREATE TABLE objects_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'team',
            agent_name TEXT NOT NULL DEFAULT 'software-team-lead',
            description TEXT DEFAULT '', workspace_dir TEXT DEFAULT '',
            provider TEXT DEFAULT 'deepseek', model TEXT DEFAULT 'deepseek-v4-flash',
            source TEXT NOT NULL DEFAULT 'local',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
        conn.execute("""CREATE TABLE tasks_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER NOT NULL REFERENCES objects_new(id) ON DELETE CASCADE,
            name TEXT NOT NULL, description TEXT DEFAULT '',
            scenario_type TEXT NOT NULL DEFAULT 'hybrid',
            autonomy_level TEXT NOT NULL DEFAULT 'low',
            prompt_template TEXT NOT NULL DEFAULT '',
            assertions TEXT NOT NULL DEFAULT '[]',
            human_metrics TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
        for row in conn.execute("SELECT * FROM objects"):
            d = dict(row)
            conn.execute(
                """INSERT INTO objects_new (id,name,kind,agent_name,description,workspace_dir,
                   provider,model,source,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (d["id"], d["name"], d.get("kind") or "team",
                 d.get("agent_name") or "software-team-lead", d.get("description") or "",
                 d.get("workspace_dir") or "", d.get("provider") or "deepseek",
                 d.get("model") or "deepseek-v4-flash", d.get("source") or "local",
                 d.get("created_at")))
        old_tasks = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()}
        task_map = {}
        for obj in conn.execute("SELECT id, task_id FROM objects").fetchall():
            t = old_tasks.get(obj["task_id"])
            if not t:
                continue
            cur = conn.execute(
                """INSERT INTO tasks_new (object_id,name,description,scenario_type,
                   autonomy_level,prompt_template,assertions,human_metrics,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (obj["id"], t["name"], t.get("description") or "",
                 t.get("scenario_type") or "hybrid", t.get("autonomy_level") or "low",
                 t.get("prompt_template") or "", t.get("assertions") or "[]",
                 t.get("human_metrics") or "[]", t.get("created_at"), t.get("updated_at")))
            task_map[(obj["task_id"], obj["id"])] = cur.lastrowid
        for r in conn.execute("SELECT id, task_id, object_id FROM runs").fetchall():
            ntid = task_map.get((r["task_id"], r["object_id"]))
            if ntid:
                conn.execute("UPDATE runs SET task_id=? WHERE id=?", (ntid, r["id"]))
        for c in conn.execute("SELECT id, task_id, object_id FROM cases").fetchall():
            ntid = task_map.get((c["task_id"], c["object_id"]))
            if ntid:
                conn.execute("UPDATE cases SET task_id=? WHERE id=?", (ntid, c["id"]))
        conn.execute("DROP TABLE objects")
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE objects_new RENAME TO objects")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def jloads(s, default=None):
    if s in (None, ""):
        return default if default is not None else []
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return default if default is not None else []


def jdumps(v):
    return json.dumps(v, ensure_ascii=False)


def row_to_dict(row):
    return dict(row) if row is not None else None
