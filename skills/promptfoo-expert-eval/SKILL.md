---
name: promptfoo-expert-eval
description: >-
  MobileEval 专家（团）评测能力。当用户要求：评测/评估某个专家或专家团、生成评测用例或
  评测 case、批量审核 case、发起真实评测（promptfoo + opencode）、查看评测结果与优化建议、
  或打开 MobileEval 评测中心网页时触发。能力覆盖：分析专家团 → 生成 case →
  审核 → 真实评测 → 优化建议，并可在 OpenWork 内置浏览器打开评测中心（网页 + 后端）。
  本插件还捆绑 mobilework-expert-manager 技能（skills/mobilework-expert-manager/）：
  当用户要求创建/转换/编辑专家或专家团（而非评测）时，加载并执行该技能生成 OpenCode
  格式专家包（含 .opencode/agents/*.md），再回到本评测流程 import-expert → 评测。
compatibility: Requires Python 3.10+ 与 Node.js 18+（npm）——两者缺失时先征求用户同意再协助安装（见「环境准备」）。flask / promptfoo / opencode CLI 缺失时自动安装（mobileeval_ctl deps）；@opencode-ai/sdk 由 promptfoo 内置；PyYAML 可选（缺失时 case 用 .json 格式）。
---

# MobileEval 专家（团）评测

通过真实 OpenCode 会话（promptfoo `opencode:sdk` provider）驱动被测专家（团）执行评测，
产物与结果统一写入 SQLite（评测数据库），网页端展示数据、case 审核与报告。

```text
analyze-expert 分析 → generate-cases 生成 case → review-cases 审核
    → run-eval 真实评测（promptfoo + opencode）→ suggest 优化建议 → 网页查看
```

默认用中文沟通；命令、路径与代码保持原文。

## 技能协作：mobilework-expert-manager（何时调用）

本插件捆绑了 `skills/mobilework-expert-manager/` 技能（专家包管理器）。它与评测流程互补，
**触发时机按用户意图区分**：

| 用户要求 | 执行者 | 说明 |
|---|---|---|
| 评测/评估/生成 case/审核/发起评测/看报告 | **本技能**（promptfoo-expert-eval） | 走下方标准评测工作流 |
| **创建**新专家/专家团（按自然语言） | **mobilework-expert-manager** | 加载其 SKILL.md，先确认业务方案再生成 OpenCode 专家包 |
| **转换**非 OpenCode 格式为 OpenCode 格式 | **mobilework-expert-manager** | 按迁移/诊断流程转换 |
| **编辑**/修改已有专家或专家团 | **mobilework-expert-manager** | 受控修改，遵守其 controlled-modification 协议 |
| 创建/转换/编辑**完成后**要评测 | **先 manager 后本技能** | 用生成/修改后的包走 import-expert → 评测 |

**协作铁律：**
1. 用户意图是"创建/转换/编辑"→ **必须**加载 `skills/mobilework-expert-manager/SKILL.md`
   并按其协议执行（其脚本在 `skills/mobilework-expert-manager/scripts/`），不得用本评测流程的
   `import-expert`/`analyze-expert` 代替（那些是评测侧能力，不生成专家包）。
2. manager 生成/修改的专家包是标准 OpenCode 格式（`expert.json` manifest +
   `.opencode/agents/*.md` + `opencode.json`），与本评测的导入格式天然兼容。
3. 评测对象缺失或格式不符时，提示用户先用 manager 技能创建/转换，再回到本流程。
4. 两个技能共享同一工作区时，路径以各自对象记录为准，不互相改写对方产物。

## 关键路径（先确认存在）

- **插件脚本目录**：本 skill 目录下的 `scripts/`（`expert_tools.py` AI 生成类、`run_eval.py` 评测执行、
  `mobileeval_ctl.py` 启动网页/发起评测）。先执行 `ls <skill目录>/scripts/` 确认路径；
  常见位置：`~/.agents/skills/promptfoo-expert-eval/scripts/`（OpenWork 用户级）或项目 `.opencode/skills/promptfoo-expert-eval/scripts/`
- **评测数据库**：`<MobileEval 项目>/eval-data/mobileeval.db`
  （命令一律加 `--db-path <绝对路径>`；也可设环境变量 `MOBILEEVAL_DB` 或 `MOBILEEVAL_HOME` 指向项目根，免传）
