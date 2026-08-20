#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 docs/promptfoo-eval-tutorial.html 增加可交互详情弹窗（<dialog>）：
- 4 个 case 完整定义（提示词/断言/主指标/异常判定）
- opencode:sdk 配置详解
- agent 完整交付总结（真实输出）
- 完整排障过程
"""
import os, re, html as H, json, yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(REPO, 'docs', 'promptfoo-eval-tutorial.html')
h = open(p, encoding='utf-8').read()

cases = yaml.safe_load(open(os.path.join(REPO, 'skills', 'promptfoo-expert-eval', 'cases', 'default-cases.yaml'), encoding='utf-8'))
agent_out = ''
rp = os.path.join(REPO, 'test-reports', 'e2e-evidence', 'bugfix-utils-results.json')
if os.path.exists(rp):
    r = json.load(open(rp, encoding='utf-8'))['results']['results'][0]
    resp = r.get('response') or {}
    agent_out = resp.get('output') or resp.get('raw') or ''

TYPE_LABEL = {'structured': '结构化', 'hybrid': '混合式', 'open-ended': '开放式'}

def esc(s):
    return H.escape(str(s), quote=True)

def case_dialog(c):
    meta = f"""<table>
      <tr><th style="width:140px">字段</th><th>值</th></tr>
      <tr><td>id</td><td><code>{esc(c['id'])}</code></td></tr>
      <tr><td>title</td><td>{esc(c['title'])}</td></tr>
      <tr><td>type</td><td>{esc(TYPE_LABEL.get(c['type'], c['type']))}（<code>{c['type']}</code>）</td></tr>
      <tr><td>output_dir</td><td><code>{esc(c.get('output_dir', ''))}</code></td></tr>
      <tr><td>main_metric</td><td>{esc(c.get('main_metric', '—'))}</td></tr>
      <tr><td>anomaly_rules</td><td>{esc(c.get('anomaly_rules', '—'))}</td></tr>
      <tr><td>bash_allow</td><td><code>{esc(', '.join(c.get('bash_allow', [])) or '默认白名单')}</code></td></tr>
    </table>"""
    setup = ''
    if c.get('setup'):
        setup = '<h4>Setup Fixtures（预置文件）</h4>' + ''.join(
            f'<pre>{esc(f["path"])}</pre><pre class="dlg-code">{esc(f["content"])}</pre>'
            for f in c['setup'].get('files', []))
    asserts = '<h4>断言（assertions）</h4><pre class="dlg-code">' + esc(yaml.safe_dump(c['assertions'], allow_unicode=True, sort_keys=False)) + '</pre>'
    return f"""<dialog id="d-case-{c['id']}" class="detail-dialog">
    <div class="dlg-head"><h3>case · {esc(c['id'])}</h3><button class="dlg-close" data-close aria-label="关闭">✕</button></div>
    <div class="dlg-body">
      {meta}
      <h4>Prompt（发送给团长的任务文本）</h4>
      <pre class="dlg-code">{esc(c['prompt'])}</pre>
      {asserts}
      {setup}
    </div>
  </dialog>"""

dialogs = ''.join(case_dialog(c) for c in cases)

# D5: agent 完整交付总结
d_agent = f"""<dialog id="d-agent-out" class="detail-dialog">
    <div class="dlg-head"><h3>agent 完整交付总结 · software-team-lead（真实运行 bugfix-utils）</h3><button class="dlg-close" data-close aria-label="关闭">✕</button></div>
    <div class="dlg-body">
      <p class="dlg-note">来源：<code>test-reports/e2e-evidence/bugfix-utils-results.json</code> · eval <code>eval-rUe-2026-08-03T15:39:02</code> · 会话 <code>ses_037b8b519ffeGNoIeqIX7BRdT8</code></p>
      <pre class="dlg-code">{esc(agent_out)}</pre>
    </div>
  </dialog>"""

# D6: opencode:sdk 配置详解
d_cfg = """<dialog id="d-config" class="detail-dialog">
    <div class="dlg-head"><h3>opencode:sdk 配置详解</h3><button class="dlg-close" data-close aria-label="关闭">✕</button></div>
    <div class="dlg-body">
      <table>
        <tr><th style="width:180px">配置项</th><th>值</th><th>说明</th></tr>
        <tr><td><code>working_dir</code></td><td><code>workspaces/test01-eval</code></td><td>评测专用工作区（权限已适配非交互；原始工作区只读）</td></tr>
        <tr><td><code>agent</code></td><td><code>software-team-lead</code></td><td>被测团长：OpenCode 从工作区加载 agent 定义并驱动真实会话</td></tr>
        <tr><td><code>provider_id</code> / <code>model</code></td><td><code>deepseek</code> / <code>deepseek-v4-flash</code></td><td>模型凭据；deepseek 不在 promptfoo 的 env 映射表，须 <code>--api-key</code> 注入</td></tr>
        <tr><td><code>tools</code></td><td>read/grep/glob/list/write/edit/todowrite/lsp/bash</td><td>授予评测运行所需工具面</td></tr>
        <tr><td><code>permission.bash</code></td><td>白名单 allow，其余 deny</td><td>非交互安全面：node/git 只读命令放行，rm/del 类 deny</td></tr>
        <tr><td><code>permission</code> 其他</td><td>external_directory / doom_loop / question → deny</td><td>评测隔离：不越界、不循环、不提问</td></tr>
        <tr><td><code>task</code></td><td>allow</td><td>团长委派 4 团员（subagent）必需</td></tr>
      </table>
      <h4>完整 YAML（run_eval.py 生成）</h4>
      <pre class="dlg-code">providers:
  - id: opencode:sdk
    config:
      working_dir: C:/project/mobile_intern/workspaces/test01-eval
      agent: software-team-lead
      provider_id: deepseek
      model: deepseek-v4-flash
      apiKey: sk-...
      tools:
        read: true
        grep: true
        glob: true
        list: true
        write: true
        edit: true
        todowrite: true
        lsp: true
        bash: true
      permission:
        read: allow
        grep: allow
        glob: allow
        list: allow
        lsp: allow
        write: allow
        edit: allow
        todowrite: allow
        task: allow
        webfetch: deny
        external_directory: deny
        doom_loop: deny
        question: deny
        skill: deny
        bash:
          '*': deny
          'node *': allow
          'git status*': allow
          'git diff*': allow
          'git log*': allow
