---
name: promptfoo-expert-eval
description: >-
  MobileEval 专家（团）评测能力。当用户要求：评测/评估某个专家或专家团、生成评测用例或
  评测 case、批量审核 case、发起真实评测（promptfoo + opencode）、查看评测结果与优化建议、
  或打开 MobileEval 评测中心网页时触发。**一旦触发，自动启动评测中心并立即在客户端浏览器弹出
  评测中心网页（无需用户先要求打开网页）**。能力覆盖：分析专家团 → 生成 case →
  审核 → 真实评测 → 优化建议，并可在客户端内置浏览器打开评测中心（网页 + 后端）。
  创建/转换/编辑专家（而非评测）的需求转交独立安装的 mobilework-expert-manager 技能处理，
  生成 OpenCode 格式专家包（含 .opencode/agents/*.md）后再回到本评测流程 import-expert → 评测。
compatibility: Requires Python 3.10+ 与 Node.js 18+（npm）——两者缺失时先征求用户同意再协助安装（见「环境准备」）。flask / promptfoo / opencode CLI 缺失时自动安装（mobileeval_ctl deps）；@opencode-ai/sdk 由 promptfoo 内置；PyYAML 可选（缺失时 case 用 .json 格式）。
metadata:
  version: 0.2.0
  mobilework:
    authContractVersion: 1
    authSkillId: promptfoo-expert-eval
    requires:
      tools:
        - mobilework_auth_request
      env:
        requiredAll: []
        requiredAny: []
        optional: []
        purposes: {}
---

# MobileEval 专家（团）评测

通过真实 OpenCode 会话（promptfoo `opencode:sdk` provider）驱动被测专家（团）执行评测，
产物与结果统一写入 SQLite（评测数据库），网页端展示数据、case 审核与报告。

```text
analyze-expert 分析 → generate-cases 生成 case → review-cases 审核
    → run-eval 真实评测（promptfoo + opencode）→ suggest 优化建议 → 网页查看
```

默认用中文沟通；命令、路径与代码保持原文。

## MobileWork 授权执行约定（每次会话运行脚本前必须执行，双环境自适应）

本技能按 MobileWork 技能接入协议（authContractVersion=1）运行，执行任何命令前先完成授权握手，
**在线版与离线版都适用**：

1. **运行任何 python 命令之前**，先调用工具 `mobilework_auth_request`，输入严格为
   `{"skill_id":"promptfoo-expert-eval"}`（严格 JSON：无注释/尾逗号/Markdown 围栏）。
2. 把 Tool 返回的字符串解析为 JSON，**仅当 `schema_version == 1 && ok == true && code == "AUTHORIZED"` 时**
   才继续执行脚本；否则：
   - `NOT_LOGGED_IN`/`TOKEN_EXPIRED`（含**离线版客户端无企业登录通道**的情形）→ 按第 3 条判定后
     **允许离线降级执行**，不阻塞本技能纯本地动作；
   - `UNKNOWN_SKILL`→ 核对环境(UAT/PROD)与目录名/name/authSkillId 三处一致；`SKILL_PACKAGE_CHANGED`→
     等客户端同步完成后重新调 Tool；其余错误码如实展示，不猜测、不运行脚本、不要求用户手工输入凭证。
3. **纯离线声明 + 离线降级条件**：本技能契约 `env` 全空——不声明、不读取任何受管业务变量
   （JWT/工号/票据/随包密钥均不需要），因此授权失败**不会遗漏任何需注入的变量**。当第 2 条返回
   未登录类错误时，判定当前为**离线模式**：向用户提示"离线模式：跳过授权"，然后**仅**执行纯本地动作
   （启动评测中心网页、跑 opencode 评测、生成/审核 case、直连用户自配模型等）；
   **不得**执行任何需要企业身份/网关票据的动作（如向平台网关上报），也**禁止**从
   `.env`/配置文件/用户输入"补值"兜底任何受管变量。
4. 授权只在**当前 Agent 会话**内有效：换会话、切账号、切 UAT/PROD、包更新后都要重新调用 Tool；
   同一会话为其他技能再调 Tool 会**覆盖**本授权，因此每个会话先做第 1 步再连续执行本流程命令。
5. **安装目录只读红线**：技能目录内禁止写入任何文件（含日志/缓存/数据库/`__pycache__`）——
   写入会使包摘要变化、授权失效。**所有 python 一律以 `python -B` 执行**（禁止生成字节码缓存）；
   日志、数据库、workspaces、评测产物只写到用户数据目录（`MOBILEEVAL_HOME` 或工作区），
   不打印/落盘任何凭证值；子进程继承环境变量，不要传全新空 `env`。

## 技能协作：mobilework-expert-manager（何时调用）

`mobilework-expert-manager`（专家包管理器）是**独立安装**的技能（非本包内嵌目录），与本评测流程互补，
**触发时机按用户意图区分**：

| 用户要求 | 执行者 | 说明 |
|---|---|---|
| 评测/评估/生成 case/审核/发起评测/看报告 | **本技能**（promptfoo-expert-eval） | 走下方标准评测工作流 |
| **创建**新专家/专家团（按自然语言） | **mobilework-expert-manager** | 加载其 SKILL.md，先确认业务方案再生成 OpenCode 专家包 |
| **转换**非 OpenCode 格式为 OpenCode 格式 | **mobilework-expert-manager** | 按迁移/诊断流程转换 |
| **编辑**/修改已有专家或专家团 | **mobilework-expert-manager** | 受控修改，遵守其 controlled-modification 协议 |
| 创建/转换/编辑**完成后**要评测 | **先 manager 后本技能** | 用生成/修改后的包走 import-expert → 评测 |

