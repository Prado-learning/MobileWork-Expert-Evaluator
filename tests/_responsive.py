#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""响应式适配：1) 手机取消 zoom（桌面保留 1.5）；2) 表格包横向滚动容器；
3) 手机断点间距/字号/触控目标；4) dialog 手机适配。"""
import os, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(REPO, 'docs', 'promptfoo-eval-tutorial.html')
h = open(p, encoding='utf-8').read()

# ---- 1) zoom 仅桌面生效 ----
old_zoom = 'html { scroll-behavior: smooth; zoom: 1.5; }'
new_zoom = 'html { scroll-behavior: smooth; }\n  @media (min-width: 901px) { html { zoom: 1.5; } }'
assert old_zoom in h, "zoom 规则未找到"
h = h.replace(old_zoom, new_zoom, 1)

# ---- 2) 所有表格包横向滚动容器 ----
h, n_tbl = re.subn(r'(<table>.*?</table>)', r'<div class="tbl-wrap">\1</div>', h, flags=re.S)
print("表格已包裹:", n_tbl, "个")

# ---- 3) 响应式 CSS（追加到 </style> 前）----
resp_css = """
  /* ---------- Responsive (mobile-first refinements) ---------- */
  .tbl-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: var(--radius); }
  .tbl-wrap table { margin: 20px 0; min-width: 480px; }
  dialog .tbl-wrap table { margin: 10px 0; }

  @media (max-width: 900px) {
    .content-section { padding: 64px 18px; }
    .hero { padding: 56px 18px 64px; }
    .topbar-inner { padding: 10px 18px; }
    .fig-frame { padding: 14px; }
    .brief-facts { padding: 20px; }
    .dlg-head { padding: 12px 16px; }
    .dlg-body { padding: 16px 18px; }
    dialog.detail-dialog { max-width: 96vw; width: 96vw; }
    .result-hero { padding: 22px 20px; }
  }

  @media (max-width: 560px) {
    .hero h1 { font-size: 30px; }
    .hero .hero-lead { font-size: 15px; }
    .content-section > h2 { font-size: 24px; }
    .result-score { font-size: 44px; }
    .step { grid-template-columns: 38px 1fr; gap: 14px; padding: 18px 0; }
    .step-no { width: 38px; height: 38px; font-size: 13px; }
    .goal-no { width: 48px; height: 48px; font-size: 15px; }
    .dlg-close { width: 36px; height: 36px; }
    .badge { font-size: 10.5px; padding: 2px 8px; }
    .callout { padding: 14px 16px; font-size: 13px; }
    .cards .card { padding: 16px; }
    .topbar-brand span { font-size: 12.5px; }
  }
"""
h = h.replace('</style>', resp_css + '\n</style>', 1)

open(p, 'w', encoding='utf-8').write(h)
print("响应式适配完成，文件大小:", len(h))
