# Promptfoo Expert Eval —— Claude Code 评测插件

通过 **Promptfoo `opencode:sdk` provider** 驱动 **真实 OpenCode** 专家（团）运行评测的
Claude Code Marketplace 插件。默认被测对象：`workspaces/test01/.opencode/agents/software-team-lead.md`
（软件开发专家团团长，含 4 个团员：产品经理 / 架构师 / 工程师 / QA）。

```text
case（内置库或自定义） → run_eval.py 生成 promptfooconfig.yaml → promptfoo eval
    → opencode:sdk 启动真实 OpenCode（agent=software-team-lead，加载被测工作区 .opencode 配置）
    → 断言（文本 + 产物文件验证） → results.json → summary.json + 控制台报告
```

## 目录结构

```text
mobilework-expert-eval-plugin/
├── .claude-plugin/
│   ├── plugin.json          # 插件 manifest（skills: ./skills/）
│   └── marketplace.json     # Marketplace 声明：本插件 + 公共 mobilework-expert-manager (github source)
├── skills/
│   └── promptfoo-expert-eval/
│       ├── SKILL.md                       # 会话入口（OpenWork / Claude Code）
│       ├── scripts/
│       │   └── run_eval.py                # 核心运行器：配置生成、执行、解析、汇总
│       ├── cases/
│       │   └── default-cases.yaml         # 内置 4 个 case（三类任务）
│       └── references/
│           ├── case-schema.md             # 自定义 case 规范
│           └── methodology.md             # 评测方法论、Promptfoo 集成记录、统计口径
└── README.md
```

## 运行环境

| 依赖 | 版本 | 说明 |
|---|---|---|
| promptfoo | 0.121.20 | 全局安装：`npm install -g promptfoo` |
| opencode CLI | 1.18.10 | `opencode:sdk` provider 必需 |
| @opencode-ai/sdk | 1.18.11 | 装在可被解析的 node_modules（本仓库样例：`workspaces/test01/package.json`） |
| Python | 3.10+ | 运行 run_eval.py；可选 PyYAML（本机 6.0.3） |
| 模型 API key | — | 运行评测必需（见下） |

> `opencode:sdk` provider 需要 `@opencode-ai/sdk` 包。promptfoo 为全局安装时，建议在
> 被测工作区 `npm install @opencode-ai/sdk`，并从该目录执行 eval（promptfoo 沿 cwd 解析 SDK）。

**模型 API key**：promptfoo 启动 opencode server 前会校验 provider 凭据（缺失时报
`Missing OPENCODE_API_KEY`，提示名有误导性，实际缺的是模型 provider 的 key）。实测
promptfoo 0.121.20 的 `getApiKey` 只映射 `anthropic`/`openai`/`google` 的环境变量，
**`deepseek` 不在映射表**，因此必须显式传 `--api-key`（或改设 OPENAI/ANTHROPIC key）：

```bash
# 推荐：--api-key + --provider/--model（promptfoo 会把 key 注入 opencode server）
python .../run_eval.py --working-dir workspaces/test01-eval --case todo-cli \
  --provider deepseek --model deepseek-v4-flash --api-key sk-...
```

评测链路真实调用 LLM 会产生费用，请在受控环境运行。

## 真实运行适配（实测排障结论）

1. **评测工作区投影**：被测工作区 `.opencode/opencode.jsonc` **与** `agents/*.md` frontmatter
   都定义了 agent 权限，opencode 以 md frontmatter 为准。默认 `bash: {"*": "ask"}` 在
   promptfoo 非交互运行中会**阻塞并被 abort**。评测需准备专用工作区（本仓库：`workspaces/test01-eval`，
   由 `test01` 复制后调整）：bash 改为白名单 allow（保留 `rm/Remove-Item/del/rd/rmdir` deny）、
   `external_directory`/`doom_loop`/`question` → deny。**原始工作区与专家包保持只读**。
2. **opencode 数据目录隔离**：promptfoo 每次 eval 启动独立 opencode server，若共享全局
   `~/.local/share/opencode/opencode.db` 会并发写导致 `SQLite FOREIGN KEY constraint failed`。
   run_eval.py 已为每个 run 设置独立 `XDG_DATA_HOME`（`<run-dir>/opencode-data/`）。
3. **SDK 默认 5 分钟超时**：opencode SDK `session.prompt` 默认 provider 超时 300000ms，
   超过会被 cancel（最终输出丢失）。case 设计应控制在 5 分钟窗口内（todo-cli 已按快速流程设计）；
   更长的任务需拆分为多个 case。
