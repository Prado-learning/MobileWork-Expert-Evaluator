# 评测方法论（methodology.md）

## 1. 任务类型与评测方法（任务书 3.3）

| 任务类型 | 内置 case | 评测方法 | 断言形式 |
|---|---|---|---|
| 结构化任务 | `todo-cli`、`bugfix-utils`（硬约束部分） | 确定性断言 | `contains` / `regex`（作用于最终输出）+ `javascript`（验证产物文件） |
| 混合式任务 | `prd-priority`、`bugfix-utils` | 硬约束断言 + 专业判断 | 硬约束用 `contains`/`javascript`；质量部分用 rubric / 模型裁判 / 人工复核 |
| 开放式任务 | `feature-design` | 不强制确定性断言 | 明确 rubric、证据引用、模型裁判或人工评审 |

**原则**：没有确定性断言不等于无法验收。开放式任务必须预先定义质量维度、评分依据、
证据位置、裁判条件与人工复核方式（在 case 的 `description` / `main_metric` / `anomaly_rules` 中声明）。

## 2. Promptfoo 集成记录（任务书 5.2）

- **版本**：0.121.20（全局 npm 安装）。许可证 MIT。安装方式：`npm install -g promptfoo`。
- **provider**：`opencode:sdk`。验证结论：支持 `working_dir`（加载被测工作区 `.opencode/` 配置）、
  `agent`（选中被测团长）、`tools` / `permission`（非交互运行权限面）、`timeout`（server 启动超时）、
  `provider_id` / `model`（模型对照）。
- **在本链路中的位置**：Promptfoo 负责**执行**（opencode:sdk provider 驱动真实 OpenCode 会话）
  与**确定性评判**（assert 断言）。结果进入 `results.json` → 统一 `summary.json` 证据。
- **本组适配**：`run_eval.py` 生成 provider 配置（权限面、工具面、bash 白名单）、case 编排、
  占位符替换（`{output_dir}` / `{output_dir_abs}`）、结果解析与汇总。
- **会话/子会话证据**：`opencode:sdk` 每次调用默认新建会话；`--repeat N` 得到 N 次独立会话。
  响应 metadata 中的 session id 尽力提取到 case 记录（`metadata` / `session_ids`），
  供后续本地 Web 关联主/子会话证据。
- **异常/重试/缓存/并发/脱敏**：
  - 缓存：强制 `--no-cache`（`PROMPTFOO_CACHE_ENABLED=false`），真实运行不读缓存。
  - 并发：`maxConcurrency: 1`，避免多个 case 写文件竞争（任务书文档「Managing Side Effects」）。
  - 超时：`--case-timeout-sec` 硬超时，超时进程终止并记为异常。
  - 重试：promptfoo 自身重试由 provider 处理；case 级重跑由使用者显式发起。
  - 脱敏：结果只落本地；导出/展示前需移除密钥与个人配置（见安全边界）。
  - `--model-outputs`（跳过模型调用、直喂预置输出）：实测对 `opencode:sdk` **不适用**——
    provider 初始化即启动 OpenCode server，会阻塞等待；该参数仅适用于其他 provider 的调试。
- **未解决差距**：模型裁判（llm-rubric）未默认启用；子会话级 token/成本统计依赖 provider 返回，
  当前尽力收集 `cost` 字段；本地 Web 与人工建议模块为后续扩展。
- **真实运行适配（实测）**：
  1. `deepseek` 不在 promptfoo opencode:sdk 的 `getApiKey` env 映射（仅 anthropic/openai/google），
     必须 `--api-key` 注入；
  2. agent 权限以 `.opencode/agents/*.md` frontmatter 为准，且优先于 provider `permission`；
     非交互评测需专用工作区（bash ask → 白名单 allow，见 README「真实运行适配」）；
  3. 共享 opencode 全局 DB 会并发冲突（SQLite FOREIGN KEY），run_eval.py 已按 run 隔离
     `XDG_DATA_HOME`；
  4. opencode SDK 默认 provider 超时 300s，case 规模需控制在窗口内。

## 3. 模型裁判（llm-rubric）启用方式

promptfoo 原生支持 `llm-rubric` 断言。启用步骤：

1. 在 case 的 `assertions` 中追加：

   ```yaml
   - type: llm-rubric
     value: |
       请按以下维度对输出评分（1-5）并说明理由：
       - 需求可度量性（是否可验收）
       - 优先级合理性（P0/P1/P2 是否符合业务价值）
       - 语言一致性（是否与用户需求语言一致）
     总分 >= 4 视为通过。
   ```

2. 指定裁判模型（promptfoo 的 `rubricProvider`，配置在 provider 或 defaultTest options；
   需要裁判模型对应的 API key / 模型配置）。裁判模型与偏差说明必须记录。

**偏差说明**：模型裁判可能偏好冗长输出、特定语言或固定格式；应配合人工复核抽样，
不能把裁判分数当作唯一事实（任务书 3.3「说明模型裁判可能存在的偏差」）。

## 4. 统计口径与异常判定（任务书 6.3）

- 1 次有效正式运行 = 冻结 case/版本/模型/工具/权限/环境后，插件启动独立真实 OpenCode 会话，
  执行到预先声明的终态，并保留会话、工具、产物、评分与异常证据。
- `--repeat 5` = 同一 case 从新会话独立运行 5 次，5 次结果全部进入统计（含失败/超时），
  不剔除失败样本。
- 不计入正式统计、需补跑的异常：mock/缓存复用、预制输出、无有效终态的中断、
  证据缺失、配置漂移、超协议人工干预。异常仍须记录并补跑。

## 5. 优化副本与对照（任务书 4.1/4.2 接口）

本插件负责「同一版本 × 同批 case」的受控基准。做优化前后对照时：

- 固定：case 集、模型、工具权限、运行环境（相同 `--working-dir`、`--repeat`、`--provider/--model`）。
- 改变：被测专家版本（优化副本指向不同工作区或 agent 定义，或通过 `--agent` 切换）。
- 输出两个版本的 `summary.json`，比较主指标通过率与逐 case 断言明细；无法固定的环境差异
  必须在报告中标注，不得误报为专家能力变化。