**协作铁律：**
1. 用户意图是"创建/转换/编辑"→ **必须**加载已安装的 `mobilework-expert-manager` 技能（SKILL.md 与
   scripts 在其独立安装目录，见下「定位已安装技能」），按其协议执行，不得用本评测流程的
   `import-expert`/`analyze-expert` 代替（那些是评测侧能力，不生成专家包）。
2. manager 生成/修改的专家包是标准 OpenCode 格式（`expert.json` manifest +
   `.opencode/agents/*.md` + `opencode.json`），与本评测的导入格式天然兼容。
3. 评测对象缺失或格式不符时，提示用户先用 manager 技能创建/转换，再回到本流程。
4. 两个技能共享同一工作区时，路径以各自对象记录为准，不互相改写对方产物。

## 关键路径（先确认存在）

- **插件脚本目录**：本 skill 目录下的 `scripts/`（`expert_tools.py` AI 生成类、`run_eval.py` 评测执行、
  `mobileeval_ctl.py` 启动网页/发起评测）。先执行 `ls <skill目录>/scripts/` 确认路径；
  常见位置：`~/.agents/skills/promptfoo-expert-eval/scripts/`（OpenWork 用户级）、
  `~/.mobilework-uat/skills/promptfoo-expert-eval/scripts/` 或 `~/.mobilework/skills/promptfoo-expert-eval/scripts/`
  （MobileWork UAT/PROD 安装目录）、或项目 `.opencode/skills/promptfoo-expert-eval/scripts/`
- **评测数据库**：`<MobileEval 项目>/eval-data/mobileeval.db`
  （命令一律加 `--db-path <绝对路径>`；也可设环境变量 `MOBILEEVAL_DB` 或 `MOBILEEVAL_HOME` 指向项目根，免传）
- **被测工作区**：由对象记录决定（执行 `list-cases --object-id <id>` 确认对象存在后，
  从数据库 `objects` 表取 `workspace_dir`/`agent_name`）
- **评测中心网页**：`mobileeval_ctl.py start` 或 `open --page=...` 后访问输出的 `http://127.0.0.1:7891`
- **定位已安装技能**（manager 等独立技能）：优先读环境变量 `MOBILEWORK_SKILLS_DIR`，
  其次按 `~/.mobilework-uat/skills/<id>`、`~/.mobilework/skills/<id>`、`~/.agents/skills/<id>` 顺序探测；
  仅当技能目录可写时才考虑本包内相对路径，禁止依赖技能目录内嵌其他技能。

所有脚本统一用 `python -B <脚本> <子命令> --参数=值` 调用（**必须带 `-B`**：技能安装目录只读，
禁止生成 `__pycache__`；若宿主支持也可先 `export PYTHONDONTWRITEBYTECODE=1` 再执行），值以 `=` 拼接（防 argparse 误解析）。
**新机器零配置自举**：本 skill 自带 MobileEval 项目模板（`<skill>/mobileeval/`，含后端与网页静态文件）。
首次在任何机器上调用时，脚本会自动把模板复制到用户目录（`~/MobileEval`）并初始化数据库，
无需手动准备项目；也可用环境变量 `MOBILEEVAL_HOME` 指向已有项目（例如 Windows：`set MOBILEEVAL_HOME=<项目根>`）。

## 环境准备（首次使用/新机器，第一件事是检查基础环境）

**任何操作之前**，先检测基础运行环境是否具备；缺失时**先征求用户同意再安装**，不得擅自静默安装：

