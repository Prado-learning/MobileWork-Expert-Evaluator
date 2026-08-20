import React, { useState } from 'react'
import { Brain, FileInput, Puzzle, CircleCheck, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../api'
import { Modal, Spinner, Empty } from './ui'

const STATUS = {
  pending: { cls: 'badge-running', text: '待审核' },
  approved: { cls: 'badge-pass', text: '审核通过' },
}
const TYPE = {
  structured: '结构化', hybrid: '混合式', open_ended: '开放式',
}

/** Case 管理：AI 自动生成 case 集 → 人工审核（通过/编辑后通过/删除）→ 评测使用已审核 case。 */
export default function CaseManager({ objectId, onCasesChange }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [edit, setEdit] = useState(null)          // 编辑中的 case
  const [error, setError] = useState('')
  const [genCount, setGenCount] = useState(6)
  const [genMode, setGenMode] = useState('replace')   // replace=覆盖未审核 | append=直接追加
  const [confirmOpen, setConfirmOpen] = useState(false)   // 生成前确认弹窗（模式 + 数量）
  const [logicOpen, setLogicOpen] = useState(false)
  const [expandedPrompt, setExpandedPrompt] = useState(null)  // 展开查看完整 prompt 的 case id

  const load = async () => {
    try {
      const r = await api.listCases(objectId)
      setData(r)
      onCasesChange?.(r.cases || [])
      setError('')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }
  React.useEffect(() => { setLoading(true); load() }, [objectId])

  const generate = async () => {
    setConfirmOpen(false)
    setGenerating(true)
    setError('')
    try { await api.generateCases(objectId, genCount, genMode); await load() }
    catch (e) { setError(`生成失败：${e.message}`) }
    finally { setGenerating(false) }
  }

  const act = async (fn, msg) => {
    setError('')
    try { await fn(); await load() } catch (e) { setError(`${msg}：${e.message}`) }
  }

  if (loading) return <div className="card"><Empty text="加载中…" /></div>
  const cases = data?.cases || []
  const counts = { pending: 0, approved: 0 }
  cases.forEach(c => { counts[c.status] = (counts[c.status] || 0) + 1 })

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="font-semibold" title="AI 自动生成 → 人工审核 → 评测使用审核通过的 case">Case 管理</h3>
          <div className="text-xs text-muted mt-1 flex gap-3">
            <span>待审核 <b className="text-ink">{counts.pending}</b></span>
            <span className="text-accent">审核通过 <b>{counts.approved}</b></span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn !px-2 !py-1 text-xs" onClick={() => setLogicOpen(true)} title="查看 Case 生成逻辑">
            <Brain size={13} className="text-accent" /> 生成逻辑
          </button>
          <button className="btn btn-primary" disabled={generating} onClick={() => setConfirmOpen(true)}>
            {generating ? <Spinner light /> : 'AI 生成 Case'}
          </button>
        </div>
      </div>
      {error && <div className="text-danger text-xs mb-3">{error}</div>}

      {/* 生成前确认弹窗：选择 追加/覆盖 模式 + 生成数量 */}
      <Modal open={confirmOpen} title="生成评测 Case" onClose={() => setConfirmOpen(false)}>
        <div className="space-y-4 text-sm">
          <div>
            <div className="font-medium mb-2">生成模式（已审核通过的 case 两种模式都会保留）</div>
            <div className="space-y-2">
              <label className={`flex items-start gap-2 border border-hairline rounded-default p-3 cursor-pointer ${genMode === 'append' ? 'border-accent bg-accent/5' : ''}`}>
                <input type="radio" name="gen-mode" checked={genMode === 'append'} onChange={() => setGenMode('append')} />
                <span>
                  <span className="font-medium">追加</span>
                  <span className="block text-xs text-muted mt-0.5">保留全部旧用例（含待审核），只新增一批，不删除任何内容</span>
                </span>
              </label>
              <label className={`flex items-start gap-2 border border-hairline rounded-default p-3 cursor-pointer ${genMode === 'replace' ? 'border-accent bg-accent/5' : ''}`}>
                <input type="radio" name="gen-mode" checked={genMode === 'replace'} onChange={() => setGenMode('replace')} />
                <span>
                  <span className="font-medium">覆盖未审核</span>
                  <span className="block text-xs text-muted mt-0.5">删除旧的「待审核 / 已拒绝」用例后重新生成，已审核通过的不动（推荐）</span>
                </span>
              </label>
            </div>
          </div>
          <div>
            <div className="font-medium mb-2">生成数量（1-12 个不同的 case）</div>
            <input type="number" min={1} max={12} className="input !w-28" value={genCount}
              onChange={(e) => setGenCount(Math.max(1, Math.min(12, Number(e.target.value) || 6)))} />
            <div className="text-xs text-muted mt-1">当前：待审核 {counts.pending} 个 / 审核通过 {counts.approved} 个。
              本次将生成 {genCount} 个新 case 供审核。</div>
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-hairline">
            <button className="btn" onClick={() => setConfirmOpen(false)}>取消</button>
            <button className="btn btn-primary" disabled={generating} onClick={generate}>
              {generating ? <Spinner light /> : '确认生成'}
            </button>
          </div>
        </div>
      </Modal>

      {cases.length === 0 ? (
        <Empty text="暂无 case，点击右上角「AI 生成 Case」（基于被测专家定义 + 任务自动生成，供你审核）" />
      ) : (
        <div className="space-y-2">
          {cases.map((c) => {
            const st = STATUS[c.status] || STATUS.pending
            return (
              <div key={c.id} className="border border-hairline rounded-default p-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`badge ${st.cls}`}>{st.text}</span>
                  <code className="text-xs text-muted">{c.case_id}</code>
                  <span className="font-medium text-sm">{c.title}</span>
                  <span className="badge badge-team">{TYPE[c.type] || c.type}</span>
                  {c.auto_generated ? <span className="badge badge-muted">AI 生成</span> : null}
                  <div className="ml-auto flex gap-1.5 flex-wrap">
                    {c.status !== 'approved' && (
                      <button className="btn btn-primary !px-2 !py-0.5 text-xs"
                        onClick={() => act(() => api.approveCase(c.id), '操作失败')}>通过</button>
                    )}
                    <button className="btn !px-2 !py-0.5 text-xs" onClick={() => setEdit(c)}>编辑</button>
                    <button className="btn btn-danger !px-2 !py-0.5 text-xs"
                      onClick={() => act(() => api.deleteCase(c.id), '删除失败')}>删除</button>
                  </div>
                </div>
                <button className="w-full text-left text-xs text-muted mt-1 hover:text-ink flex items-start gap-1"
                  onClick={() => setExpandedPrompt(expandedPrompt === c.id ? null : c.id)}>
                  <span className="shrink-0 mt-0.5 text-muted">
                    {expandedPrompt === c.id ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  </span>
                  <span className="break-all whitespace-pre-wrap">
                    {expandedPrompt === c.id ? c.prompt : `${c.prompt.slice(0, 100)}${c.prompt.length > 100 ? '…（点击展开）' : ''}`}
                  </span>
                </button>
              </div>
            )
          })}
        </div>
      )}

      {edit && (
        <CaseEditModal
          c={edit}
          onClose={() => setEdit(null)}
          onSave={async (body) => {
            try {
              await api.updateCase(edit.id, body)
              await api.approveCase(edit.id)   // 编辑保存即通过
              await load()
              setEdit(null)
            } catch (e) { setError(`保存失败：${e.message}`) }
          }}
        />
      )}

      {logicOpen && <CaseLogicModal onClose={() => setLogicOpen(false)} />}
    </div>
  )
}

/** Case 生成逻辑说明弹窗：从哪些方面生成 case、基于什么考虑。 */
function CaseLogicModal({ onClose }) {
  const rows = [
    {
      icon: FileInput,
      title: '生成依据（输入）',
      items: [
        '被测专家/专家团的定义：角色、权限、委派关系、工作流（读取 .opencode 配置）',
        '任务配置：任务名称与描述（来自 analyze_expert 分析结果）',
        '生成数量：默认 6 个，上限 12（超过 6 分批生成）',
      ],
    },
    {
      icon: Puzzle,
      title: '从哪些方面生成（场景覆盖）',
      items: [
        '结构化：精确产出 + 确定性断言 —— 产物可被程序自动校验（contains / regex / javascript）',
        '混合式：硬约束 + 专业判断 —— 产物正确性与专业质量并重',
        '开放式：高自主，只给目标与验收标准 —— 靠人工评审把关（断言可留空）',
        'case 之间按不同能力侧重分配，避免重复；任务性质明确时可侧重某类场景',
      ],
    },
    {
      icon: Brain,
      title: '基于什么考虑（设计原则）',
      items: [
        '匹配专家团编排：涉及团长的 case，prompt 要求委派对应团员、由团长验收汇总',
        '断言可自动化：使用 promptfoo 语法（contains/regex/javascript），javascript 用固定模板、禁止 require',
        '可评测性：产物位置一律用 {output_dir} 占位，严禁在 prompt 中写死文件路径',
        '规模可控：单个 case 须在 5 分钟内完成（opencode 运行窗口限制），聚焦 1 个明确功能、委派 ≤2 个团员',
      ],
    },
    {
      icon: CircleCheck,
      title: '审核闭环',
      items: [
        '生成模式可切换：「覆盖未审核」删除旧待审核用例再生成新一批；「追加」保留全部旧用例、只新增一批；两种模式都已审核通过的 case 保留、不重复生成',
        '人工审核：通过 → 供评测使用；编辑后保存 → 直接审核通过；删除 → 移除该 case',
        '评测只使用「已通过」的 case 集（评测引擎按 case.status=approved 过滤）',
      ],
    },
  ]
  return (
    <Modal open title="Case 生成逻辑" onClose={onClose} width="max-w-2xl">
      <div className="grid gap-4">
        {rows.map((r) => (
          <div key={r.title}>
            <div className="font-semibold text-sm flex items-center gap-1.5">
              <r.icon size={15} className="text-accent shrink-0" />{r.title}
            </div>
            <ul className="mt-1.5 space-y-1 text-sm text-muted">
              {r.items.map((it, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-accent shrink-0">·</span>
                  <span>{it}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="flex justify-end mt-5">
        <button className="btn btn-primary" onClick={onClose}>知道了</button>
      </div>
    </Modal>
  )
}

function CaseEditModal({ c, onClose, onSave }) {
  const [form, setForm] = useState({
    title: c.title, type: c.type, prompt: c.prompt, output_dir: c.output_dir,
    assertions: JSON.stringify(c.assertions || [], null, 2),
  })
  const [assertMode, setAssertMode] = useState('form')   // form=字段表单 | json=JSON 编辑
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const save = async () => {
    try {
      await onSave({ ...form, assertions: JSON.parse(form.assertions || '[]') })
    } catch (e) { alert(`断言 JSON 格式错误：${e.message}`) }
  }
  // 表单视图用的断言列表（与 form.assertions JSON 字符串双向同步）
  let assertions = []
  try { assertions = JSON.parse(form.assertions || '[]') } catch { /* JSON 视图编辑中，非法时表单视图回退空 */ }
  const setAssertions = (list) => setForm({ ...form, assertions: JSON.stringify(list, null, 2) })
  const patchAssert = (i, patch) => {
    const next = [...assertions]; next[i] = { ...next[i], ...patch }; setAssertions(next)
  }
  const ASSERT_TYPES = [
    ['contains', 'contains（包含文本）'], ['regex', 'regex（正则匹配）'],
    ['javascript', 'javascript（产物文件断言）'], ['llm-rubric', 'llm-rubric（业务评分）'],
    ['delegation', 'delegation（委派断言）'], ['tool-call', 'tool-call（工具调用）'],
    ['kb-hit', 'kb-hit（知识命中）'],
  ]
  return (
    <Modal open title={`编辑 Case：${c.case_id}`} onClose={onClose} width="max-w-2xl">
      <div className="grid gap-3 text-sm">
        <div>
          <label className="label">标题</label>
          <input className="input" value={form.title} onChange={set('title')} />
        </div>
        <div>
          <label className="label">类型</label>
          <select className="input" value={form.type} onChange={set('type')}>
            <option value="structured">结构化</option>
            <option value="hybrid">混合式</option>
            <option value="open_ended">开放式</option>
          </select>
        </div>
        <div>
          <label className="label">任务提示词（支持 {"{output_dir}"} 占位）</label>
          <textarea className="input font-mono text-xs" rows={8} value={form.prompt} onChange={set('prompt')} />
        </div>
        <div>
          <label className="label">产物目录</label>
          <input className="input font-mono text-xs" value={form.output_dir} onChange={set('output_dir')} />
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="label !mb-0">断言</label>
            <div className="flex items-center gap-1 text-xs border border-hairline rounded-default p-0.5">
              <button className={`px-1.5 py-0.5 rounded-default ${assertMode === 'form' ? 'bg-accent/10 text-accent' : 'text-muted hover:text-ink'}`}
                onClick={() => setAssertMode('form')}>表单</button>
              <button className={`px-1.5 py-0.5 rounded-default ${assertMode === 'json' ? 'bg-accent/10 text-accent' : 'text-muted hover:text-ink'}`}
                onClick={() => setAssertMode('json')}>JSON</button>
            </div>
          </div>
          {assertMode === 'json' ? (
            <textarea className="input font-mono text-xs" rows={6} value={form.assertions} onChange={set('assertions')} />
          ) : (
            <div className="space-y-2">
              {assertions.map((a, i) => (
                <div key={i} className="border border-hairline rounded-default p-2">
                  <div className="flex items-center gap-2 mb-1.5">
                    <select className="input !w-52 !py-1 text-xs" value={a.type || 'contains'}
                      onChange={(e) => patchAssert(i, { type: e.target.value })}>
                      {ASSERT_TYPES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                    </select>
                    {a.type === 'llm-rubric' && (
                      <input className="input !py-1 text-xs" placeholder="metric（如 可用性）" value={a.metric || ''}
                        onChange={(e) => patchAssert(i, { metric: e.target.value })} />
                    )}
                    <button className="btn btn-danger !px-1.5 !py-0.5 ml-auto" title="删除该断言"
                      onClick={() => setAssertions(assertions.filter((_, j) => j !== i))}>删</button>
                  </div>
                  <textarea className="input font-mono text-[11px]" rows={2} placeholder="断言值（contains 文本 / regex 正则 / js 代码 / rubric 评分标准 / agent 名等）"
                    value={typeof a.value === 'object' ? JSON.stringify(a.value, null, 1) : (a.value ?? '')}
                    onChange={(e) => patchAssert(i, { value: e.target.value })} />
                </div>
              ))}
              {assertions.length === 0 && <div className="text-xs text-muted text-center py-2">暂无断言</div>}
              <button className="btn text-xs" onClick={() => setAssertions([...assertions, { type: 'contains', value: '' }])}>+ 添加断言</button>
            </div>
          )}
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn btn-primary" onClick={save}>保存并审核通过</button>
      </div>
    </Modal>
  )
}
