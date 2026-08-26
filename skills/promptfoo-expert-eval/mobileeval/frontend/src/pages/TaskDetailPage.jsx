import React, { useEffect, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronRight, ArrowLeft, Pencil, Play, X, Save } from 'lucide-react'
import { api } from '../api'
import { Modal, StatusBadge, ScenarioBadge, Empty, Spinner, fmtTime, fmtMs, HelpButton, TaskVsCaseHelp } from '../components/ui'

const ASSERT_LABELS = {
  javascript: 'JS 脚本',
  'javascript:equals': 'JS 相等',
  regex: '正则匹配',
  contains: '包含文本',
  icontains: '包含（忽略大小写）',
  'not-contains': '不包含',
  equals: '文本相等',
  'is-json': 'JSON 结构',
  'is-error': '应报错',
}

export default function TaskDetailPage() {
  const { objectId, taskId } = useParams()
  const [task, setTask] = useState(null)
  const [runs, setRuns] = useState([])
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(null)
  const [showRun, setShowRun] = useState(false)
  const [runForm, setRunForm] = useState({ repeat: 1, provider: '', model: '', concurrency: 4, variant: '', experiment_id: '' })
  const [experiments, setExperiments] = useState([])
  const [launching, setLaunching] = useState(false)
  const [polling, setPolling] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [detail, setDetail] = useState(null)   // {kind: 'assertion'|'metric', index}

  const load = useCallback(async () => {
    try {
      const t = await api.getTask(taskId)
      setTask(t)
      setRuns(await api.listRuns({ task_id: taskId }))
      setError('')
      setPolling(true)
    } catch (e) { setError(e.message) }
  }, [taskId])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.listExperiments(objectId).then(setExperiments).catch(() => {}) }, [objectId])
  useEffect(() => {
    if (!polling) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [polling, load])

  const launch = async () => {
    setLaunching(true)
    try {
      await api.createRun(taskId, runForm)
      setShowRun(false); load()
    } catch (e) { setError(`发起失败：${e.message}`) }
    finally { setLaunching(false) }
  }

  const save = async () => {
    try {
      await api.updateTask(taskId, { ...form, assertions: JSON.parse(form.assertions || '[]'), human_metrics: JSON.parse(form.human_metrics || '[]') })
      setEditing(false); load()
    } catch (e) { setError(`保存失败：${e.message}`) }
  }

  if (error && !task) return <div className="card !border-danger/40 text-danger">{error}</div>
  if (!task) return <Empty text="加载中…" />

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link to={`/objects/${objectId}`} className="btn !px-2.5" aria-label="返回"><ArrowLeft size={14} /></Link>
        <h1 className="text-xl font-semibold">{task.name}</h1>
        <ScenarioBadge type={task.scenario_type} />
        <HelpButton onClick={() => setHelpOpen(true)} title="评测任务 vs 评测用例 关系说明" />
        <div className="ml-auto flex gap-2">
          <button className="btn" onClick={() => {
            setForm({ ...task, assertions: JSON.stringify(task.assertions, null, 2), human_metrics: JSON.stringify(task.human_metrics, null, 2) })
            setEditing(true)
          }}><Pencil size={13} />编辑配置</button>
          <button className="btn btn-primary" onClick={() => setShowRun(true)}><Play size={13} />发起评测</button>
        </div>
      </div>
      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}

      <div className="card mb-4 grid md:grid-cols-2 gap-4 text-sm">
        <div>
          <div className="label">任务类型 / 自主度</div>
          <div className="flex gap-2">
            <ScenarioBadge type={task.scenario_type} />
            <span className="badge badge-team">{task.autonomy_level === 'low' ? '低自主（严格断言）' : '高自主（目标+验收）'}</span>
          </div>
          <div className="text-xs text-muted mt-2">{task.description || '无描述'}</div>
        </div>
        <div>
          <div className="label">固定提示词模板</div>
          <pre className="text-xs whitespace-pre-wrap bg-page rounded-default p-2 max-h-40 overflow-y-auto">{task.prompt_template || '（未设置）'}</pre>
        </div>
        <div>
          <div className="label">确定性断言（{task.assertions?.length || 0}）</div>
          {!task.assertions?.length ? (
            <div className="text-xs text-muted">未设置</div>
          ) : (
            <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
              {task.assertions.map((a, i) => (
                <button key={i} type="button"
                  className="w-full text-left flex items-center gap-2 border border-hairline rounded-default p-1.5 hover:border-accent/50 cursor-pointer"
                  onClick={() => setDetail({ kind: 'assertion', index: i })}>
                  <span className="badge badge-muted text-[10px] shrink-0">{ASSERT_LABELS[a.type] || a.type}</span>
                  <span className="flex-1 text-[11px] text-muted truncate">{String(a.value || '').split('\n')[0]}</span>
                  <ChevronRight size={12} className="text-muted shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="label">业务指标（人工评审用）</div>
          {!task.human_metrics?.length ? (
            <div className="text-xs text-muted">未设置</div>
          ) : (
            <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
              {task.human_metrics.map((m, i) => (
                <button key={i} type="button"
                  className="w-full text-left flex items-center gap-2 border border-hairline rounded-default p-1.5 hover:border-accent/50 cursor-pointer"
                  onClick={() => setDetail({ kind: 'metric', index: i })}>
                  <span className="text-xs font-medium shrink-0">{m.name}</span>
                  <span className="text-[10px] text-muted shrink-0">权重 {Math.round((m.weight || 0) * 100)}%</span>
                  <span className="flex-1 text-[11px] text-muted truncate">{String(m.criteria || m.description || '').split('\n')[0]}</span>
                  <ChevronRight size={12} className="text-muted shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold mb-3">评测记录（{runs.length}）</h3>
        {runs.length === 0 ? <Empty text="点击右上角发起第一次评测（或到中间对话框让 AI 发起）" /> : (
          <table className="table-base">
            <thead>
              <tr><th>#</th><th>状态</th><th>分数</th><th>进度 / 通过·失败</th><th>模型</th><th>并发</th><th>耗时</th><th>时间</th><th></th></tr>
            </thead>
            <tbody>
              {runs.map(r => {
                const done = (r.pass_count || 0) + (r.fail_count || 0) + (r.error_count || 0)
                const running = r.status === 'running' || r.status === 'pending'
                return (
                  <tr key={r.id}>
                    <td className="font-mono">{r.id}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="font-semibold">{r.score != null ? r.score.toFixed(2) : '—'}</td>
                    <td>
                      {running
                        ? <span className="text-accent">{done}/{r.total_cases || '…'}<span className="text-muted">（进行中）</span></span>
                        : <span>{r.pass_count}/{r.fail_count}{r.error_count ? ` +${r.error_count}异常` : ''}</span>}
                    </td>
                    <td className="text-xs">{r.model}</td>
                    <td>{r.concurrency || 1}</td>
                    <td>{fmtMs(r.duration_ms)}</td>
                    <td className="text-xs text-muted">{fmtTime(r.created_at)}</td>
                    <td className="text-right">
                      <Link to={`/runs/${r.id}`} className="text-accent text-xs">报告</Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <Modal open={showRun} title="发起评测" onClose={() => setShowRun(false)}>
        <div className="grid gap-3 text-sm">
          <div className="text-muted text-xs">
            将启动真实 OpenCode 会话（opencode:sdk + promptfoo），使用该对象已审核通过的 case。运行中请勿关闭页面。
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label">重复次数</label>
              <input type="number" min={1} className="input" value={runForm.repeat}
                onChange={(e) => setRunForm({ ...runForm, repeat: e.target.value })} />
            </div>
            <div>
              <label className="label">并发数（1-100）</label>
              <input type="number" min={1} max={100} className="input" value={runForm.concurrency}
                title="并发执行的 case 数；DeepSeek 端点最高支持约 100 并发"
                onChange={(e) => setRunForm({ ...runForm, concurrency: Math.max(1, Math.min(100, Number(e.target.value) || 4)) })} />
            </div>
            <div>
              <label className="label">provider（覆盖）</label>
              <input className="input" value={runForm.provider} onChange={(e) => setRunForm({ ...runForm, provider: e.target.value })} />
            </div>
            <div>
              <label className="label">model（覆盖）</label>
              <input className="input" value={runForm.model} onChange={(e) => setRunForm({ ...runForm, model: e.target.value })} />
            </div>
            <div>
              <label className="label">对照实验（可选）</label>
              <select className="input" value={runForm.experiment_id || ''}
                onChange={(e) => setRunForm({ ...runForm, experiment_id: e.target.value })}>
                <option value="">（不关联实验）</option>
                {experiments.map(exp => <option key={exp.id} value={exp.id}>{exp.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">对照实验 variant（可选）</label>
              <input className="input" value={runForm.variant || ''} placeholder="如 deepseek-chat / v2 / with-agent"
                onChange={(e) => setRunForm({ ...runForm, variant: e.target.value })} />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={() => setShowRun(false)}><X size={13} />取消</button>
          <button className="btn btn-primary" disabled={launching} onClick={launch}>{launching ? <Spinner light /> : <><Play size={13} />启动评测</>}</button>
        </div>
      </Modal>

      <Modal open={editing} title="编辑任务配置" onClose={() => setEditing(false)} width="max-w-2xl">
        {form && (
          <div className="grid gap-3 text-sm">
            <div>
              <label className="label">名称</label>
              <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">任务类型</label>
                <select className="input" value={form.scenario_type} onChange={(e) => setForm({ ...form, scenario_type: e.target.value })}>
                  <option value="structured">结构化</option>
                  <option value="hybrid">混合式</option>
                  <option value="open_ended">开放式</option>
                </select>
              </div>
              <div>
                <label className="label">自主度</label>
                <select className="input" value={form.autonomy_level} onChange={(e) => setForm({ ...form, autonomy_level: e.target.value })}>
                  <option value="low">低</option>
                  <option value="high">高</option>
                </select>
              </div>
            </div>
            <div>
              <label className="label">固定提示词模板（支持 {'{output_dir}'} 占位）</label>
              <textarea className="input font-mono text-xs" rows={5} value={form.prompt_template} onChange={(e) => setForm({ ...form, prompt_template: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">断言（JSON）</label>
                <textarea className="input font-mono text-xs" rows={4} value={form.assertions} onChange={(e) => setForm({ ...form, assertions: e.target.value })} />
              </div>
              <div>
                <label className="label">业务指标（JSON）</label>
                <textarea className="input font-mono text-xs" rows={4} value={form.human_metrics} onChange={(e) => setForm({ ...form, human_metrics: e.target.value })} />
              </div>
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={() => setEditing(false)}><X size={13} />取消</button>
          <button className="btn btn-primary" onClick={save}><Save size={13} />保存</button>
        </div>
      </Modal>

      <TaskVsCaseHelp open={helpOpen} onClose={() => setHelpOpen(false)} />

      <Modal open={!!detail} title={
        detail?.kind === 'assertion'
          ? `断言 #${(detail.index || 0) + 1} · ${ASSERT_LABELS[task.assertions?.[detail.index]?.type] || task.assertions?.[detail.index]?.type || '未知类型'}`
          : detail?.kind === 'metric'
            ? `业务指标 #${(detail.index || 0) + 1} · ${task.human_metrics?.[detail.index]?.name || ''}`
            : ''
      } onClose={() => setDetail(null)} width="max-w-xl">
        {detail?.kind === 'assertion' && (
          <div className="grid gap-3 text-sm">
            <div className="text-xs text-muted">自动判分规则，评测运行时由 promptfoo 执行：</div>
            <pre className="bg-page rounded-default p-3 text-xs whitespace-pre-wrap break-all max-h-96 overflow-y-auto">{task.assertions?.[detail.index]?.value || '—'}</pre>
          </div>
        )}
        {detail?.kind === 'metric' && (() => {
          const m = task.human_metrics?.[detail.index] || {}
          return (
            <div className="grid gap-3 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium">{m.name}</span>
                <span className="badge badge-team">权重 {Math.round((m.weight || 0) * 100)}%</span>
              </div>
              <div>
                <div className="label">评分标准</div>
                <p className="whitespace-pre-wrap text-muted">{m.criteria || m.description || '—'}</p>
              </div>
            </div>
          )
        })()}
      </Modal>
    </div>
  )
}