```bash
python --version    # 需要 3.10+；Windows 可能是 py -3 --version
node --version      # 需要 18+（npm 随 Node 一起装）
npm --version
```

- **Python 缺失或版本 < 3.10**：向用户说明"评测工具需要 Python 3.10+，当前未检测到（或版本过低），
  需要下载安装"，并按「交互提问协议」给出选项：
  ```
  请选择：
  [1] 同意安装（macOS: brew install python@3.12；Windows: winget install Python.Python.3.12；Linux: sudo apt install python3）
  [2] 不安装，停止评测
  ```
  同时用 `composer.set_text` 预填 `1`。**用户同意后**协助安装（按系统推荐），装完重新检测确认版本。
- **Node.js / npm 缺失或版本 < 18**：同样先说明再征得同意（选项同上，安装命令：
  macOS `brew install node@22`；Windows `winget install OpenJS.NodeJS.LTS`；Linux `sudo apt install nodejs npm`），
  装完重新检测。
- **用户不同意安装**：如实告知"缺少 Python/Node 无法运行评测工具"，停止并说明后续需要时可再装，不强行继续。

基础环境就绪后，其余依赖（flask / promptfoo / opencode CLI）由 `mobileeval_ctl.py start`/`deps` **自动安装**，无需用户干预。
**评测模型（必配，唯一需要用户手动完成的事）**：执行 `mobileeval_ctl.py start` 后用
`expert_tools.py list-models --db-path=<db>` 检查；**若没有任何模型 → 自动执行
`mobileeval_ctl.py open --page=models` 打开「评测模型」配置页，提示用户添加模型（name/provider/model/base_url/api_key），
等待用户配置完成后再继续后续评测流程**（发起评测、生成 case 前都确认模型已就绪）。等待时按协议给出收尾选项：
```
请选择：
[1] 已配置完成，继续（agent 重新 list-models 校验）
[2] 稍后再说（流程暂停）
```

## 启动前置（每次调用本 skill 的第一件事，必须执行）

无论用户接下来要做什么（评测、导入专家、优化、查看报告、对比），**第一步永远是启动评测中心网页**：

```bash
python -B <scripts>/mobileeval_ctl.py start
```

拿到返回的 `url`（http://127.0.0.1:7891）后，**等待 3 秒，然后在客户端内置浏览器/预览面板打开该地址**——
这是**无条件自动动作，不等用户开口要求、不等“接下来是否需要人工操作”**（评测中心是本技能的主工作台，
触发即弹出）。MobileWork 客户端用 `openwork_inner_browser_open_url` 打开；OpenWork 桌面直接用内置浏览器
打开。打开失败时执行 `python -B <scripts>/mobileeval_ctl.py status` 确认后再重试一次。
页面打开后**立即**按下面「人工接管网页（…默认接管）」流程调用 `openwork_inner_browser_show_takeover`
显示「手动接管」按钮并提示用户点击（用户不需要操作时可保持接管按钮挂着，不影响后续命令行执行；
仅当用户明确说“只命令行跑、不要开网页”时才跳过打开）。

**启动评测中心的唯一方式就是上面的 `mobileeval_ctl.py start`——严禁手动前台运行
`python app.py` 或其他启动命令**。原因：后端是 Flask 常驻服务，手动前台运行会让命令通道
一直阻塞（无输出、看似"卡死/超时"），且 Windows 控制台 GBK 编码会把日志刷乱、误导判断。
`start` 已自动处理：前端构建产物缺失时自动打包源码（npm run build）、缺失 flask 自动安装
（scope=web，**启动阶段不装 promptfoo/opencode**，它们留给评测前自动补装）、
7891 被占用则清理后启动、后端日志落盘 `eval-data/backend.log`（**启动失败/异常时先读该日志尾部
定位真实原因，不要盲目反复重试或改用手动命令**）。`start` 就绪等待最长 60s，超时会打印后端日志尾部。
**服务为常驻模式**：不随命令/OpenWork 会话退出（重复 `start` 返回 already_running 直接复用），
不需要时不重复执行 start/status；停止用 `python -B <scripts>/mobileeval_ctl.py stop`。
**不要执行 brv query 等项目上下文查询**——本 skill 的脚本自带全部上下文（数据库/工作区），
外部查询只会拖慢流程（可能超时 120 秒）。

### 人工接管网页（客户端打开评测中心页面后的通用约定，默认接管）

客户端右侧面板/内置浏览器里打开的网页**默认是只读预览（页面实时录屏视频），鼠标点击、
键盘输入无法直达页面**。本文件所有“打开评测中心页/报告/配置页供用户查看或操作”的步骤，
凡涉及**人工操作**（审核/勾选 case、查看并搜索会话证据、写人工评审、发起/重跑评测、
填模型配置、版本切换等），一律按下面的“默认手动接管”流程执行，**不要只丢一个只读预览给用户**：