- **被测工作区**：由对象记录决定（执行 `list-cases --object-id <id>` 确认对象存在后，
  从数据库 `objects` 表取 `workspace_dir`/`agent_name`）
- **评测中心网页**：`mobileeval_ctl.py start` 或 `open --page=...` 后访问输出的 `http://127.0.0.1:7891`

所有脚本统一用 `python <脚本> <子命令> --参数=值` 调用，值以 `=` 拼接（防 argparse 误解析）。
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
  需要下载安装，是否同意安装？"。**用户同意后**协助安装（按系统推荐）：
  - Windows：`winget install Python.Python.3.12`（或引导用户从 python.org 下载安装包，勾选 Add to PATH）
  - macOS：`brew install python@3.12`
  - Linux：`sudo apt install python3 python3-pip`（或系统对应包管理器）
  装完重新检测确认版本。
- **Node.js / npm 缺失或版本 < 18**：同样先说明再征得同意，然后协助安装：
  - Windows：`winget install OpenJS.NodeJS.LTS`（或引导从 nodejs.org 下载 LTS 安装包）
  - macOS：`brew install node@22`
  - Linux：`sudo apt install nodejs npm`（或 nvm）
  装完重新检测。
- **用户不同意安装**：如实告知"缺少 Python/Node 无法运行评测工具"，停止并说明后续需要时可再装，不强行继续。

基础环境就绪后，其余依赖（flask / promptfoo / opencode CLI）由 `mobileeval_ctl.py start`/`deps` **自动安装**，无需用户干预。
**评测模型（必配，唯一需要用户手动完成的事）**：执行 `mobileeval_ctl.py start` 后用
`expert_tools.py list-models --db-path=<db>` 检查；**若没有任何模型 → 自动执行
`mobileeval_ctl.py open --page=models` 打开「评测模型」配置页，提示用户添加模型（name/provider/model/base_url/api_key），
等待用户配置完成后再继续后续评测流程**（发起评测、生成 case 前都确认模型已就绪）。

## 启动前置（每次调用本 skill 的第一件事，必须执行）

无论用户接下来要做什么（评测、导入专家、优化、查看报告、对比），**第一步永远是启动评测中心网页**：

```bash
python <scripts>/mobileeval_ctl.py start
```

拿到返回的 `url`（http://127.0.0.1:7891）后，**等待 3 秒再在 OpenWork 内置浏览器打开该地址**
（避免服务刚起、首次连接被拒 ERR_CONNECTION_REFUSED）。如果打开失败，执行
`python <scripts>/mobileeval_ctl.py status` 确认后再重试。
`start` 已自动处理：前端构建产物缺失时自动打包源码（npm run build）、依赖缺失自动安装、
7891 被占用则清理后启动。**服务为常驻模式**：不随命令/OpenWork 会话退出（重复 `start` 返回
already_running 直接复用），不需要时不重复执行 start/status；停止用 `python <scripts>/mobileeval_ctl.py stop`。
**不要执行 brv query 等项目上下文查询**——本 skill 的脚本自带全部上下文（数据库/工作区），
外部查询只会拖慢流程（可能超时 120 秒）。

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

## 工具（AI 按需调用）

### 1. 评测中心（网页 + 后端，启动前置；依赖缺失自动安装）
```bash
python <scripts>/mobileeval_ctl.py start       # 启动/复用后端并输出 URL（调用本 skill 的第一件事）
python <scripts>/mobileeval_ctl.py status      # 检查是否已在运行
python <scripts>/mobileeval_ctl.py stop        # 停止常驻服务（结束 7891 上的进程）
python <scripts>/mobileeval_ctl.py deps        # 可选：仅检测并自动安装 flask / promptfoo / opencode
```
固定使用 **http://127.0.0.1:7891**；start 时若 7891 被占用（且不是 MobileEval 自身），
会自动结束占用进程后重新启动。返回 `{"status":"started|already_running","url":"http://127.0.0.1:7891"}`。
拿到 url 后，**在 OpenWork 内置浏览器中打开该地址**，让用户查看/审核数据。
**服务常驻运行**（不随命令/会话退出），重复 start 返回 already_running 直接复用；
只有需要释放端口时才执行 stop。

