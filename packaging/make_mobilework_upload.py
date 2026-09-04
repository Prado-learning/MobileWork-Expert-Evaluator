#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 MobileWork 技能上传包（目录 + ZIP）+ 上传前自查报告。

依据《MobileWork 技能接入指南（简版）》：
- 包限制：目录项 ≤ 4096、总大小 ≤ 128 MiB、单文件 ≤ 16 MiB、SKILL.md ≤ 1 MB；
- SKILL.md 必须在 Skill 根目录；ZIP 根目录为 Skill 根，或只含一个顶层目录；
- 目录名 == SKILL.md `name` == `metadata.mobilework.authSkillId`（小写 kebab-case）。

自动剔除发布不需要的：__pycache__ / *.pyc / node_modules / .git / .bak-* / 运行期缓存。

用法：
    python -B packaging/make_mobilework_upload.py                 # 处理全部技能
    python -B packaging/make_mobilework_upload.py --skills=promptfoo-expert-eval
    python -B packaging/make_mobilework_upload.py --out-dir=dist/mobilework-upload --no-zip
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 插件主仓根
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

SKILLS = ["promptfoo-expert-eval", "mobilework-expert-manager"]

EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", ".idea", ".vscode"}
EXCLUDE_NAME_RE = re.compile(r"\.(pyc|pyo|bak-[\d-]+|mobileeval-home\.conf)$", re.I)

LIMITS = {"max_items": 4096, "max_total_mib": 128, "max_file_mib": 16, "max_skill_md_mib": 1}