1. **MobileWork 客户端（有灵犀浏览器工具）**：用客户端工具 `openwork_inner_browser_open_url`
   打开返回的 URL（右侧面板即显示页面）；**页面打开后立即调用
   `openwork_inner_browser_show_takeover`** 显示「手动接管」按钮（该工具只显示按钮、不会自动接管），
   并提示用户“点击浏览器面板上的『手动接管』按钮即可像普通浏览器一样直接操作”。
   接管生效后页面变成**真实可交互页面**（不再是视频预览）；接管期间**暂停本任务一切浏览器自动化**
   （不调用 browser_* 系列命令、不轮询/截图页面），等用户说“结束接管”后，
   先 `openwork_inner_browser_snapshot`（或按环境用 cmit-browser snapshot）重新同步页面状态，再继续原任务。
2. **接管工具不可用/调用失败，或环境无灵犀浏览器（如 OpenWork 桌面）**：直接把 URL 交给用户，
   请其在系统浏览器（Chrome/Edge）打开 `http://127.0.0.1:7891`（后端在本机，外部浏览器访问
   完全可交互，数据实时一致）；不要反复重试接管工具。
3. 仅当页面**纯展示、用户无需点击**（如展示一份报告让用户看结论）时，可保持在预览模式直接讲解，
   不必每次都走接管。

### 高效执行铁律（违者会显著拖慢流程，必须遵守）

1. **只用本 skill 的命令**：禁止加载/调用其他 skill（如 byterover）、禁止查询扩展能力、
   禁止对任何命令执行 `--help`/`context`——命令格式本 SKILL.md 已给全。
2. **一次调用拿全貌**：确认对象后，第一步执行 `expert_tools.py overview --object-id=<id>`
   （对象/成员/case/最近评测/下一步建议一次返回）；**禁止**逐个 `list-cases`/`list-tasks`/`status`/`context` 反复查询。
3. **start 复用后直接用**：`start` 返回 `already_running` 说明服务在跑，**直接**用返回的 URL 打开页面，
   **禁止**再执行 `status` 确认。
4. **打开页面失败**：一次打开失败（ERR_CONNECTION_REFUSED）时，先 `status` 确认再重试一次；不要反复重试。
5. **及时汇报**：每完成一个大步骤（启动/确认对象/确认 case/评测完成）立即向用户汇报一句话进度，
   不要让用户长时间等待无反馈。

### 交互提问协议（所有需要用户确认/选择的地方必须遵守）

OpenWork 无"动态可点击按钮"原生能力，但有 `composer.set_text`（把预填文本放入输入框）。
因此**所有向用户提问/确认的地方，一律用「编号选项」+ `composer.set_text` 预填**实现点选式体验：

1. **选项格式**（消息中渲染）：
   ```
   请选择：
   [1] 选项描述（对应操作说明）
   [2] 选项描述
   [3] 选项描述
   ```
2. **预填输入框**：提问的同时调用 `composer.set_text`，把"最可能的默认选择"对应的回复文本
   预填进输入框（用户可见、可编辑、回车即发送）；若无法调用该能力，则在消息末尾附上
   "回复数字即可，如：1"。
3. **选项必须可执行**：每个选项要么是 `[数字]` 直接触发一条命令，要么是明确的下一步动作
   （如"调整参数→重跑 dry-run"）；禁止开放式提问（如"你想怎么做？"）。
4. **脚本 options 字段**：`overview` / `generate-case-plan` / `run-eval --dry-run` / `start`
   返回 JSON 中带 `options` 数组（`[{"key": "1", "label": "…", "action": "命令或说明"}]`），
   AI 必须按该数组渲染选项，不得自造选项。
5. **默认选中**：`options` 中 `default: true` 的项即默认选择，`composer.set_text` 预填其 action。

> 例外：评测模型配置（需用户填表单）与网页端操作（评测中心页内按钮）不走本协议，但
> agent 等待时应给出"已配置完成/跳过"等收尾选项。

## 工具（AI 按需调用）

