"""SQLite 数据层：连接与建表。

层级（自顶向下）：专家/专家团(objects) → 任务(tasks) → 评测(runs)。
"""
import json
import os
import sqlite3

from config import DB_PATH, ensure_dirs

SCHEMA = """
-- 顶层：被测专家/专家团
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'team',               -- single | team（专家/专家团）
    agent_name TEXT NOT NULL DEFAULT 'software-team-lead',
    description TEXT DEFAULT '',
    workspace_dir TEXT DEFAULT '',
    provider TEXT DEFAULT 'deepseek',
    model TEXT DEFAULT 'deepseek-v4-flash',
    base_url TEXT DEFAULT '',                        -- LLM API base URL（留空用 provider 默认端点）
    source TEXT NOT NULL DEFAULT 'local',            -- local（本机路径）| uploaded（上传专家包）
    source_path TEXT DEFAULT '',                     -- 专家来源路径（全局 agents 目录 / workspace）
    source_type TEXT DEFAULT '',                     -- global | workspace | local | uploaded
    current_version INTEGER DEFAULT 1,               -- 专家当前版本号（版本管理）
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 专家版本快照：每次优化前保存当前版本，滚动保留
CREATE TABLE IF NOT EXISTS expert_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    path TEXT DEFAULT '',
    score REAL,
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
    summary TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 任务：挂在专家/专家团下
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    scenario_type TEXT NOT NULL DEFAULT 'hybrid',   -- structured | hybrid | open_ended
    autonomy_level TEXT NOT NULL DEFAULT 'low',      -- low | high（低自主=严格断言；高自主=目标+验收）
    prompt_template TEXT NOT NULL DEFAULT '',
    assertions TEXT NOT NULL DEFAULT '[]',           -- JSON: [{type, value}]
    human_metrics TEXT NOT NULL DEFAULT '[]',        -- JSON: [{name, description, criteria, weight}]
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',          -- pending|running|passed|failed|error|aborted
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    base_url TEXT DEFAULT '',                        -- 评测用模型 base url（来自全局模型）
    model_id INTEGER,                                -- 关联全局 models 表（可选）
    experiment_id INTEGER,                          -- 对照实验（可选）
    variant TEXT DEFAULT '',                        -- 变体标签（版本/模型/是否启用专家团）
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
    session_ids TEXT DEFAULT '[]',                   -- JSON
    error TEXT DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 对照实验：同一组 case 在不同变量（专家版本/基础模型/是否启用专家团）下对比
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    variable TEXT NOT NULL DEFAULT 'model',         -- version | model | agent_on
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 全局评测模型（发起评测时选择；provider/model/base_url/api_key 传给 promptfoo 调用）
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                             -- 显示名（如 DeepSeek 官方 / 本地 vLLM）
    provider TEXT NOT NULL DEFAULT 'deepseek',      -- opencode provider_id
    model TEXT NOT NULL DEFAULT 'deepseek-v4-flash',-- 模型 id
    base_url TEXT DEFAULT '',                       -- 可选：API 端点
    api_key TEXT DEFAULT '',                        -- API key（本地明文；评测时传给 promptfoo）
    is_default INTEGER DEFAULT 0,                   -- 默认模型（发起评测时预选）
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
    assertions TEXT DEFAULT '[]',                    -- JSON 明细
    session_ids TEXT DEFAULT '[]',
    process_metrics TEXT DEFAULT '',                 -- JSON: 过程探针产出的模块级指标（工具调用/委派/任务派发）
    repeats TEXT DEFAULT '[]',                       -- JSON: repeat 多次的 pass/score（稳定性）
    needs_review INTEGER DEFAULT 0                   -- 1=待人工判定（开放式/兜底重判/无法自动判定）
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    rating INTEGER DEFAULT 0,                        -- 1-5
    comments TEXT DEFAULT '',
    metrics TEXT DEFAULT '[]',                       -- JSON: [{name, score, note}] 逐项打分
    ai_consumed INTEGER DEFAULT 0,                   -- AI 是否已读取该评审
    case_id TEXT DEFAULT '',                         -- 逐 case 判定（空=整体评审）
    verdict TEXT DEFAULT '',                         -- pass|fail|uncertain 逐 case 判定
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS ai_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    review_id INTEGER REFERENCES reviews(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'auto',             -- auto | review-driven
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,                           -- 唯一 case 标识（如 c1/c2/c3）
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'hybrid',             -- structured | hybrid | open_ended
    dimension TEXT NOT NULL DEFAULT '',              -- 模块级评测维度: tool_accuracy|kb_match|collaboration|output_quality
    prompt TEXT NOT NULL DEFAULT '',
    output_dir TEXT NOT NULL DEFAULT '',
    assertions TEXT NOT NULL DEFAULT '[]',           -- JSON: [{type, value}]
    status TEXT NOT NULL DEFAULT 'pending',          -- pending | approved | rejected
    review_note TEXT DEFAULT '',
    auto_generated INTEGER NOT NULL DEFAULT 1,       -- AI 自动生成标记
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reviewed_at TEXT
);

-- AI 评测助手聊天记录（会话 + 消息；会话可挂在某个专家/专家团下，NULL=通用对话）
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
    role TEXT NOT NULL,                              -- user | ai
    text TEXT NOT NULL DEFAULT '',
    tools TEXT DEFAULT '[]',                         -- JSON: [{name, args, result}]（AI 消息的工具调用轨迹）
    blocks TEXT DEFAULT '[]',                        -- JSON: 有序内容块 [{type:'text'|'tool', ...}]（AI 消息，保存交替顺序）
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS pending_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    saved_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',          -- pending=待转换 | converting=转换中 | done=已完成 | failed=失败
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    finished_at TEXT
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tasks_object ON tasks(object_id);
CREATE INDEX IF NOT EXISTS idx_runs_object ON runs(object_id);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_cases_object ON cases(object_id);
CREATE INDEX IF NOT EXISTS idx_case_results_run ON case_results(run_id);
CREATE INDEX IF NOT EXISTS idx_pending_imports_object ON pending_imports(object_id);
CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews(run_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
"""