def _excluded(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if EXCLUDE_NAME_RE.search(rel):
        return True
    if os.path.basename(rel).startswith(".mobileeval-home.conf"):
        return True
    return False


def _collect(src: str):
    """返回 [(abs_path, rel_posix)]，按排除规则过滤。"""
    out = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for f in sorted(files):
            abs_f = os.path.join(root, f)
            rel = os.path.relpath(abs_f, src)
            if _excluded(rel):
                continue
            out.append((abs_f, rel.replace("\\", "/")))
    return out


def _parse_frontmatter(md_text: str):
    """解析 SKILL.md frontmatter（YAML 优先，缺失 PyYAML 时降级正则）。"""
    m = re.match(r"^---\s*\n(.*?)\n---", md_text, re.S)
    if not m:
        return {}
    fm = m.group(1)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(fm) or {}
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        pass
    # 降级：粗提取顶层 name / metadata.mobilework.*
    data = {}
    for key in ("name",):
        mm = re.search(rf"^{key}:\s*(\S+)", fm, re.M)
        if mm:
            data[key] = mm.group(1).strip("'\"")
    mm = re.search(r"^metadata:\s*\n(\s+.*)$", fm, re.M | re.S)
    if mm:
        meta = {}
        for k in ("authContractVersion", "authSkillId"):
            mk = re.search(rf"^(\s+)mobilework:\s*\n(.*)$", mm.group(1), re.M | re.S)
            if mk:
                mm2 = re.search(rf"{k}:\s*(\S+)", mk.group(2), re.M)
                if mm2:
                    meta[k] = mm2.group(1).strip("'\"")
        data["_mobilework_flat"] = meta
    return data


def _check_contract(skill_id: str, data: dict) -> list:
    """契约自查，返回问题列表（空 = 通过）。"""
    problems = []
    if data.get("name") != skill_id:
        problems.append(f"name({data.get('name')!r}) != 目录名({skill_id})")
    mw = data.get("metadata", {}).get("mobilework", {}) if isinstance(data, dict) else {}
    if not mw:
        mw_flat = data.get("_mobilework_flat", {})
        mw = {"authContractVersion": mw_flat.get("authContractVersion"),
              "authSkillId": mw_flat.get("authSkillId")}
    if str(mw.get("authContractVersion", "")) != "1":
        problems.append(f"metadata.mobilework.authContractVersion != 1（当前 {mw.get('authContractVersion')!r}）")
    if mw.get("authSkillId") != skill_id:
        problems.append(f"metadata.mobilework.authSkillId({mw.get('authSkillId')!r}) != 目录名({skill_id})")
    req = mw.get("requires", {})
    tools = req.get("tools", [])
    if "mobilework_auth_request" not in tools:
        problems.append("requires.tools 缺少 mobilework_auth_request")
    env = req.get("env", {})
    for key in ("requiredAll", "requiredAny", "optional"):
        if key not in env:
            problems.append(f"requires.env 缺少 {key}")
    if "purposes" not in env:
        problems.append("requires.env 缺少 purposes")
    return problems


def build_skill(skill_id: str, out_dir: str, make_zip: bool = True):
    src = os.path.join(SKILLS_DIR, skill_id)
    if not os.path.isdir(src):
        raise SystemExit(f"[err] 源技能不存在: {src}")
    target = os.path.join(out_dir, skill_id)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)

    files = _collect(src)
    for abs_f, rel in files:
        dst = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(abs_f, dst)

    # 契约自查
    skill_md = os.path.join(target, "SKILL.md")
    problems = []
    if not os.path.isfile(skill_md):
        problems.append("SKILL.md 缺失（必须在技能根目录）")
        data = {}
    else:
        with io.open(skill_md, encoding="utf-8") as fh:
            md_text = fh.read()
        data = _parse_frontmatter(md_text)
        problems += _check_contract(skill_id, data)

    # 体积/项数统计
    total = sum(os.path.getsize(os.path.join(target, rel)) for _, rel in files)
    max_f = max(((os.path.getsize(os.path.join(target, rel)) / (1024 * 1024)), rel) for _, rel in files) if files else (0, "")
    skill_md_mib = os.path.getsize(skill_md) / (1024 * 1024) if os.path.isfile(skill_md) else 0
    n_items = len(files)

    report = {
        "skill_id": skill_id,
        "ok": True,
        "items": n_items,
        "total_mib": round(total / (1024 * 1024), 2),
        "max_file_mib": round(max_f[0], 2),
        "max_file": max_f[1],
        "skill_md_mib": round(skill_md_mib, 3),
        "limits": LIMITS,
        "problems": problems,
    }
    if n_items > LIMITS["max_items"]:
        report["ok"] = False
        problems.append(f"目录项 {n_items} > {LIMITS['max_items']}")
    if total / (1024 * 1024) > LIMITS["max_total_mib"]:
        report["ok"] = False
        problems.append("总大小超限")
    if max_f[0] > LIMITS["max_file_mib"]:
        report["ok"] = False
        problems.append(f"单文件超限: {max_f[1]}")
    if skill_md_mib > LIMITS["max_skill_md_mib"]:
        report["ok"] = False
        problems.append("SKILL.md 超限")

    zip_path = None
    if make_zip:
        zip_path = os.path.join(out_dir, f"{skill_id}.zip")
        if os.path.isfile(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for abs_f, rel in files:
                zf.write(os.path.join(target, rel), arcname=f"{skill_id}/{rel}")
        report["zip"] = zip_path
    report["dir"] = target
    return report


def main():
    ap = argparse.ArgumentParser(description="生成 MobileWork 技能上传包")
    ap.add_argument("--skills", default=",".join(SKILLS), help="逗号分隔技能名，默认全部")
    ap.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "dist", "mobilework-upload"))
    ap.add_argument("--no-zip", action="store_true", help="只生成目录不打包 zip")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    reports = []
    for sid in [s.strip() for s in args.skills.split(",") if s.strip()]:
        reports.append(build_skill(sid, out_dir, make_zip=not args.no_zip))

    for r in reports:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print("-" * 60)
    if all(r["ok"] and not r["problems"] for r in reports):
        print(f"[ok] 全部技能通过自查，产物目录: {out_dir}")
    else:
        print("[warn] 存在未通过项，请修复后重新出包。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