### 1. 评测中心（网页 + 后端，启动前置；依赖缺失自动安装）
```bash
python -B <scripts>/mobileeval_ctl.py start       # 启动/复用后端并输出 URL（调用本 skill 的第一件事）
python -B <scripts>/mobileeval_ctl.py status      # 检查是否已在运行
python -B <scripts>/mobileeval_ctl.py stop        # 停止常驻服务（结束 7891 上的进程）
python -B <scripts>/mobileeval_ctl.py deps        # 可选：仅检测并自动安装 flask / promptfoo / opencode
```
固定使用 **http://127.0.0.1:7891**；start 时若 7891 被占用（且不是 MobileEval 自身），
会自动结束占用进程后重新启动。返回 `{"status":"started|already_running","url":"http://127.0.0.1:7891"}`。
拿到 url 后，**在 OpenWork 内置浏览器中打开该地址**，让用户查看/审核数据。
**服务常驻运行**（不随命令/会话退出），重复 start 返回 already_running 直接复用；
只有需要释放端口时才执行 stop。

### 2. 查看对象现状（先确定 object_id）
```bash
python -B <scripts>/expert_tools.py list-cases --object-id=9 --db-path=<db>
```
`list-cases` 返回每条 case 的 `id`（数据库 id）、`case_id`、`title`、`status`，供审核决策。

### 3. 分析专家团（业务指标写库，不再创建任务）
```bash
python -B <scripts>/expert_tools.py analyze-expert --workspace=<被测工作区> --agent=software-team-lead \
  --name="评测方向名" --object-id=9 --db-path=<db>
```
返回 `{"object_id": <id>, "config": {...}}`。业务指标已写入对象。

### 4. 生成评测 case（两阶段：先概要 → 用户确认 → 再生成完整 case）
```bash
# 阶段 4a：生成 case 概要（不写库，供用户确认）
python -B <scripts>/expert_tools.py generate-case-plan --workspace=<被测工作区> --agent=software-team-lead \
  --name="评测方向名" --description="评测方向描述" --count=6
# 返回 {"status":"awaiting_confirmation","plan":[{"seq","title","type","target","verify"},...], "options":[...]}
# → 把 plan 展示给用户确认（标题/类型/目标/验证点），按 options 渲染选项并预填默认项，用户确认后才进行下一步

# 阶段 4b：用户确认后，按概要生成完整 case 并写库（--plan 传上一步返回的 plan JSON 字符串）
python -B <scripts>/expert_tools.py generate-cases --workspace=<被测工作区> --agent=software-team-lead \
  --count=6 --plan='[{"seq":1,"title":"...","type":"structured","target":"...","verify":"..."},...]' \
  --object-id=9 --mode=replace --db-path=<db>
```
`mode=replace`（默认）覆盖未审核用例；`mode=append` 追加新一批。返回 `{"generated": n, ...}`。

### 4c. 生成完毕 → 打开展示 case 的网页
```bash
python -B <scripts>/mobileeval_ctl.py open --page=object --object-id=9
```
在 OpenWork 内置浏览器打开评测中心页，展示刚生成的 case 列表（含每条 title/type/status，可逐条查看与审核）。

### 4d. 导入并转换用户提供的现成用例（重要：转换由 AI 完成）

用户在评测中心页「评测用例」Tab 点「导入用例」→ 复制提示词模板 → 在对话框发送（填入自己用例文件的路径）。
模板内容大致为：
> 请读取本机文件 <文件路径> 中的评测用例，转换为评测中心标准用例格式，导入到当前专家/专家团的评测用例中（object_id=...）。转换结果先展示给我确认，确认后再写入。

这些用例可能是任意格式（JSON/YAML/Markdown/Excel 等），**不一定符合评测中心标准结构**。
转换由 **AI（本会话）** 完成，不调用额外 LLM：

1. **拿到文件内容**：用户消息中给出文件路径 → 用 `read` 读取；若用户直接在对话框粘贴内容，直接用粘贴文本。
2. **AI 转换**：识别原格式（JSON/YAML/Markdown/表格等），把每条用例转换为标准结构：
   ```json
   {"case_id": "imp-1", "title": "用例标题", "type": "structured|hybrid|open_ended",
    "dimension": "", "prompt": "发给被测专家的完整任务指令（可含 {output_dir} 占位）",
    "output_dir": "eval-runs/{run_id}/imp-1",
    "assertions": [{"type": "contains|regex|javascript|tool-call|delegation|kb-hit|llm-rubric", "value": "..."}]}
   ```
   原内容已有标题/步骤/期望等 → 映射到 prompt（合成可执行指令）；无法确定的字段用默认（type=hybrid、assertions=[]）。
   转换结果**先展示给用户确认**，确认后再落库。
3. **落库**（转换好的 case 数组直接写入）：
   ```bash
   python -B <scripts>/expert_tools.py import-cases --object-id=9 --cases='[{"title":"...","prompt":"...",...}]' --mode=append --db-path=<db>
   ```
   落库为 `pending`，走「批量审核 case」流程（见下节）。