### 2. 查看对象现状（先确定 object_id）
```bash
python <scripts>/expert_tools.py list-cases --object-id=9 --db-path=<db>
```
`list-cases` 返回每条 case 的 `id`（数据库 id）、`case_id`、`title`、`status`，供审核决策。

### 3. 分析专家团（业务指标写库，不再创建任务）
```bash
python <scripts>/expert_tools.py analyze-expert --workspace=<被测工作区> --agent=software-team-lead \
  --name="评测方向名" --object-id=9 --db-path=<db>
```
返回 `{"object_id": <id>, "config": {...}}`。业务指标已写入对象。

### 4. 生成评测 case（两阶段：先概要 → 用户确认 → 再生成完整 case）
```bash
# 阶段 4a：生成 case 概要（不写库，供用户确认）
python <scripts>/expert_tools.py generate-case-plan --workspace=<被测工作区> --agent=software-team-lead \
  --name="评测方向名" --description="评测方向描述" --count=6
# 返回 {"status":"awaiting_confirmation","plan":[{"seq","title","type","target","verify"},...]}
# → 把 plan 展示给用户确认（标题/类型/目标/验证点），用户确认后才进行下一步

# 阶段 4b：用户确认后，按概要生成完整 case 并写库（--plan 传上一步返回的 plan JSON 字符串）
python <scripts>/expert_tools.py generate-cases --workspace=<被测工作区> --agent=software-team-lead \
  --count=6 --plan='[{"seq":1,"title":"...","type":"structured","target":"...","verify":"..."},...]' \
  --object-id=9 --mode=replace --db-path=<db>
```
`mode=replace`（默认）覆盖未审核用例；`mode=append` 追加新一批。返回 `{"generated": n, ...}`。

### 4c. 生成完毕 → 打开展示 case 的网页
```bash
python <scripts>/mobileeval_ctl.py open --page=object --object-id=9
```
在 OpenWork 内置浏览器打开评测中心页，展示刚生成的 case 列表（含每条 title/type/status，可逐条查看与审核）。

### 5. 批量审核 case
```bash
python <scripts>/expert_tools.py review-cases --object-id=9 --action=approve --scope=all --db-path=<db>
python <scripts>/expert_tools.py review-cases --object-id=9 --action=approve --scope=selected --case-ids=12,13 --db-path=<db>
```
`action=approve|reject`；`scope=all|selected`（selected 需 `--case-ids`，逗号分隔数据库 id）。

### 6. 发起真实评测（创建 run + 执行 + 落库）

**发起前必须先 dry-run 给用户确认参数，确认后才正式执行：**
```bash
# ① 预览参数（不创建 run、不执行）→ 逐项展示给用户确认
python <scripts>/mobileeval_ctl.py run-eval --object-id=9 --dry-run --db-path=<db>
# ② 用户确认后，去掉 --dry-run 正式发起（参数与 ① 一致）
python <scripts>/mobileeval_ctl.py run-eval --object-id=9 --model-id=1 --version=v1 \
  --agent-on=1 --repeat=1 --concurrency=4 [--experiment-id=2 --variant=deepseek-chat] --db-path=<db>
```
返回 `{"run_id": n, "status": {...stats}, "url": "http://127.0.0.1:7891/runs/<id>"}`。
参数与 web「发起评测」弹窗一致：`--model-id`（全局模型）/`--version`（专家版本）/`--agent-on`（是否专家团）/
`--repeat`（次数）/`--concurrency`（并发）/`--experiment-id`+`--variant`（对照实验，可选）。
评测较耗时（单 case 最长 5 分钟）；完成后用 `import-summary --run-id=<id>` 可补录（一般不需要）。

### 7. 生成优化建议（写库）
```bash
python <scripts>/expert_tools.py suggest --summary=<run>/summary.json --meta=<run>/meta.json \
  --run-id=<id> --db-path=<db>
```
meta.json 可由 AI 构造：`{"object": "对象名", "status": "passed|failed", "score": 0.0, "pass_fail_error": "a/b/c"}`。

## 标准评测工作流（用户说"评测 XX 专家团"时按此执行）

> 模型层级：对象（专家/专家团）→ 用例（case，审核通过后参与评测）→ 运行（run，一次真实评测 = 一条实验记录）。
> **没有任务层**。每次运行记录实验变量：专家版本 / 模型 / 是否启用专家团 / 重复次数，可任意选择多次运行对比。