4. **权限优先级**：agent 自身权限优先于 promptfoo provider config 的 `permission` 参数
   （opencode 安全模型），因此权限适配必须在工作区 agent 定义上完成，而不是 provider 配置。

## 快速开始

```bash
# 1. 列出内置 case
python mobilework-expert-eval-plugin/skills/promptfoo-expert-eval/scripts/run_eval.py \
  --working-dir workspaces/test01 --list

# 2. 干跑（只生成配置，不消耗模型）
python mobilework-expert-eval-plugin/skills/promptfoo-expert-eval/scripts/run_eval.py \
  --working-dir workspaces/test01 --dry-run --all

# 3. 运行单个 case（真实 OpenCode 会话）
python mobilework-expert-eval-plugin/skills/promptfoo-expert-eval/scripts/run_eval.py \
  --working-dir workspaces/test01 --case todo-cli

# 4. 正式基准：全部 case × 5 次独立运行（任务书 6.3）
python mobilework-expert-eval-plugin/skills/promptfoo-expert-eval/scripts/run_eval.py \
  --working-dir workspaces/test01 --all --repeat 5
```

输出：`<working-dir>/.eval-results/<时间戳>/`
`summary.json`（统一证据）+ `runs/<case-id>-NN/`（promptfooconfig.yaml、results.json、output.txt、eval.log）。

## 安装（Claude Code Marketplace）

```bash
# 本地仓库验证（在 mobilework-expert-eval-plugin/ 目录内）
claude plugin list --json
claude plugin details promptfoo-expert-eval@mobilework-expert-eval-marketplace
```

推送到 GitHub 后：

```bash
/plugin marketplace add <your-github>/mobilework-expert-eval-plugin
/plugin install promptfoo-expert-eval@mobilework-expert-eval-marketplace
/plugin install mobilework-expert-manager@mobilework-expert-eval-marketplace   # 公共 manager（可选）
/reload-plugins
```

OpenWork 导入：`Settings → Extensions → Install from GitHub`，输入本仓库根 URL
（或按任务书三组形态改造后输入 `<repo>/tree/<release-tag>/plugins/<group>-expert-eval`），
Preview → Install → Refresh，再从新对话触发评测流程（见 SKILL.md）。

## Cases：内置 + 可生成

- **内置默认 case 库**（我帮写好了 4 个，覆盖任务书 3.3 三类任务）：
  - `todo-cli`：结构化 —— Todo CLI 应用，确定性断言产物与测试证据
  - `prd-priority`：混合式 —— 二手书交易小程序 PRD，P0/P1/P2 硬约束 + 文档产物
  - `feature-design`：开放式 —— 协作白板 MVP 后端设计，文档产物 + 接口要素，无硬性通过率
  - `bugfix-utils`：混合式 —— 预置 bug fixture，修复正确性断言 + QA 回归证据
- **插件可生成/追加 case**：在会话中用自然语言描述任务，按 `references/case-schema.md`
  整理为 YAML/JSON，用 `--case-file` 加载；自定义 case 与内置库按 id 去重，不改内置文件。
  正式运行前把 case 的目标、输入、环境、期望证据、评分方式、主指标、异常判定写进 case 定义
  （任务书 6.3 要求）。

## 与任务书对照

| 任务书要求 | 本插件落点 |
|---|---|
| Promptfoo 真实入链（5.1/5.2/G4） | `opencode:sdk` 执行 + assert 评判；结果入 `summary.json` 统一证据 |
| 真实 OpenCode（G3） | provider 以被测工作区为 `working_dir`、`agent=software-team-lead`，真实会话与委派 |
| 多方法评估（6/G13） | 三类任务断言策略见 methodology.md；llm-rubric 可选启用 |
| 可重复基准（7/G9） | `--repeat 5`、`--no-cache`、`maxConcurrency:1`、run 目录隔离 |
| 版本/模型对照（4.1/G10） | 同参数冻结 + 不同 `--agent`/工作区；`--provider/--model` 对照 |
| 异常隔离（6.3/G15） | 超时/崩溃/空结果记为异常，不进 PASS 统计，需补跑 |
| case 设计（6.3） | case 定义含目标/输入/环境/证据/评分/主指标/异常判定 |

**尚未覆盖**（后续模块）：本地结果 Web、逐 case 人工建议、优化副本闭环、OpenWork 全流程编排。
本插件的 `summary.json` 是这些下游模块的统一证据入口。

## 安全边界

- 被测专家包只读；评测产物只写入 `eval-runs/` 与 `.eval-results/`。
- 运行权限面由脚本生成：文件读/写/编辑 allow；bash 白名单外 deny；外部目录/doom_loop/webfetch deny。
- `--no-cache` 保证真实运行；导出/展示前脱敏。