> 注意：`import-cases` 只负责校验与落库，**不做格式转换**；转换必须是 AI 在会话中完成，
> 因为输入格式千变万化，需要理解语义才能正确映射。
> 前端「导入用例」只是给出提示词模板，**转换完全由 AI 在收到用户消息后执行**。

### 5. 批量审核 case
```bash
python -B <scripts>/expert_tools.py review-cases --object-id=9 --action=approve --scope=all --db-path=<db>
python -B <scripts>/expert_tools.py review-cases --object-id=9 --action=approve --scope=selected --case-ids=12,13 --db-path=<db>
```
`action=approve|reject`；`scope=all|selected`（selected 需 `--case-ids`，逗号分隔数据库 id）。

### 6. 发起真实评测（创建 run + 执行 + 落库）

**发起前必须先 dry-run 给用户确认参数，确认后才正式执行：**
```bash
# ① 预览参数（不创建 run、不执行）→ 逐项展示给用户确认
python -B <scripts>/mobileeval_ctl.py run-eval --object-id=9 --dry-run --db-path=<db>
# ② 用户确认后，去掉 --dry-run 正式发起（参数与 ① 一致）
python -B <scripts>/mobileeval_ctl.py run-eval --object-id=9 --model-id=1 --version=v1 \
  --agent-on=1 --repeat=1 --concurrency=4 [--experiment-id=2 --variant=deepseek-chat] --db-path=<db>
```
返回 `{"run_id": n, "status": {...stats}, "url": "http://127.0.0.1:7891/runs/<id>"}`。
参数与 web「发起评测」弹窗一致：`--model-id`（全局模型）/`--version`（专家版本）/`--agent-on`（是否专家团）/
`--repeat`（次数）/`--concurrency`（并发）/`--experiment-id`+`--variant`（对照实验，可选）。
评测较耗时（单 case 最长 5 分钟）；完成后用 `import-summary --run-id=<id>` 可补录（一般不需要）。

### 7. 生成优化建议（写库）
```bash
python -B <scripts>/expert_tools.py suggest --summary=<run>/summary.json --meta=<run>/meta.json \
  --run-id=<id> --db-path=<db>
```
meta.json 可由 AI 构造：`{"object": "对象名", "status": "passed|failed", "score": 0.0, "pass_fail_error": "a/b/c"}`。

## 标准评测工作流（用户说"评测 XX 专家团"时按此执行）

> 模型层级：对象（专家/专家团）→ 用例（case，审核通过后参与评测）→ 运行（run，一次真实评测 = 一条实验记录）。
> **没有任务层**。每次运行记录实验变量：专家版本 / 模型 / 是否启用专家团 / 重复次数，可任意选择多次运行对比。

0. **启动前置（必须）**：先执行 `mobileeval_ctl.py start` 并在 OpenWork 内置浏览器打开
   `http://127.0.0.1:7891`，让用户看到评测中心页面。随后执行 `expert_tools.py list-models --db-path=<db>`
   **检查评测模型**：没有任何模型 → **自动执行 `open --page=models` 打开「评测模型」配置页**，
   提示用户添加模型并按协议给出收尾选项（[1] 已配置完成 [2] 稍后再说），等待配置完成
   （未配模型前不进入后续步骤）。
1. **确认对象（先看主库，不在就导入）**：
   - 执行 `expert_tools.py list-objects --db-path=<db>`，返回 `db`（**唯一权威库路径**，即 web 用的库）和对象列表。
   - 用户要评测的专家/专家团**在列表里** → 记下 object_id，执行 `overview --object-id=<id>` 拿全貌。
   - **不在列表里** → **唯一动作是 `import-expert` 导入**（从 OpenWork 全局或 workspace 复制到隔离工作区并建对象）。
     若存在多个候选来源，按协议给出选项（[1] 全局 ~/.config/opencode/agents [2] 指定 workspace 目录 [3] 取消）；
     单一来源则直接导入。导入后再 `list-objects` 确认、再 `overview`。
   - **严禁**：自行搜索/猜测数据库文件、使用非 `list-objects` 返回的 `--db-path`、直接改库。
     所有命令的 `--db-path` 必须等于 `list-objects` 返回的 `db`（web 与脚本必须同一个库）。
2. **生成 case（两阶段，仅当对象无 case 时）**：`analyze-expert` 分析专家团（业务指标自动落到对象）；然后
   `generate-case-plan --count=6` 生成 case 概要，**按 options 渲染并展示给用户确认**
   （标题/类型/目标/验证点）：[1] 确认生成 [2] 调整数量/内容 [3] 重新生成概要；
   用户确认后 `generate-cases --count=6 --plan=<概要JSON>` 按概要生成完整 case 写库。
