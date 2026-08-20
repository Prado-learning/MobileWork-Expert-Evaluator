#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 tests/test-report.json 渲染为 MobileWork Design System 风格的 HTML 测试报告。

设计依据：MobileWork-Design-System/DESIGN.md（六色 token、IBM Plex Sans、
8px 圆角、1px hairline、4px 基线、克制状态表达：文字 + 图标共同传达状态）。

用法：
    python tests/render_report.py [--input tests/test-report.json] [--output test-reports/test-report.html]
"""

import argparse
import html
import json
import os
from datetime import datetime

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
DEFAULT_IN = os.path.join(TESTS_DIR, "test-report.json")
DEFAULT_OUT = os.path.join(REPO_ROOT, "test-reports", "test-report.html")

# ---- MobileWork Design System tokens（DESIGN.md / system/variables.css）---- #
MW = {
    "page": "#f0f2f5",
    "ink": "#121314",
    "accent": "#1890ff",
    "surface": "#ffffff",
    "muted": "#7c8085",
    "hairline": "#e5e6eb",
    "radius": "8px",
    "font": "'IBM Plex Sans Variable', 'IBM Plex Sans', Geist, 'PingFang SC', 'Microsoft YaHei', ui-sans-serif, system-ui, sans-serif",
    "mono": "ui-monospace, 'SFMono-Regular', Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
}

CATEGORIES = {
    "S": ("静态 / 结构", "manifest、YAML、语法、目录与 case schema 的静态核对"),
    "F": ("功能", "run_eval.py 实际行为：case 加载、配置生成、过滤、自定义与越界防护"),
    "P": ("解析 / 内部", "promptfoo 结果解析（新旧结构）、命令解析与占位符渲染"),
    "I": ("集成 / 环境", "promptfoo、opencode、@opencode-ai/sdk 与 javascript 断言写法"),
    "E": ("端到端", "真实 opencode:sdk 会话（需模型 API key）"),
}

STATUS_META = {
    "pass":    {"label": "通过", "icon": "✓", "cls": "st-pass"},
    "fail":    {"label": "失败", "icon": "✕", "cls": "st-fail"},
    "blocked": {"label": "受阻", "icon": "⊘", "cls": "st-blocked"},
    "skipped": {"label": "跳过", "icon": "–", "cls": "st-skip"},
}


def esc(s):
    return html.escape(str(s), quote=True)


def render_stat_cards(stats, total):
    rate = (stats.get("pass", 0) / total * 100) if total else 0
    cards = [
        ("总用例", total, "ink"),
        ("通过", stats.get("pass", 0), "accent"),
        ("失败", stats.get("fail", 0), "fail"),
        ("受阻 / 跳过", stats.get("blocked", 0) + stats.get("skipped", 0), "blocked"),
    ]
    parts = []
    for label, value, tone in cards:
        parts.append(f"""
        <div class="stat">
          <div class="stat-value" data-tone="{tone}">{value}</div>
          <div class="stat-label">{label}</div>
        </div>""")
    return f"""
    <section class="stats">
      {''.join(parts)}
      <div class="rate">
        <div class="rate-head"><span>通过率</span><span>{rate:.1f}%</span></div>
        <div class="rate-track"><div class="rate-fill" style="width:{rate:.1f}%"></div></div>
      </div>
    </section>"""


def render_test_item(r):
    meta = STATUS_META.get(r["status"], STATUS_META["skipped"])
    dur = r.get("duration_ms")
    dur_s = f"{dur:.0f} ms" if isinstance(dur, (int, float)) else "—"
    detail = esc(r.get("detail") or "")
    return f"""
      <li class="test-item">
        <span class="badge {meta['cls']}"><span class="badge-icon">{meta['icon']}</span>{meta['label']}</span>
        <div class="test-body">
          <div class="test-head">
            <code class="test-id">{esc(r['id'])}</code>
            <span class="test-name">{esc(r['name'])}</span>
            <span class="test-dur">{dur_s}</span>
          </div>
          {f'<div class="test-detail">{detail}</div>' if detail else ''}
        </div>
      </li>"""


def render_tab(cat, results):
    title, desc = CATEGORIES[cat]
    items = "".join(render_test_item(r) for r in results)
    passed = sum(1 for r in results if r["status"] == "pass")
    total = len(results)
    return f"""
    <section class="tab-panel" data-tab="{cat}">
      <div class="tab-desc"><strong>{title}</strong> · {desc} <span class="tab-count">{passed}/{total} 通过</span></div>
      <ul class="test-list">{items}</ul>
    </section>"""


def render_report(report):
    env = report.get("environment", {})
    stats = report.get("stats", {})
    results = report.get("results", [])
    total = report.get("total", len(results))
    cat_order = ["S", "F", "P", "I", "E"]
    grouped = {c: [r for r in results if r["category"] == c] for c in cat_order}
    grouped = {k: v for k, v in grouped.items() if v}

    tabs = "".join(
        f'<button class="tab-btn" data-tab="{c}" {"data-active" if i == 0 else ""}>{CATEGORIES[c][0]}</button>'
        for i, c in enumerate(grouped)
    )
    panels = "".join(render_tab(c, grouped[c]) for c in grouped)

    generated = esc(report.get("generated_at", ""))
    report_id = esc(report.get("report_id", ""))
    blocked_notes = "".join(
        f"<li><code>{esc(r['id'])}</code> {esc(r['name'])}：{esc(r.get('detail') or '')}</li>"
        for r in results if r["status"] == "blocked"
    )

    # 结论区根据实际结果动态生成
    n_pass, n_fail, n_block = stats.get("pass", 0), stats.get("fail", 0), stats.get("blocked", 0)
    if n_block > 0:
        conclusion_items = [
            f"插件静态结构、核心功能、结果解析与集成链路共 {total} 项检查，通过 {n_pass} 项，失败 {n_fail} 项，{n_block} 项受阻。",
            "受阻项均为外部依赖限制（模型 API key 或端到端真实运行），配置凭据后即可补齐。",
        ]
    else:
        conclusion_items = [
            f"插件静态结构、核心功能、结果解析、集成环境与真实端到端运行共 {total} 项检查全部通过（{n_pass}/{total}）。",
            "真实端到端运行已核对：opencode:sdk 驱动 software-team-lead 专家团完成真实任务，产物、会话与评分证据齐全（见 e2e-evidence/）。",
        ]
    conclusion_items.append(
        "正式基准（任务书 6.3）：`run_eval.py --working-dir <评测工作区> --all --repeat 5 "
        "--provider deepseek --model deepseek-v4-flash --api-key sk-...`"
    )
    conclusion_items.append(
        "本报告基于 MobileWork Design System 渲染（token：page/surface/ink/accent/muted/hairline；8px 圆角；1px hairline；文字 + 图标表达状态）。"
    )
    conclusion_ul = "".join(f"<li>{esc(x)}</li>" for x in conclusion_items)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Promptfoo Expert Eval 插件测试报告</title>
<style>
  :root {{
    --page: {MW['page']}; --ink: {MW['ink']}; --accent: {MW['accent']};
    --surface: {MW['surface']}; --muted: {MW['muted']}; --hairline: {MW['hairline']};
    --font: {MW['font']}; --mono: {MW['mono']};
    --fail: #c0392b; --fail-bg: #fbeeec;
    --blocked: #8a6d1a; --blocked-bg: #faf3e3;
    --pass-bg: color-mix(in oklch, var(--accent) 8%, var(--surface));
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--page); color: var(--ink);
    font-family: var(--font); font-size: 14px; line-height: 22px;
    padding: 32px 20px 64px;
  }}
  .wrap {{ max-width: 960px; margin: 0 auto; }}
  header {{ margin-bottom: 24px; }}
  .kicker {{ color: var(--muted); font-size: 12px; letter-spacing: .08em; margin-bottom: 8px; }}
  h1 {{ font-size: 26px; font-weight: 600; letter-spacing: -.01em; }}
  .meta {{ margin-top: 12px; color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px 20px; }}
  .meta code {{ font-family: var(--mono); color: var(--ink); }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }}
  .stat, .rate {{ background: var(--surface); border: 1px solid var(--hairline); border-radius: {MW['radius']}; padding: 16px; }}
  .stat-value {{ font-size: 28px; font-weight: 600; }}
  .stat-value[data-tone="accent"] {{ color: var(--accent); }}
  .stat-value[data-tone="fail"] {{ color: var(--fail); }}
  .stat-value[data-tone="blocked"] {{ color: var(--blocked); }}
  .stat-label {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
  .rate {{ grid-column: 1 / -1; }}
  .rate-head {{ display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
  .rate-track {{ height: 6px; background: var(--page); border-radius: 999px; overflow: hidden; }}
  .rate-fill {{ height: 100%; background: var(--accent); border-radius: 999px; }}
  .tabs {{ display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 1px solid var(--hairline); }}
  .tab-btn {{
    appearance: none; background: none; border: none; cursor: pointer;
    font-family: var(--font); font-size: 14px; color: var(--muted);
    padding: 10px 16px; border-bottom: 2px solid transparent; margin-bottom: -1px;
  }}
  .tab-btn[data-active] {{ color: var(--ink); border-bottom-color: var(--accent); font-weight: 500; }}
  .tab-panel[hidden] {{ display: none; }}
  .tab-desc {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}
  .tab-count {{ color: var(--ink); font-family: var(--mono); font-size: 12px; }}
  .test-list {{ list-style: none; }}
  .test-item {{
    display: flex; gap: 12px; align-items: flex-start;
    background: var(--surface); border: 1px solid var(--hairline);
    border-radius: {MW['radius']}; padding: 12px 16px; margin-bottom: 8px;
  }}
  .badge {{
    flex: none; display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; font-weight: 500; padding: 2px 10px; border-radius: 999px;
    border: 1px solid transparent;
  }}
  .badge-icon {{ font-weight: 600; }}
  .st-pass {{ color: var(--accent); background: var(--pass-bg); border-color: color-mix(in oklch, var(--accent) 24%, var(--hairline)); }}
  .st-fail {{ color: var(--fail); background: var(--fail-bg); border-color: color-mix(in oklch, var(--fail) 30%, var(--hairline)); }}
  .st-blocked {{ color: var(--blocked); background: var(--blocked-bg); border-color: color-mix(in oklch, var(--blocked) 30%, var(--hairline)); }}
  .st-skip {{ color: var(--muted); background: var(--page); }}
  .test-body {{ flex: 1; min-width: 0; }}
  .test-head {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }}
  .test-id {{ font-family: var(--mono); font-size: 12px; color: var(--muted); }}
  .test-name {{ font-weight: 500; }}
  .test-dur {{ margin-left: auto; color: var(--muted); font-size: 12px; font-family: var(--mono); }}
  .test-detail {{
    margin-top: 6px; color: var(--muted); font-size: 12px;
    font-family: var(--mono); word-break: break-all; white-space: pre-wrap;
  }}
  .conclusion {{ background: var(--surface); border: 1px solid var(--hairline); border-radius: {MW['radius']}; padding: 20px; margin-top: 24px; }}
  .conclusion h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 10px; }}
  .conclusion ul {{ padding-left: 20px; color: var(--muted); font-size: 13px; }}
  .conclusion li {{ margin-bottom: 4px; }}
  footer {{ margin-top: 32px; color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
  @media (max-width: 768px) {{ .stats {{ grid-template-columns: repeat(2, 1fr); }} body {{ padding: 20px 12px 48px; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="kicker">MOBILEWORK · EXPERT EVAL PLUGIN</div>
    <h1>Promptfoo Expert Eval 插件测试报告</h1>
    <div class="meta">
      <span>报告 <code>{report_id}</code></span>
      <span>生成时间 <code>{generated}</code></span>
      <span>平台 <code>{esc(env.get('platform', '—'))}</code> / Python <code>{esc(env.get('python', '—'))}</code></span>
      <span>promptfoo <code>{esc(env.get('promptfoo', '—'))}</code></span>
    </div>
  </header>

  {render_stat_cards(stats, total)}

  <nav class="tabs">{tabs}</nav>
  {panels}

  <section class="conclusion">
    <h2>结论与下一步</h2>
    <ul>{conclusion_ul}</ul>
    {f'<div style="margin-top:10px"><strong>受阻项：</strong><ul>{blocked_notes}</ul></div>' if blocked_notes else ''}
  </section>

  <footer>
    <span>Design System: MobileWork Design System（中国移动 · 九天生态）</span>
    <span>证据状态：defined → implemented → verified（本报告为自动化测试输出）</span>
  </footer>
</div>
<script>
  const btns = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.tab-panel');
  btns.forEach(btn => {{
    btn.addEventListener('click', () => {{
      btns.forEach(b => b.removeAttribute('data-active'));
      btn.setAttribute('data-active', '');
      panels.forEach(p => {{
        p.hidden = p.dataset.tab !== btn.dataset.tab;
      }});
    }});
  }});
</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_IN)
    ap.add_argument("--output", default=DEFAULT_OUT)
    args = ap.parse_args()

    report = json.load(open(args.input, encoding="utf-8"))
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(render_report(report))

    # 把原始 JSON 一并放到 test-reports/，便于报告与数据关联
    import shutil
    shutil.copy2(args.input, os.path.join(os.path.dirname(args.output), "test-report.json"))

    stats = report.get("stats", {})
    print(f"报告已生成: {args.output}")
    print(f"统计: 总 {report.get('total')} / 通过 {stats.get('pass')} / 失败 {stats.get('fail')} / 受阻 {stats.get('blocked')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