0. **启动前置（必须）**：先执行 `mobileeval_ctl.py start` 并在 OpenWork 内置浏览器打开
   `http://127.0.0.1:7891`，让用户看到评测中心页面。随后执行 `expert_tools.py list-models --db-path=<db>`
   **检查评测模型**：没有任何模型 → **自动执行 `open --page=models` 打开「评测模型」配置页**，
   提示用户添加模型并等待配置完成（未配模型前不进入后续步骤）。
1. **确认对象（先看主库，不在就导入）**：
   - 执行 `expert_tools.py list-objects --db-path=<db>`，返回 `db`（**唯一权威库路径**，即 web 用的库）和对象列表。
   - 用户要评测的专家/专家团**在列表里** → 记下 object_id，执行 `overview --object-id=<id>` 拿全貌。
   - **不在列表里** → **唯一动作是 `import-expert` 导入**（从 OpenWork 全局或 workspace 复制到隔离工作区并建对象），
     导入后再 `list-objects` 确认、再 `overview`。
   - **严禁**：自行搜索/猜测数据库文件、使用非 `list-objects` 返回的 `--db-path`、直接改库。
     所有命令的 `--db-path` 必须等于 `list-objects` 返回的 `db`（web 与脚本必须同一个库）。
2. **生成 case（两阶段，仅当对象无 case 时）**：`analyze-expert` 分析专家团（业务指标自动落到对象）；然后
   `generate-case-plan --count=6` 生成 case 概要，**展示给用户确认**
   （标题/类型/目标/验证点）；用户确认后 `generate-cases --count=6 --plan=<概要JSON>` 按概要生成完整 case 写库。
3. **打开展示页面**：`open --page=object --object-id=<id>`，让用户在评测中心页看到刚生成的 case 列表。
4. **审核**：询问用户是否全部通过；通过则 `review-cases --scope=all`；用户想挑一部分则
   `list-cases` 拿 id 后 `--scope=selected`。
5. **发起评测（必须先确认参数）**：发起前**必须**执行
   `mobileeval_ctl.py run-eval --object-id=<id> --dry-run --db-path=<db>`
   拿到本次评测的完整参数（评测模型/专家版本/是否启用专家团/重复次数/并发/对照实验/variant/将跑的 case 数），
   **逐项展示给用户确认**（参数与 web「发起评测」弹窗一致）；用户确认后才去掉 `--dry-run` 正式执行。
   需要调整参数时，让用户指定后再 dry-run 一次。未确认前**不得**发起评测。
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
python <scripts>/expert_tools.py list-models --db-path=<db>
# 新增模型（可设默认；api_key 存本地库，列表仅返回掩码）
python <scripts>/expert_tools.py add-model --name="DeepSeek 官方" --provider=deepseek \
  --model=deepseek-v4-flash --base-url=https://api.deepseek.com/v1 --api-key=sk-xxx \
  --is-default=1 --db-path=<db>
# 发起评测时指定模型（推荐；也可直接 --provider/--model + 环境变量 key）
python <scripts>/mobileeval_ctl.py run-eval --object-id=9 --model-id=1 --db-path=<db>
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
python <scripts>/expert_tools.py import-expert --name=software-team-lead --source-type=global --db-path=<db>
# 从用户 workspace 导入（--source-path 指向专家包目录）
python <scripts>/expert_tools.py import-expert --name=software-team-lead --source-type=workspace --source-path=<目录> --db-path=<db>
```
导入会把专家（团）**复制到评测工具专属隔离工作区**（`<项目>/MobileEval/eval-data/workspaces/<名>/`，
含 agents/avatars/权限配置），评测只在该隔离区进行，不影响来源。

## 迭代优化 + 版本管理 + 回归对比（用户确认后执行）

```bash
python <scripts>/expert_tools.py versions-list --object-id=<id> --db-path=<db>   # 版本历史
python <scripts>/expert_tools.py optimize-expert --object-id=<id> --run-id=<run_id> [--note="说明"] [--only-agents=a,b] --db-path=<db>
```
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

示例：评测完成后打开报告 → `python <scripts>/mobileeval_ctl.py open --page=report --run-id=13`，
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