3. **打开展示页面**：`open --page=object --object-id=<id>`，让用户在评测中心页看到刚生成的 case 列表。
4. **审核**：按「交互提问协议」询问用户（`options` 来自 `overview` 的 `next_step`）：
   ```
   请选择：
   [1] 全部通过（review-cases --scope=all）
   [2] 只通过部分（agent list-cases 展示 id → 用户给 id → --scope=selected --case-ids=...）
   [3] 驳回全部 / 重新生成 case
   ```
5. **发起评测（必须先确认参数）**：发起前**必须**执行
   `mobileeval_ctl.py run-eval --object-id=<id> --dry-run --db-path=<db>`
   拿到本次评测的完整参数（评测模型/专家版本/是否启用专家团/重复次数/并发/对照实验/variant/将跑的 case 数），
   **按 `options` 渲染选项并逐项展示给用户确认**（参数与 web「发起评测」弹窗一致）：
   ```
   请选择：
   [1] 确认发起（agent 去掉 --dry-run 正式执行，参数与预览一致）
   [2] 修改参数（用户指定 → 重跑 dry-run）
   [3] 取消
   ```
   同时用 `composer.set_text` 预填 `1`。用户确认后才正式执行。未确认前**不得**发起评测。
   无审核通过的 case 时评测会直接失败（提示先生成并审核用例）。
6. **生成建议**：评测完成后 `suggest` 生成优化建议。
7. **汇报 + 打开网页**：汇总结果（通过/失败/分数），并在 OpenWork 内置浏览器打开
   `http://127.0.0.1:7891/runs/<id>` 让用户查看报告。

### 全局评测模型（发起评测时选择，模型含 API Key / Base URL）

模型在**全局「评测模型」页**管理（`open --page=models` 或 http://127.0.0.1:7891/models），
不在专家团里配：每个模型记录 `name / provider / model / base_url / api_key`，
评测时把 provider/模型/base URL/API Key **传给 promptfoo** 调用。
```bash
# 列出全局模型
python -B <scripts>/expert_tools.py list-models --db-path=<db>
# 新增模型（可设默认；api_key 存本地库，列表仅返回掩码）
python -B <scripts>/expert_tools.py add-model --name="DeepSeek 官方" --provider=deepseek \
  --model=deepseek-v4-flash --base-url=https://api.deepseek.com/v1 --api-key=sk-xxx \
  --is-default=1 --db-path=<db>
# 发起评测时指定模型（推荐；也可直接 --provider/--model + 环境变量 key）
python -B <scripts>/mobileeval_ctl.py run-eval --object-id=9 --model-id=1 --db-path=<db>
```
> 说明：`run-eval` 的 `--model-id` 从 models 表解析 provider/model/base_url/api_key；
> 未指定时回退 `--provider/--model` + 环境变量 `DEEPSEEK_API_KEY`（兼容旧用法）。

### 对照实验（多维度对比：版本/模型/是否启用专家团）

每次运行（run）自带实验变量：`version`（专家版本）、`model`（基础模型）、`agent_on`（1=专家团，0=无专家 baseline）、
`repeat`（次数）。量化某变量影响：固定其余变量、只改目标变量，跑 2 组以上运行，然后：
- **Web**：评测中心 → 历史对比（勾选 ≥2 次运行）→ 逐 case 断言矩阵；或「对照实验」页按变量分组对比
- **CLI**：`expert_tools.py compare-runs --ids=1,2,3 --db-path=<db>`（或 `open --page=compare`）

## 专家导入（从 OpenWork 全局或 workspace 指定专家/专家团）

```bash
# 从 OpenWork 全局专家（~/.config/opencode/agents）导入（指定团长名=导入整个团队；指定团员名=单专家）
python -B <scripts>/expert_tools.py import-expert --name=software-team-lead --source-type=global --db-path=<db>
# 从用户 workspace 导入（--source-path 指向专家包目录）
python -B <scripts>/expert_tools.py import-expert --name=software-team-lead --source-type=workspace --source-path=<目录> --db-path=<db>
```
导入会把专家（团）**复制到评测工具专属隔离工作区**（`<项目>/MobileEval/eval-data/workspaces/<名>/`，
含 agents/avatars/权限配置），评测只在该隔离区进行，不影响来源。

## 迭代优化 + 版本管理 + 回归对比（用户确认后执行）

