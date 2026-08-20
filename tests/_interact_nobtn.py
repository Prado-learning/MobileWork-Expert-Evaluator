#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保持画面不变，把交互绑定到原有元素（代码块/表格行/卡片）：
1) 删除上一轮添加的按钮与按钮列；2) 给元素加 data-dialog + title；3) CSS 替换。"""
import os, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(REPO, 'docs', 'promptfoo-eval-tutorial.html')
h = open(p, encoding='utf-8').read()

# ---- 1) 删除全部按钮（含包裹 <p>/<td>）----
# 独立按钮行（agent / config / debug）
for pat in [
    r'\s*<p><button class="btn-detail" data-dialog="d-agent-out">[^<]*</button></p>',
    r'\s*<p style="margin-top:12px"><button class="btn-detail" data-dialog="d-config">[^<]*</button></p>',
    r'\s*<p style="margin-top:20px"><button class="btn-detail" data-dialog="d-debug">[^<]*</button></p>',
]:
    h, n = re.subn(pat, '', h)
    print("删除按钮行:", n)
# case 表按钮列
h, n = re.subn(r'<td><button class="btn-detail" data-dialog="d-case-[^"]*">详情</button></td>', '', h)
print("删除 case 按钮列:", n)
# 表头空列
h = h.replace('<th></th>', '', 1)
print("删除表头空列")

# ---- 2) 给原有元素加 data-dialog + title ----
# 2.1 Step4 配置 code-wrap
def tag_codewrap(m):
    block = m.group(0)
    if 'promptfooconfig.yaml · opencode:sdk' in block and '<div class="code-wrap"' in block:
        return block.replace('<div class="code-wrap">', '<div class="code-wrap" data-dialog="d-config" title="点击查看 opencode:sdk 配置详解">', 1)
    if 'agent 输出 · software-team-lead' in block:
        return block.replace('<div class="code-wrap">', '<div class="code-wrap" data-dialog="d-agent-out" title="点击查看完整交付总结（真实输出）">', 1)
    return block
h, _ = re.subn(r'<div class="code-wrap">.*?</div>\s*</div>', tag_codewrap, h, flags=re.S)

# 2.2 case 表行
for cid in ('todo-cli', 'prd-priority', 'feature-design', 'bugfix-utils'):
    old = f'<tr><td><code>{cid}</code></td>'
    new = f'<tr data-dialog="d-case-{cid}" title="点击查看 case 完整定义（提示词/断言/主指标）"><td><code>{cid}</code></td>'
    assert old in h, f"case 行 {cid} 未找到"
    h = h.replace(old, new, 1)

# 2.3 排障卡片（4 个 col）
h, n = re.subn(r'<div class="col">', '<div class="col" data-dialog="d-debug" title="点击查看完整排障过程">', h)
print("排障卡加交互:", n)

# ---- 3) CSS：按钮样式替换为元素交互样式 ----
old_css = """  /* Interactive detail dialog */
  .btn-detail { appearance: none; border: 1px solid var(--hairline-strong); background: var(--surface); color: var(--accent-strong); font-family: var(--font-sans); font-size: 12.5px; font-weight: 600; padding: 5px 14px; border-radius: 999px; cursor: pointer; transition: all var(--t-fast); }
  .btn-detail:hover { border-color: var(--accent); background: var(--accent-bg); }"""
new_css = """  /* Interactive detail —— 绑定到原有元素，画面零变化 */
  [data-dialog] { cursor: pointer; }
  tr[data-dialog]:hover td { background: color-mix(in oklch, var(--accent-bg) 55%, var(--surface)); }
  .col[data-dialog]:hover { background: color-mix(in oklch, var(--accent-bg) 60%, var(--surface)); }
  .code-wrap[data-dialog]:hover pre { box-shadow: 0 0 0 1.5px var(--accent); }
  .code-wrap[data-dialog] { transition: box-shadow var(--t-fast); }"""
assert old_css in h, "按钮 CSS 未找到"
h = h.replace(old_css, new_css, 1)

open(p, 'w', encoding='utf-8').write(h)
print("完成，文件大小:", len(h))
print("剩余 btn-detail:", h.count('btn-detail'))
print("data-dialog 总数:", h.count('data-dialog="'))