def get_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    ensure_dirs()
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(_INDEXES)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    """迁移到当前结构。

    - 旧层级（task → object）→ 新层级（object → task）：无损迁移，
      每个专家/专家团复制一份原任务挂到自己名下。
    """
    obj_cols = {r[1] for r in conn.execute("PRAGMA table_info(objects)").fetchall()}
    task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    if "task_id" in obj_cols:
        _migrate_hierarchy(conn)
    else:
        if "source" not in obj_cols:
            conn.execute("ALTER TABLE objects ADD COLUMN source TEXT NOT NULL DEFAULT 'local'")
    # 聊天会话挂对象：旧库补 object_id 列
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "chat_sessions" in tables:
        sess_cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()}
        if "object_id" not in sess_cols:
            conn.execute(
                "ALTER TABLE chat_sessions ADD COLUMN object_id INTEGER REFERENCES objects(id) ON DELETE SET NULL")
        msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
        if "blocks" not in msg_cols:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN blocks TEXT DEFAULT '[]'")
    # runs 并发/总数列：旧库补列
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
    cr_tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "case_results" in cr_tables:
        cr_cols = {r[1] for r in conn.execute("PRAGMA table_info(case_results)").fetchall()}
        if "token_count" not in cr_cols:
            conn.execute("ALTER TABLE case_results ADD COLUMN token_count INTEGER DEFAULT 0")
        if "process_metrics" not in cr_cols:
            conn.execute("ALTER TABLE case_results ADD COLUMN process_metrics TEXT DEFAULT ''")
        if "repeats" not in cr_cols:
            conn.execute("ALTER TABLE case_results ADD COLUMN repeats TEXT DEFAULT '[]'")
        if "needs_review" not in cr_cols:
            conn.execute("ALTER TABLE case_results ADD COLUMN needs_review INTEGER DEFAULT 0")
    # 模块级评测：cases.dimension 列
    if "cases" in cr_tables:
        c_cols = {r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()}
        if "dimension" not in c_cols:
            conn.execute("ALTER TABLE cases ADD COLUMN dimension TEXT NOT NULL DEFAULT ''")
    # 专家版本管理列：旧库补列
    obj_cols2 = {r[1] for r in conn.execute("PRAGMA table_info(objects)").fetchall()}
    for col, ddl in (("source_path", "TEXT DEFAULT ''"),
                     ("source_type", "TEXT DEFAULT ''"),
                     ("current_version", "INTEGER DEFAULT 1")):
        if col not in obj_cols2:
            conn.execute(f"ALTER TABLE objects ADD COLUMN {col} {ddl}")
    if "base_url" not in obj_cols2:
        conn.execute("ALTER TABLE objects ADD COLUMN base_url TEXT DEFAULT ''")
    # 逐 case 人工判定列：reviews.case_id + verdict
    if "reviews" in tables:
        rv_cols = {r[1] for r in conn.execute("PRAGMA table_info(reviews)").fetchall()}
        if "case_id" not in rv_cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN case_id TEXT DEFAULT ''")
        if "verdict" not in rv_cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN verdict TEXT DEFAULT ''")
    # 去 task 层：runs/cases 的 task_id 可空 + runs 加实验变量列 + objects 加 human_metrics
    _migrate_detask(conn)
    _migrate_models(conn)