```bash
python -B <scripts>/expert_tools.py versions-list --object-id=<id> --db-path=<db>   # 版本历史
python -B <scripts>/expert_tools.py optimize-expert --object-id=<id> --run-id=<run_id> [--note="说明"] [--only-agents=a,b] --db-path=<db>
```
按「交互提问协议」确认后再执行 `optimize-expert`：
```
请选择：
[1] 执行优化（agent 运行 optimize-expert，自动快照旧版 + AI 重写 + 写回全局）
[2] 只生成建议，暂不优化
[3] 跳过
```
同时用 `composer.set_text` 预填 `1`。
`optimize-expert` 流程：读取该 run 的优化建议 → **自动快照当前版本**（保存旧版到
`workspaces/<名>/versions/v<N>/`，滚动保留最近 10 版）→ AI 逐个 agent 基于建议重写定义
（身份/角色不变，优化工作流/输出规范/验收标准/权限等）→ **直接写回 OpenWork 全局版本
（~/.config/opencode/agents/，当前使用版本立即生效，无需重新安装）+ 隔离工作区副本** → 记录优化关系。
优化后发起回归评测：`mobileeval_ctl.py run-eval --object-id=<id> --db-path=<db>`，
再到对比页选择两次评测查看差异。

## 分阶段网页（同一 web 应用，用页面 CLI 跳转）

每个页面一个 CLI：调用 `mobileeval_ctl.py open --page=<页面> ...`，自动启动后端并返回对应路由的
URL，在 **OpenWork 内置浏览器打开**即可（所有页面都由同一个 web 应用提供）：

| 阶段/页面 | CLI | 路由 |
|---|---|---|
| 全部专家/专家团 | `open --page=objects` | `/objects` |
| 评测中心（用例/评测） | `open --page=object --object-id=<id>` | `/objects/<id>` |
| 评测报告 | `open --page=report --run-id=<rid>` | `/runs/<rid>` |
| 版本历史 | `open --page=versions --object-id=<id>` | `/objects/<id>/versions` |
| 迭代优化 | `open --page=optimize --object-id=<id>` | `/objects/<id>/optimize` |
| 对照实验（多版本/模型/是否启用专家团） | `open --page=experiments --object-id=<id>` | `/objects/<id>/experiments` |
| 优化对比报告 | `open --page=compare --object-id=<id> --base=<run1> [--opt=<run2>]` | `/compare/<id>?base=&opt=` |

示例：评测完成后打开报告 → `python -B <scripts>/mobileeval_ctl.py open --page=report --run-id=13`，
把返回的 `url` 在 OpenWork 内置浏览器打开。

## 模块级评测能力（case 断言新增类型）

case 的 assertions 现支持两类断言，报告按维度聚合展示：

**模块级断言（观测过程，非最终输出）** —— 由评测后过程探针（读取 case 独立 opencode.db）评估：
- `tool-call`：断言某工具被调用（value=工具名，或 `{"tool":"名","status":"completed"}`）
- `delegation`：断言团长委派给某团员（value=团员 agent 名）
- `kb-hit`：断言检索命中某关键词（value=关键词）

**业务视角断言（用户可感知体验，LLM 裁判自动打分）**：
- `llm-rubric`：`{"type":"llm-rubric","metric":"可用性|相关性|完整性|可交付","value":"评分标准"}`

报告页新增：模块级效能（工具调用准确率/多Agent协同/知识匹配/输出质量）、稳定性（repeat 多次成功率+波动图）、
技术+业务双视角指标。**AI+人工闭环**：开放式/兜底重判的 case 自动标"待人工判定"，报告页逐 case 人工纠错，
`generate-suggestions` 会读取逐 case 纠错反哺优化建议。**原始过程数据**：报告页"导出原始过程数据"下载完整
eval.log/results.json/每 case 输出与过程 trace 的 zip。

## 运行环境核对（run-eval 前必须）

1. `promptfoo --version`、`opencode --version` 可用；`@opencode-ai/sdk` 已装。
2. **评测模型已配置**：`list-models` 至少有一条（含 api_key）；没有则先 `open --page=models` 让用户配置。
3. 被测工作区存在 `.opencode/opencode.jsonc` 且声明被测 agent（评测前会自动兜底写入默认权限配置）。
4. 模型 API key：`--api-key` 或环境变量（deepseek 需显式传 `DEEPSEEK_API_KEY`）。

## 边界与安全

- 只操作系统上下文给定的对象/run id；不猜测、不遍历其他 id。
- 工作区路径一律以对象记录为准，不得自行拼接/改写路径。
- 评测是真实执行（写文件、跑命令），产物在隔离工作区；bash 已拒绝破坏性命令（rm -rf/del /s 等）。
- `optimize-expert` 会**直接修改 OpenWork 全局专家文件**（用户确认后执行；修改前自动快照旧版本）。