prompts:
  - &lt;case prompt 文本&gt;
tests:
  - vars: {}
    assert:
      - type: javascript
        value: |
          const fsp = import('node:fs');
          return fsp.then(m =&gt; m.default.existsSync({output_dir_abs} + '/utils/utils.js'));</pre>
    </div>
  </dialog>"""

# D7: 排障过程详解
d_debug = """<dialog id="d-debug" class="detail-dialog">
    <div class="dlg-head"><h3>真实运行排障过程（4 个根因）</h3><button class="dlg-close" data-close aria-label="关闭">✕</button></div>
    <div class="dlg-body">
      <h4>① API key 映射缺失</h4>
      <p class="dlg-note">现象：报 <code>Missing OPENCODE_API_KEY</code>。排查：读 promptfoo 源码发现 opencode:sdk 的 <code>getApiKey</code> 只映射 anthropic/openai/google 的环境变量，deepseek 不在表内——提示名有误导性，实际缺的是模型 provider 的 key。解决：<code>--api-key</code> 显式注入 + <code>--provider deepseek</code>。</p>
      <h4>② agent 权限优先导致会话中止</h4>
      <p class="dlg-note">现象：agent 运行 5 分钟后 Aborted，最终输出丢失。排查：opencode 日志显示 <code>asking permission=bash action=ask</code>；agent 权限以 <code>agents/*.md</code> frontmatter 为准且优先于 provider <code>permission</code>。解决：创建评测专用工作区 <code>test01-eval</code>，把 bash 改为白名单 allow（保留 rm/del 类 deny）、external_directory/doom_loop/question → deny；原始工作区与专家包保持只读。</p>
      <h4>③ opencode 全局数据库并发写</h4>
      <p class="dlg-note">现象：<code>SQLite FOREIGN KEY constraint failed</code>。排查：promptfoo 每次 eval 启动独立 opencode server，多个 server 并发写同一 <code>~/.local/share/opencode/opencode.db</code>。解决：run_eval.py 为每个 run 设置独立 <code>XDG_DATA_HOME</code>（<code>&lt;run-dir&gt;/opencode-data/</code>），同时保证环境隔离可复现。</p>
      <h4>④ opencode SDK 默认 5 分钟超时</h4>
      <p class="dlg-note">现象：完整 SOP 任务超过 300s 被 cancel。排查：SDK 文档确认 <code>session.prompt</code> 默认 provider 超时 300000ms。解决：case 规模控制在窗口内（todo-cli 改快速流程），长任务拆分；运行时用 <code>--case-timeout-sec</code> 兜底。</p>
    </div>
  </dialog>"""

dialogs_all = dialogs + d_agent + d_cfg + d_debug

# ---- 1) 在 </body> 前插入 dialogs + JS ----
js = """<script>
  document.querySelectorAll('[data-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      var d = document.getElementById(b.dataset.dialog);
      if (d && typeof d.showModal === 'function') d.showModal();
    });
  });
  document.querySelectorAll('[data-close]').forEach(function (b) {
    b.addEventListener('click', function () { var d = b.closest('dialog'); if (d) d.close(); });
  });
  document.querySelectorAll('dialog').forEach(function (d) {
    d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { document.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); }); }
  });
</script>
"""
block = '\n' + dialogs_all + '\n' + js + '</body>'
assert '</body>' in h
h = h.replace('</body>', block, 1)

# ---- 2) 触发按钮 ----
# 2.1 case 表：每行加"详情"按钮（§4 内置 case 一览）
btn_case = lambda cid: f'<td><button class="btn-detail" data-dialog="d-case-{cid}">详情</button></td>'
for c in cases:
    row_pat = f'<td><code>{c["id"]}</code></td>'
    if row_pat in h:
        # 在行末尾 </tr> 前加按钮列（用该行唯一标题定位）
        title = c['title']
        tr_pat = re.compile(r'(<tr><td><code>' + re.escape(c['id']) + r'</code></td>.*?</tr>)', re.S)
        m = tr_pat.search(h)
        if m:
            h = h.replace(m.group(0), m.group(0).replace('</tr>', btn_case(c['id']) + '</tr>', 1), 1)
# 表头加空列
h = h.replace('<tr><th>case</th><th>类型</th><th>任务</th><th>评测方法</th></tr>',
              '<tr><th>case</th><th>类型</th><th>任务</th><th>评测方法</th><th></th></tr>', 1)

# 2.2 交付总结：pre 前加"查看完整输出"按钮
btn_agent = '<p><button class="btn-detail" data-dialog="d-agent-out">查看完整交付总结（真实输出）</button></p>'
anchor_out = 'agent 输出 · software-team-lead'  # code-head 标签
# 定位 §4 交付总结 code-wrap（含"交付总结 · 工具库"的 pre）
m4 = re.search(r'<div class="code-wrap"><div class="code-head"><span>agent 输出 · software-team-lead</span>', h)
assert m4, "交付总结 code-wrap 未找到"
h = h.replace(m4.group(0), btn_agent + '\n  ' + m4.group(0), 1)

# 2.3 Step4 配置：代码块后加"配置详解"
btn_cfg = '<p style="margin-top:12px"><button class="btn-detail" data-dialog="d-config">查看 opencode:sdk 配置详解</button></p>'
anchor_cfg = '<span>promptfooconfig.yaml · opencode:sdk</span>'
idx = h.find(anchor_cfg)
assert idx >= 0, "Step4 配置块未找到"
end = h.find('</pre></div>', idx)
assert end >= 0, "Step4 配置块结束未找到"
h = h[:end + len('</pre></div>')] + '\n  ' + btn_cfg + h[end + len('</pre></div>'):]

# 2.4 排障：col-grid 后加"查看完整排障过程"
btn_debug = '<p style="margin-top:20px"><button class="btn-detail" data-dialog="d-debug">查看完整排障过程（含排查细节）</button></p>'
m6 = re.search(r'<div class="col-grid">.*?</div>\s*(</div>|</section>)', h, re.S)
assert m6, "排障 col-grid 未找到"
h = h.replace(m6.group(0), m6.group(0) + '\n  ' + btn_debug, 1)

# ---- 3) CSS ----
css = """
  /* Interactive detail dialog */
  .btn-detail { appearance: none; border: 1px solid var(--hairline-strong); background: var(--surface); color: var(--accent-strong); font-family: var(--font-sans); font-size: 12.5px; font-weight: 600; padding: 5px 14px; border-radius: 999px; cursor: pointer; transition: all var(--t-fast); }
  .btn-detail:hover { border-color: var(--accent); background: var(--accent-bg); }
  dialog.detail-dialog { border: 1px solid var(--hairline-strong); border-radius: 10px; padding: 0; max-width: 760px; width: 92vw; max-height: 82vh; box-shadow: var(--shadow-md); background: var(--surface); color: var(--ink); }
  dialog.detail-dialog::backdrop { background: rgb(18 19 20 / .45); backdrop-filter: blur(2px); }
  .dlg-head { position: sticky; top: 0; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 22px; border-bottom: 1px solid var(--hairline); background: var(--surface); z-index: 2; }
  .dlg-head h3 { font-size: 15px; font-weight: 600; margin: 0; }
  .dlg-close { appearance: none; border: none; background: var(--page); color: var(--muted); width: 28px; height: 28px; border-radius: 50%; cursor: pointer; font-size: 13px; transition: all var(--t-fast); }
  .dlg-close:hover { background: var(--accent-bg); color: var(--accent-strong); }
  .dlg-body { padding: 20px 22px 26px; overflow-y: auto; max-height: calc(82vh - 57px); }
  .dlg-body h4 { font-size: 13px; font-weight: 600; margin: 18px 0 8px; color: var(--accent-strong); text-transform: uppercase; letter-spacing: .05em; }
  .dlg-body h4:first-child { margin-top: 0; }
  .dlg-note { color: var(--muted); font-size: 12.5px; margin: 8px 0; line-height: 1.7; }
  .dlg-code { margin: 6px 0 12px !important; }
"""
h = h.replace('</style>', css + '\n</style>', 1)

open(p, 'w', encoding='utf-8').write(h)
print("交互弹窗已添加，文件大小:", len(h))
print("dialog 数量:", h.count('<dialog'))
print("触发按钮数量:", h.count('data-dialog="'))