def _migrate_models(conn):
    """全局模型迁移（幂等）：runs 补 base_url/model_id 列（models 表由 CREATE TABLE 建）。"""
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "base_url" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN base_url TEXT DEFAULT ''")
    if "model_id" not in run_cols:
        conn.execute("ALTER TABLE runs ADD COLUMN model_id INTEGER")


def _migrate_detask(conn):
    """去 task 层迁移（幂等）：评测任务不再是必选层级，每次运行(run)自带实验变量。

    - runs 重建：task_id 改可空；新增 version（专家版本）/agent_on（是否启用专家团）/case_ids（本次跑的 case 集）
    - cases 重建：task_id 改可空（case 直接挂对象）
    - objects 加 human_metrics（承接原 task 的业务指标定义）
    """
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "agent_on" in run_cols:
        return  # 已迁移
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # 1) runs 重建
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
        # 2) cases 重建（task_id 可空，无外键）
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
    # 3) objects 承接业务指标 + 重建索引
    obj_cols = {r[1] for r in conn.execute("PRAGMA table_info(objects)").fetchall()}
    if "human_metrics" not in obj_cols:
        conn.execute("ALTER TABLE objects ADD COLUMN human_metrics TEXT DEFAULT '[]'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_object ON runs(object_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_object ON cases(object_id)")


def _migrate_hierarchy(conn):
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

        # 复制 objects（保留 id，去掉 task_id）
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

        # 每个 object 复制其原 task，记录 old_task_id → new_task_id（按 object 区分）
        old_tasks = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()}
        task_map = {}  # (old_task_id, old_object_id) -> new_task_id
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

        # 更新 runs / cases 的 task_id 到新任务
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


def ensure_default_task(object_id):
    """确保 object 至少拥有一条 task（去 task 层后，生成 case 需要 task_id 落库）。

    若 object 下已存在 task，直接返回最近一条的 id；否则插入一条默认 task 并返回其 id。
    用于修复「去 task 层迁移后导入/分析流程不再创建 task，但生成 case 接口仍要求 task 存在」的 bug。
    """
    conn = get_db()
    try:
        obj = row_to_dict(conn.execute(
            "SELECT id, name, agent_name FROM objects WHERE id=?", (object_id,)).fetchone())
        if not obj:
            return None
        existing = row_to_dict(conn.execute(
            "SELECT id FROM tasks WHERE object_id=? ORDER BY id DESC LIMIT 1",
            (object_id,)).fetchone())
        if existing:
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO tasks (object_id, name, description, scenario_type, autonomy_level,
               prompt_template, assertions, human_metrics)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (object_id,
             f"{obj.get('name') or '专家'} 默认评测任务",
             "覆盖核心能力的默认评测任务（由生成 case 时自动创建）",
             "hybrid", "low", "", "[]", "[]"))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


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
