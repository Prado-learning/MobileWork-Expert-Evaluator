#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""1) 中国移动 logo 移到 topbar 左侧；2) 删除 §7 课题任务图集板块及其图片文件。"""
import os, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(REPO, 'docs', 'promptfoo-eval-tutorial.html')
h = open(p, encoding='utf-8').read()

# ---- 1) 删除 §7 图集板块（含 4 个 figure）----
m = re.search(r'<section class="content-section" id="figures">.*?</section>', h, re.S)
assert m, "§7 图集板块未找到"
h = h.replace(m.group(0), '', 1)

# ---- 2) topbar：中国移动 logo 移到左侧品牌区，右侧只留导航 ----
old_tb = """    <div class="topbar-brand"><img class="brand-icon" src="figures/brand/mobilework-product-icon.png" alt="MobileWork">Promptfoo Expert Eval</div>
    <div class="topbar-right">
      <nav>
        <a href="#progress">01 背景与进展</a>
        <a href="#principle">02 评测原理</a>
        <a href="#tutorial">03 教程</a>
        <a href="#demo">04 真实演示</a>
        <a href="#debug">05 排障</a>
        <a href="#checklist">06 对照</a>
        <a href="#figures">07 图集</a>
      </nav>
      <img class="cmcc-logo" src="figures/brand/china-mobile-logo.png" alt="中国移动">
    </div>"""
new_tb = """    <div class="topbar-brand">
      <img class="cmcc-logo" src="figures/brand/china-mobile-logo.png" alt="中国移动">
      <img class="brand-icon" src="figures/brand/mobilework-product-icon.png" alt="MobileWork">
      <span>Promptfoo Expert Eval</span>
    </div>
    <div class="topbar-right">
      <nav>
        <a href="#progress">01 背景与进展</a>
        <a href="#principle">02 评测原理</a>
        <a href="#tutorial">03 教程</a>
        <a href="#demo">04 真实演示</a>
        <a href="#debug">05 排障</a>
        <a href="#checklist">06 对照</a>
      </nav>
    </div>"""
assert old_tb in h, "topbar 结构未找到"
h = h.replace(old_tb, new_tb, 1)

# topbar-brand 现在含 img + span，需对齐
old_css = '.topbar-brand { display: flex; align-items: center; gap: 10px; font-weight: 600; font-size: 14px; letter-spacing: -.01em; }'
new_css = '.topbar-brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; letter-spacing: -.01em; }\n  .topbar-brand .cmcc-logo { height: 20px; }\n  .topbar-brand .brand-icon { height: 18px; }'
assert old_css in h, "topbar-brand CSS 未找到"
h = h.replace(old_css, new_css, 1)

open(p, 'w', encoding='utf-8').write(h)
print("HTML 修改完成，大小:", len(h))

# ---- 3) 删除不再引用的 4 个任务书图文件 ----
fig_dir = os.path.join(REPO, 'docs', 'figures')
for f in ('workbuddy-marketplace.png', 'mobilework-opencode.png',
          'promptfoo-results.png', 'openwork-claude-plugin-import.png'):
    fp = os.path.join(fig_dir, f)
    if os.path.exists(fp):
        os.remove(fp)
        print("已删除:", f)
