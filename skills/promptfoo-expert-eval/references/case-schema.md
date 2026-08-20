# Case 定义规范（case-schema.md）

自定义 case 用于在默认 case 库之外追加评测对象。使用者可在 OpenWork / Claude 会话中描述一个任务，
由本插件按本规范将其整理为 YAML case 文件（或直接手写），再由 `run_eval.py --case-file <path>` 加载执行。
内置默认库见 `cases/default-cases.yaml`。

## 字段

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `id` | 是 | string | 唯一标识，仅允许 `[a-z0-9-]`，作为 run 目录与结果文件命名前缀 |
| `title` | 是 | string | 人类可读标题 |
| `type` | 是 | enum | `structured` / `hybrid` / `open-ended`，决定评测方法（见 references/methodology.md） |
| `description` | 否 | string | 任务目标、主指标、异常判定说明，写入报告 |
| `prompt` | 是 | string（块标量） | 发给被测团长（agent）的任务文本；可含 `{output_dir}` 占位符 |
| `output_dir` | 是 | string | 产物目录，相对 working_dir；建议形如 `eval-runs/{run_id}/<case-id>`，`{run_id}` 由脚本替换 |
| `setup.files` | 否 | list | 运行前预置的 fixture 文件：`path`（相对 output_dir）+ `content`（块标量） |
| `bash_allow` | 否 | list[string] | bash 命令白名单（glob 模式）。缺省用默认白名单：`node *`、`git status*`、`git diff*`、`git log*`、`python *` |
| `bash_deny_override` | 否 | bool | 若为 true，bash 全部 deny（纯只读 case 用） |
| `webfetch` | 否 | bool | 是否允许 webfetch（默认 false，离线评测） |
| `assertions` | 是 | list | Promptfoo assert 数组，见下 |
| `main_metric` | 否 | string | 主指标定义（任务书 6.3） |
| `anomaly_rules` | 否 | string | 异常判定规则（任务书 6.3） |

## assertions

复用 Promptfoo 原生断言（`contains`、`regex`、`javascript` 等）。常用两类：

```yaml
assertions:
  - type: contains          # 输出文本包含子串（结构化硬约束）
    value: "app.js"
  - type: regex             # 输出文本匹配正则
    value: "(?i)(pass|通过)"
  - type: javascript        # 确定性断言，可访问文件系统验证产物
    value: |
      const fsp = import('node:fs');
      return fsp.then(m => m.default.existsSync({output_dir_abs} + '/app.js'));
```

- 文本断言作用于 agent 的**最终输出**；产物类断言用 `javascript` + `{output_dir_abs}`（绝对路径 JSON 字符串）。
- `javascript` 断言环境：`output`（最终输出文本）、`vars`、`process`（shim）。断言体是**同步函数体**：
  以 `const ...` 声明开头的多行代码按原样执行，最后返回布尔值或 **Promise**（推荐用
  `import('node:fs')` 访问文件系统，`require` 不可用）。返回 true/false，或 `{pass, reason}` 对象。
- 混合式/开放式任务建议配合 llm-rubric（模型裁判），启用方式见 methodology.md。

## 示例：自定义一个 case

```yaml
- id: my-custom-case
  title: "自定义：生成项目脚手架"
  type: structured
  description: "主指标 = 脚手架文件齐全；异常判定 = 产物缺失"
  prompt: |
    请为 Python 项目生成最小脚手架，全部产物放入 {output_dir}：
    包含 pyproject.toml、src/__init__.py、README.md。不要询问任何问题。
  output_dir: "eval-runs/{run_id}/my-custom-case"
  bash_allow:
    - "python *"
  assertions:
    - type: javascript
      value: |
        const fsp = import('node:fs');
        return fsp.then(m => m.default.existsSync({output_dir_abs} + '/pyproject.toml'));
  main_metric: "产物齐全（1 项断言）"
  anomaly_rules: "pyproject.toml 缺失判失败"
```

## 加载规则

- 默认库 `cases/default-cases.yaml` 始终加载；`--case <id>` 按 id 过滤。
- `--case-file <path>` 追加自定义 case（可多次指定），与默认库按 id 去重（自定义优先）。
- 文件支持 `.yaml` / `.yml` / `.json`；解析优先 PyYAML，缺失时回退 JSON。
