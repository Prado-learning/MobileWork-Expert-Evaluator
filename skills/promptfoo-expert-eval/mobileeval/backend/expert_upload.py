"""上传的专家包 → 评测工作区：

- 解压（防 zip 路径穿越）
- 探测 .opencode 位置（working_dir）
- 权限适配：非交互评测所需的权限面（bash ask → 白名单 allow，external_directory/doom_loop/question → deny）
  —— 与 workspaces/test01-eval 的适配一致；上传的包作为评测副本，原包不受影响。
"""
import json
import os
import re
import shutil
import zipfile

UPLOADS_ROOT = None  # 由 config 注入

BASH_ALLOW_RULES = [
    "    '*': allow",
    "    'rm *': deny",
    "    'Remove-Item*': deny",
    "    'del *': deny",
    "    'rd *': deny",
    "    'rmdir*': deny",
]


def extract_zip(zip_path, dest_root, max_depth=4):
    """安全解压 zip 到 dest_root，返回解压根目录。过滤 __MACOSX 与隐藏元数据。"""
    if not os.path.exists(zip_path):
        raise ValueError("上传文件不存在")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("__MACOSX") or name.split("/")[0].startswith("."):
                continue
            if info.is_dir():
                continue
            if name.count("/") >= max_depth:
                continue
            target = os.path.normpath(os.path.join(dest_root, name))
            if not (target == dest_root or target.startswith(dest_root + os.sep)):
                raise ValueError(f"zip 条目路径越界: {name}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return dest_root


def _is_workspace(d):
    """评测工作区判定：.opencode 下存在 opencode.jsonc（旧版）或 agents/*.md（新版）均可。"""
    if os.path.isfile(os.path.join(d, ".opencode", "opencode.jsonc")):
        return True
    ad = os.path.join(d, ".opencode", "agents")
    if os.path.isdir(ad):
        return any(f.endswith(".md") for f in os.listdir(ad))
    return False


def find_workspace(root, max_depth=4):
    """在解压根目录中定位 .opencode 评测工作区（含 opencode.jsonc 或 agents/*.md）。"""
    root = os.path.abspath(root)
    candidates = [root]
    for depth in range(1, max_depth + 1):
        if depth == 1:
            candidates = [os.path.join(root, d) for d in os.listdir(root)
                          if os.path.isdir(os.path.join(root, d))]
        for d in list(candidates):
            if _is_workspace(d):
                return d
        candidates = [os.path.join(d, s) for d in candidates
                      for s in (os.listdir(d) if os.path.isdir(d) else [])
                      if os.path.isdir(os.path.join(d, s))]
    # 回退：os.walk 全量扫描
    for base, dirs, files in os.walk(root):
        if _is_workspace(base):
            return base
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
    return None


def _missing_cfg_msg(root):
    """找不到 .opencode 评测工作区时，给出可操作的明确错误。"""
    for base, dirs, files in os.walk(root):
        if ".opencode" in dirs and not _is_workspace(base):
            raise ValueError(
                f"找到 {base} 下的 .opencode 目录，但其中既没有 opencode.jsonc 配置文件，"
                f"也没有 agents/*.md 专家定义（请确认专家包结构为 "
                f"<文件夹>/.opencode/opencode.jsonc 或 <文件夹>/.opencode/agents/*.md）"
            )
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
    raise ValueError("上传内容中未找到 .opencode 评测工作区（应为含 .opencode/opencode.jsonc 或 .opencode/agents/*.md 的专家包）")


def _md_frontmatter(path):
    """解析 agents/*.md 的 frontmatter（简单 key: value 行解析，足够取 name/mode）。"""
    raw = open(path, encoding="utf-8-sig").read()
    if not raw.startswith("---"):
        return {}
    fm = raw.split("---", 2)[1]
    d = {}
    for ln in fm.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        k, _, v = s.partition(":")
        k, v = k.strip(), v.strip()
        if k and not any(c in k for c in (" ", "\t", "'", '"')):
            d[k] = v
    return d


def _parse_yaml_simple(text):
    """解析 YAML 子集（frontmatter）：嵌套 dict + 标量。忽略列表/续行等复杂结构。

    用于 agents/*.md 的 frontmatter 展示，支持 permission/profession 等嵌套块。
    """
    lines = [ln for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    root = {}
    stack = [(-1, root)]
    for ln in lines:
        s = ln.strip()
        if s.startswith("---") or s == "...":
            continue
        if ":" not in s:
            continue
        k, _, v = s.partition(":")
        k = k.strip().strip("'\"")
        v = v.strip()
        while stack and len(ln) - len(ln.lstrip()) <= stack[-1][0]:
            stack.pop()
        node = stack[-1][1]
        if v:
            node[k] = v
        else:
            child = {}
            node[k] = child
            stack.append((len(ln) - len(ln.lstrip()), child))
    return root


def _dict_first(v):
    """dict 取 zh 优先 → en → 任意值；标量原样返回。"""
    if isinstance(v, dict):
        for k in ("zh", "en"):
            if v.get(k):
                return v[k]
        return next((str(x) for x in v.values() if x), "")
    return (v or "")


def _perm_val(v):
    """permission 子键摘要：dict 取 '*' 值，标量原样。"""
    if isinstance(v, dict):
        return v.get("*") or next((x for x in v.values() if isinstance(x, str)), "")
    return v


def list_agents(workspace):
    """解析评测工作区的专家团成员信息（agents/*.md 为主，opencode.jsonc 补充）。

    返回 [{id, mode, steps, description, role, bash, edit, webfetch, external, task_allow}]，
    primary（团长）排在首位。
    """
    oc = os.path.join(workspace, ".opencode")
    agents, order = {}, []
    adir = os.path.join(oc, "agents")
    if os.path.isdir(adir):
        for f in sorted(os.listdir(adir)):
            if not f.endswith(".md"):
                continue
            raw = open(os.path.join(adir, f), encoding="utf-8-sig").read()
            # 只解析 --- 之间的 frontmatter，正文（markdown）不参与
            fm_text = raw.split("---", 2)[1] if raw.startswith("---") else ""
            fm = _parse_yaml_simple(fm_text)
            aid = (fm.get("name") or f[:-3]).strip()
            perm = fm.get("permission") or {}
            agents[aid] = {
                "id": aid,
                "mode": fm.get("mode", ""),
                "steps": fm.get("steps"),
                "description": (fm.get("description") or ""),
                "role": _dict_first(fm.get("profession")) or _dict_first(fm.get("displayName")),
                "bash": _perm_val(perm.get("bash")),
                "edit": perm.get("edit"),
                "webfetch": perm.get("webfetch"),
                "external": _perm_val(perm.get("external_directory")),
                "task_allow": _task_allow(perm.get("task")),
            }
            order.append(aid)
    # opencode.jsonc：补充/兜底（旧版只有 jsonc 时也生成列表）
    cfg_path = os.path.join(oc, "opencode.jsonc")
    if os.path.isfile(cfg_path):
        lines = [ln for ln in open(cfg_path, encoding="utf-8-sig").read().splitlines()
                 if not ln.lstrip().startswith(("//", "/*"))]
        try:
            cfg = json.loads("\n".join(lines))
        except ValueError:
            cfg = None
        if cfg:
            for aid, a in (cfg.get("agent") or {}).items():
                perm = a.get("permission") or {}
                if aid not in agents:
                    agents[aid] = {
                        "id": aid, "mode": a.get("mode", ""), "steps": a.get("steps"),
                        "description": (a.get("description") or ""),
                        "role": "", "bash": _perm_val(perm.get("bash")),
                        "edit": perm.get("edit"), "webfetch": perm.get("webfetch"),
                        "external": _perm_val(perm.get("external_directory")),
                        "task_allow": _task_allow(perm.get("task")),
                    }
                    order.append(aid)
                else:  # 补充 jsonc 里的委派信息
                    ta = _task_allow(perm.get("task"))
                    if ta and not agents[aid].get("task_allow"):
                        agents[aid]["task_allow"] = ta
                    if not agents[aid].get("steps") and a.get("steps"):
                        agents[aid]["steps"] = a.get("steps")
    primary = sorted((a for a in agents.values() if a["mode"] == "primary"),
                     key=lambda x: x["id"])
    others = [a for a in (agents[i] for i in order) if a["mode"] != "primary"]
    return primary + others


def _task_allow(tv):
    if isinstance(tv, dict):
        return [k for k, v in tv.items() if v == "allow"]
    return []


def detect_agent_name(workspace):
    """探测 primary agent（团长）：优先 opencode.jsonc，其次 agents/*.md frontmatter。"""
    cfg_path = os.path.join(workspace, ".opencode", "opencode.jsonc")
    if os.path.exists(cfg_path):
        lines = [ln for ln in open(cfg_path, encoding="utf-8-sig").read().splitlines()
                 if not ln.lstrip().startswith(("//", "/*"))]
        try:
            cfg = json.loads("\n".join(lines))
        except ValueError:
            cfg = None
        if cfg:
            agents = cfg.get("agent") or {}
            for aid, a in agents.items():
                if a.get("mode") == "primary":
                    return aid
            if agents:
                return next(iter(agents))
    # agents/*.md：mode: primary 优先，否则第一个
    agents_dir = os.path.join(workspace, ".opencode", "agents")
    if os.path.isdir(agents_dir):
        mds = sorted(f for f in os.listdir(agents_dir) if f.endswith(".md"))
        first = None
        for f in mds:
            fm = _md_frontmatter(os.path.join(agents_dir, f))
            name = (fm.get("name") or "").strip()
            if not name:
                continue
            if fm.get("mode") == "primary":
                return name
            if first is None:
                first = name
        return first
    return None


def _patch_jsonc_permissions(cfg_path):
    lines = [ln for ln in open(cfg_path, encoding="utf-8-sig").read().splitlines()
             if not ln.lstrip().startswith(("//", "/*"))]
    try:
        data = json.loads("\n".join(lines))
    except ValueError:
        return
    changed = False
    for aid, agent in (data.get("agent") or {}).items():
        perm = agent.get("permission", {})
        # bash 一律改为白名单 allow（保留删除类 deny）
        b = {"*": "allow"}
        for pat in ("rm *", "Remove-Item*", "del *", "rd *", "rmdir*", "format*"):
            b[pat] = "deny"
        perm["bash"] = b
        for key in ("external_directory", "doom_loop"):
            v = perm.get(key)
            if isinstance(v, dict) and v.get("*") == "ask":
                perm[key] = "deny"
            elif v == "ask":
                perm[key] = "deny"
        perm["question"] = "deny"
        changed = True
    if changed:
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)


def _patch_agent_md(agents_dir):
    """改 agents/*.md frontmatter 的权限（非交互适配，与 opencode.jsonc 版本行为一致）：
    bash 的 '*': ask → 白名单 allow+删除类 deny；external_directory/doom_loop 的 '*': ask → deny；
    question: ask → deny。按当前 permission 子键作用域精确替换，避免破坏 yaml 结构。"""
    if not os.path.isdir(agents_dir):
        return 0
    n = 0
    for fname in os.listdir(agents_dir):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(agents_dir, fname)
        raw = open(path, encoding="utf-8-sig").read()
        if not raw.startswith("---"):
            continue
        parts = raw.split("---", 2)
        out, inside, cur, seen_q = [], False, None, False
        changed = False
        for line in parts[1].splitlines():
            s = line.strip()
            if s == "permission:":
                inside, cur, seen_q = True, None, False
                out.append(line)
                continue
            if not inside:
                out.append(line)
                continue
            if s in ("bash:", "external_directory:", "doom_loop:", "skill:", "task:", "todowrite:", "webfetch:"):
                cur = s[:-1]
                if s in ("skill:", "task:", "todowrite:", "webfetch:") and not seen_q:
                    out.append("  question: deny")
                    seen_q = True
                    changed = True
                out.append(line)
                continue
            if s == "'*': ask":
                if cur == "bash":
                    out.extend(BASH_ALLOW_RULES)
                elif cur in ("external_directory", "doom_loop"):
                    out.append(line.replace("'*': ask", "'*': deny"))
                else:
                    out.append(line)
                changed = True
                continue
            if s == "doom_loop: ask":
                out.append(line.replace("doom_loop: ask", "doom_loop: deny"))
                changed = True
                continue
            if s == "question: ask":
                out.append(line.replace("question: ask", "question: deny"))
                changed = True
                continue
            out.append(line)
        if changed:
            open(path, "w", encoding="utf-8-sig").write("---" + "\n".join(out) + "---" + parts[2])
            n += 1
    return n


def adapt_workspace(workspace):
    """非交互评测权限适配（副本工作区，不改原始上传内容以外的东西）。
    兼容两种结构：opencode.jsonc（旧版）与 agents/*.md（新版，无 jsonc）。"""
    cfg_path = os.path.join(workspace, ".opencode", "opencode.jsonc")
    if os.path.isfile(cfg_path):
        _patch_jsonc_permissions(cfg_path)
    n_md = _patch_agent_md(os.path.join(workspace, ".opencode", "agents"))
    return n_md


def _should_skip_rel(rel):
    """过滤无关/危险条目。注意 .opencode 目录是必需的配置，不能过滤。"""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if any(p in ("node_modules", ".git", "__pycache__", "dist", ".pytest_cache") for p in parts):
        return True
    if rel.startswith("__MACOSX"):
        return True
    base = os.path.basename(rel)
    if base in (".DS_Store", "Thumbs.db") or base.startswith("._"):
        return True
    return False


def store_upload_files(file_storage_list, uploads_root, prefix="obj"):
    """文件夹模式：按相对路径重建目录结构，返回 (workspace_dir, agent_name)。"""
    os.makedirs(uploads_root, exist_ok=True)
    dest = os.path.join(uploads_root, f"{prefix}-{os.urandom(4).hex()}")
    os.makedirs(dest, exist_ok=True)
    try:
        saved = 0
        for fs in file_storage_list:
            rel = (fs.filename or "").replace("\\", "/")
            if not rel or _should_skip_rel(rel):
                continue
            target = os.path.normpath(os.path.join(dest, rel))
            if not (target == dest or target.startswith(dest + os.sep)):
                raise ValueError(f"上传路径越界: {rel}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            fs.save(target)
            saved += 1
        if saved == 0:
            raise ValueError("未收到有效文件（请选择包含 .opencode 配置的专家文件夹）")
        workspace = find_workspace(dest)
        if not workspace:
            _missing_cfg_msg(dest)
        adapt_workspace(workspace)
        return workspace, detect_agent_name(workspace)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def store_upload(file_storage, uploads_root, prefix="obj"):
    """保存上传 zip 并解压适配，返回 (workspace_dir, agent_name)。"""
    os.makedirs(uploads_root, exist_ok=True)
    dest = os.path.join(uploads_root, f"{prefix}-{os.urandom(4).hex()}")
    os.makedirs(dest, exist_ok=True)
    zip_path = os.path.join(dest, "expert-package.zip")
    file_storage.save(zip_path)
    try:
        extract_zip(zip_path, dest)
        workspace = find_workspace(dest)
        if not workspace:
            _missing_cfg_msg(dest)
        adapt_workspace(workspace)
        agent_name = detect_agent_name(workspace)
        return workspace, agent_name
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
