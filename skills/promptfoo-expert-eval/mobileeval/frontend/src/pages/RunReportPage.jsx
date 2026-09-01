import React, { useEffect, useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Check, X, Star, MessageSquare, RotateCcw } from 'lucide-react'
import { api } from '../api'
import { StatusBadge, KindBadge, Empty, Modal, Spinner, HelpButton, fmtTime, fmtMs } from '../components/ui'
import Markdown from '../components/Markdown'

export default function RunReportPage() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [showReview, setShowReview] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [sessionDetail, setSessionDetail] = useState(null)   // 会话证据弹窗数据
  const [sessionLoadingId, setSessionLoadingId] = useState(null)  // 当前正在加载的会话 id（避免所有项一起转圈）
  const [reviewHelp, setReviewHelp] = useState(false)  // 人工评审说明弹窗
  const [rerunning, setRerunning] = useState(false)    // 一键重跑异常/失败 case

  const load = async () => {
    try {
      setReport(await api.getReport(runId))
      setError('')
    } catch (e) { setError(e.message) }
  }
  useEffect(() => { load() }, [runId])

  if (error) return <div className="card !border-danger/40 text-danger">{error}</div>
  if (!report) return <Empty text="加载中…" />

  const { run, cases, metrics, reviews, suggestions, object_name, object_kind, stability } = report
  const isSingle = object_kind === 'single'
  const chartData = cases.map(c => ({ name: c.case_id.replace(/^task-/, '').slice(0, 12), score: c.score ?? 0, pass: !!c.pass }))

  const failedCount = (run.fail_count || 0) + (run.error_count || 0)
  const finished = run.status !== 'running' && run.status !== 'pending'
  const rerunFailed = async () => {
    if (!window.confirm(`将新建一次评测，仅重跑本次 ${failedCount} 个失败/异常 case（沿用原版本/模型/专家团配置）。\n确认发起？`)) return
    setRerunning(true); setError('')
    try {
      const r = await api.rerunFailedCases(runId)
      navigate(`/runs/${r.id}`)
    } catch (e) { setError(`重跑失败：${e.message}`) }
    finally { setRerunning(false) }
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link to={`/objects/${run.object_id}`} className="btn !px-2">←</Link>
        <h1 className="text-xl font-semibold">{object_name} · 评测报告</h1>
        <StatusBadge status={run.status} />
        {finished && failedCount > 0 && (
          <button className="btn !py-1.5 text-xs" onClick={rerunFailed} disabled={rerunning}
            title="新建一次评测，仅重跑本次失败/异常的 case（省时省费用）">
            {rerunning ? <Spinner /> : <RotateCcw size={12} className="mr-1 inline" />}
            一键重跑异常/失败（{failedCount}）
          </button>
        )}
        <a className="btn !py-1.5 text-xs ml-auto" href={`/api/runs/${runId}/export`} download title="下载 eval.log / results.json / 每 case 输出与过程 trace 的完整原始数据">
          导出原始过程数据
        </a>
      </div>

      <div className="card mb-4 grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
        <div><div className="label">综合分数</div><span className="text-2xl font-semibold text-accent">{run.score != null ? run.score.toFixed(2) : '—'}</span></div>
        <div><div className="label">通过 / 失败 / 异常</div>{run.pass_count} / {run.fail_count} / {run.error_count}</div>
        <div><div className="label">模型</div>{run.model}</div>
        <div><div className="label">重复次数</div>{run.repeat}</div>
        <div><div className="label">运行时间</div>{fmtTime(run.created_at)}</div>
      </div>

      <div className="mb-4">
        <MetricGroup title={isSingle ? '模块级效能（过程拆解：工具 / 知识 / 输出）' : '模块级效能（过程拆解：工具 / 协同 / 知识 / 输出）'}
          metrics={(metrics.module || []).filter(m => !(isSingle && m.key === 'collaboration'))} tone="accent"
          explain={{
            title: '模块级效能指标说明',
            items: [
              { name: '工具调用准确率', desc: '由过程探针统计被测专家在整个评测过程中的工具调用成功占比（成功数 / 总数），反映专家操作工具（读文件、执行命令、编辑代码等）的正确性。' },
              ...(isSingle ? [] : [{ name: '多Agent协同', desc: '团长委派断言通过率（delegation 断言通过 / 总数），并记录实际委派次数。反映团长是否按协作 SOP 把任务正确委派给对应团员（如 Bug 场景 QA 复现 → 工程师修复的顺序）。' }]),
              { name: '知识匹配精准度', desc: 'kb-hit 断言通过率：检索/知识检索类工具（grep/read/webfetch 等）的输入中命中预期关键词的比例。未生成检索类断言时显示 —。' },
              { name: '输出质量分', desc: 'llm-rubric（业务视角 LLM 裁判）断言的得分，从可用性、相关性、完整性、可交付四个维度衡量最终交付物的质量。' },
            ],
          }} />
      </div>
      {stability?.per_case?.length > 0 && (
        <div className="card mb-4">
          <div className="flex items-center gap-3 mb-2">
            <h3 className="font-semibold">稳定性（多次跑测成功率）</h3>
            {stability.overall && (
              <span className="text-xs text-muted">
                平均成功率 {(stability.overall.avg_success_rate * 100).toFixed(1)}% · 波动 ±{(stability.overall.std * 100).toFixed(1)}% · {stability.overall.case_count} 个 case
              </span>
            )}
          </div>
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stability.per_case.map(p => ({ name: p.case_id.slice(0, 12), rate: p.success_rate * 100 }))}>
                <XAxis dataKey="name" fontSize={10} />
                <YAxis domain={[0, 100]} fontSize={11} />
                <Tooltip />
                <Bar dataKey="rate" name="成功率%" radius={[4, 4, 0, 0]}>
                  {stability.per_case.map((p, i) => <Cell key={i} fill={p.success_rate >= 0.8 ? '#1890ff' : '#c0392b'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      <div className="grid md:grid-cols-2 gap-4 mb-4">
        <MetricGroup title="技术性能指标（底层效能）" metrics={metrics.tech} tone="tech" />
        <MetricGroup title="用户可感知业务指标（产品视角）" metrics={metrics.business} tone="business"
          explain={{
            title: '业务指标（产品视角）说明',
            items: [
              { name: 'LLM 裁判自动评分', desc: '每个业务维度（如可用性 / 相关性 / 完整性 / 可交付）由 LLM 裁判按 case 的评分标准自动打分（llm-rubric 断言），聚合为平均分与评估次数，无需人工介入。' },
              { name: '人工综合评分', desc: '人工评审给出的 1-5 分综合评分（可多次评审取平均）。AI 无法判定或需要兜底复核的 case 会标记待人工评审。' },
              { name: '人类自定义指标', desc: '对象上配置的人类专属评估维度（专家意见：除内置指标外人类可提出指标），逐项聚合展示，由人工在评审时打分。' },
            ],
          }} />
      </div>

      <div className="grid md:grid-cols-3 gap-4 mb-4">
        <div className="card md:col-span-2">
          <h3 className="font-semibold mb-2">逐 case 得分</h3>
          {cases.length === 0 ? <Empty text="无 case" /> : (
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                <XAxis dataKey="name" fontSize={10} />
                <YAxis domain={[0, 1]} fontSize={11} />
                <Tooltip />
                <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                  {chartData.map((d, i) => <Cell key={i} fill={d.pass ? '#1890ff' : '#c0392b'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <h3 className="font-semibold mb-2">会话证据（点击查看详情）</h3>
          <div className="text-xs text-muted space-y-1">
            {(run.session_ids || []).map(s => (
              <button key={s} className="btn !px-1.5 !py-1 text-[11px] font-mono w-full text-left truncate"
                title="点击查看会话消息详情" disabled={sessionLoadingId === s}
                onClick={async () => {
                  setSessionLoadingId(s)
                  try { setSessionDetail(await api.getRunSession(runId, s)) }
                  catch (e) { setSessionDetail({ error: e.message }) }
                  finally { setSessionLoadingId(null) }
                }}>
                {sessionLoadingId === s ? <Spinner /> : <MessageSquare size={11} className="inline mr-1" />}{s}
              </button>
            ))}
            {(run.session_ids || []).length === 0 && <span>无会话记录</span>}
          </div>
        </div>
      </div>

      <div className="card mb-4">
        <h3 className="font-semibold mb-3">case 明细（{cases.length}）</h3>
        {cases.length === 0 ? <Empty text="无 case" /> : cases.map(c => <CaseRow key={c.id} c={c} />)}
      </div>

      <div className="card mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold">人工评审</h3>
            <HelpButton onClick={() => setReviewHelp(true)} title="人工评审说明" />
          </div>
          <button className="btn btn-primary" onClick={() => setShowReview(true)}>+ 提交评审</button>
        </div>
        {reviews.length === 0 ? <Empty text="暂无人工评审" /> : (
          <div className="space-y-3">
            {reviews.map(r => (
              <div key={r.id} className="border border-hairline rounded-default p-3">
                <div className="flex items-center gap-3 text-sm">
                  <span className="flex gap-0.5 shrink-0">
                    {[1, 2, 3, 4, 5].map(n => (
                      <Star key={n} size={13} className={n <= (r.rating || 0) ? 'text-accent fill-accent' : 'text-hairline'} />
                    ))}
                  </span>
                  <span className="text-xs text-muted">{fmtTime(r.created_at)}</span>
                  {r.ai_consumed ? <span className="badge badge-pass">AI 已读取</span> : <span className="badge badge-muted">待 AI 读取</span>}
                  <button className="btn btn-danger !px-2 !py-0.5 text-xs ml-auto" onClick={async () => { await api.deleteReview(r.id); load() }}>删除</button>
                </div>
                {r.comments && <div className="text-sm mt-2 whitespace-pre-wrap">{r.comments}</div>}
                {r.metrics?.length > 0 && (
                  <div className="flex flex-wrap gap-3 mt-2 text-xs text-muted">
                    {r.metrics.map(m => <span key={m.name}>{m.name}: <b className="text-ink">{m.score ?? '—'}</b></span>)}
                  </div>
                )}
                <button className="btn text-xs mt-2" disabled={suggesting}
                  onClick={async () => { setSuggesting(true); try { await api.invokeTool('generate_suggestions', { run_id: Number(runId), review_id: r.id }); load() } catch (e) { alert(e.message) } finally { setSuggesting(false) } }}>
                  {suggesting ? <Spinner /> : '基于此评审生成 AI 优化建议'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold">AI 优化建议（人工纠错 → AI 优化闭环）</h3>
          <button className="btn" disabled={suggesting}
            onClick={async () => { setSuggesting(true); try { await api.invokeTool('generate_suggestions', { run_id: Number(runId) }); load() } catch (e) { alert(e.message) } finally { setSuggesting(false) } }}>
            {suggesting ? <Spinner /> : '自动生成建议'}
          </button>
        </div>
        {suggestions.length === 0 ? <Empty text="暂无建议，点击生成" /> : (
          <div className="space-y-3">
            {suggestions.map(s => (
              <div key={s.id} className="border border-hairline rounded-default p-3">
                <div className="text-xs text-muted mb-2 flex gap-2">
                  <span className="badge badge-team">{s.source === 'review-driven' ? '评审驱动' : '自动'}</span>
                  <span>{fmtTime(s.created_at)}</span>
                </div>
                <div className="text-sm"><Markdown>{s.content}</Markdown></div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showReview && <ReviewModal runId={runId} objectId={run.object_id} onClose={() => setShowReview(false)} onDone={load} />}
      {sessionDetail && <SessionModal data={sessionDetail} onClose={() => setSessionDetail(null)} />}
      <Modal open={reviewHelp} title="人工评审说明" onClose={() => setReviewHelp(false)} width="max-w-lg">
        <div className="space-y-2 text-sm leading-relaxed">
          <p><b className="text-ink">何时转人工：</b>AI 无法自动判定或需要兜底复核的 case 会标记「待人工评审」，由你给出结论与综合评分。</p>
          <p><b className="text-ink">如何被使用：</b>点击「自动生成建议」或单条评审的「基于此评审生成 AI 优化建议」时，<b className="text-ink">全部人工评审（综合评分 + 逐 case 纠错）都会喂给 AI</b> 生成优化建议，并记入 <code>ai_suggestions</code>。</p>
          <p><b className="text-ink">闭环落点：</b>迭代优化页（/optimize）直接读取这些建议来重写专家（团）定义，因此人工意见会真正进入下一版专家，而非仅作展示。</p>
        </div>
        <div className="flex justify-end mt-4">
          <button className="btn" onClick={() => setReviewHelp(false)}>知道了</button>
        </div>
      </Modal>
    </div>
  )
}

/** 会话证据弹窗：展示单个 opencode 会话的完整消息流（用户/助理/工具调用）。 */
function Highlight({ text, q }) {
  if (!q || !text) return <>{text}</>
  const lower = text.toLowerCase()
  const idx = lower.indexOf(q.toLowerCase())
  if (idx === -1) return <>{text}</>
  return <>{text.slice(0, idx)}<mark className="bg-accent/30 text-ink rounded-[2px] px-0.5">{text.slice(idx, idx + q.length)}</mark>{text.slice(idx + q.length)}</>
}

function SessionModal({ data, onClose }) {
  const [q, setQ] = useState('')
  const s = data?.session || {}
  const all = s.messages || []
  const ROLE = { user: { text: '用户', cls: 'badge-muted' }, assistant: { text: '助理', cls: 'badge-team' }, tool: { text: '工具', cls: 'badge-pass' } }
  const msgText = (m) => {
    const body = (m.parts || []).map(p => {
      if (p.type === 'text' || p.type === 'reasoning') return p.text || ''
      if (p.type === 'tool') return `${p.tool || ''} ${JSON.stringify(p.input || '')} ${p.error || ''}`
      return ''
    }).join(' ')
    return `${m.role || ''} ${m.agent || ''} ${body}`.toLowerCase()
  }
  const query = q.trim().toLowerCase()
  const messages = query ? all.filter(m => msgText(m).includes(query)) : all
  if (data?.error) {
    return (
      <Modal open title="会话证据" onClose={onClose} width="max-w-lg">
        <div className="text-sm text-warn bg-warn/10 border border-warn/30 rounded-default p-4">
          {data.error}
          <div className="text-xs text-muted mt-2">该会话过程数据未落盘（opencode 会话持久化偶发失败，属工具链问题，非专家本身行为缺失）。</div>
        </div>
        <div className="flex justify-end mt-4">
          <button className="btn" onClick={onClose}>关闭</button>
        </div>
      </Modal>
    )
  }
  return (
    <Modal open title={`会话证据 · ${(s.case || '').slice(-12)}`} onClose={onClose} width="max-w-3xl">
      <div className="text-xs text-muted mb-3 space-y-0.5">
        <div className="font-mono break-all">{s.session}</div>
        <div>agent: {s.agent || '—'} · model: {s.model || '—'} · 共 {all.length} 条消息{query ? ` · 命中 ${messages.length} 条` : ''}</div>
      </div>
      <div className="flex items-center gap-2 mb-3">
        <input className="input !py-1 !text-xs flex-1" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="搜索消息内容 / 工具名 / agent…" />
        {query && <button className="btn !py-1 !px-2 text-xs" onClick={() => setQ('')}>清除</button>}
      </div>
      <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
        {messages.length === 0 && <div className="text-center text-muted py-6">{query ? `没有匹配「${q}」的消息` : '会话无消息记录'}</div>}
        {messages.map(m => {
          const r = ROLE[m.role] || ROLE.tool
          return (
            <div key={m.id} className="border border-hairline rounded-default p-3">
              <div className="flex items-center gap-2 mb-1.5">
                <span className={`badge ${r.cls}`}>{r.text}</span>
                {m.agent ? <span className="text-xs text-muted">{m.agent}</span> : null}
                <span className="text-[10px] text-muted ml-auto">{new Date(m.time).toLocaleTimeString()}</span>
              </div>
              <div className="space-y-1.5 text-sm">
                {(m.parts || []).map((p, i) => {
                  if (p.type === 'text') {
                    return <div key={i} className="whitespace-pre-wrap break-words"><Highlight text={p.text} q={q} /></div>
                  }
                  if (p.type === 'tool') {
                    return (
                      <div key={i} className="bg-page rounded-default p-2 text-xs font-mono">
                        <span className="text-accent">⚙ <Highlight text={p.tool} q={q} /></span>
                        <span className={`ml-2 ${p.status === 'completed' ? 'text-accent' : p.status === 'error' ? 'text-danger' : 'text-muted'}`}>{p.status || ''}</span>
                        {p.input != null && <pre className="mt-1 text-[11px] whitespace-pre-wrap break-words max-h-40 overflow-y-auto text-muted">{JSON.stringify(p.input, null, 1).slice(0, 1200)}</pre>}
                        {p.error ? <div className="text-danger mt-1">{String(p.error).slice(0, 300)}</div> : null}
                      </div>
                    )
                  }
                  if (p.type === 'reasoning') {
                    return <div key={i} className="text-xs text-muted italic truncate">…<Highlight text={p.text} q={q} />…</div>
                  }
                  return null
                })}
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex justify-end mt-4">
        <button className="btn" onClick={onClose}>关闭</button>
      </div>
    </Modal>
  )
}

function MetricGroup({ title, metrics, tone, explain }) {
  const [helpOpen, setHelpOpen] = useState(false)
  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="font-semibold flex-1">{title}</h3>
        {explain && <HelpButton onClick={() => setHelpOpen(true)} title="指标说明" />}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {metrics.map(m => (
          <div key={m.key} className="border border-hairline rounded-default p-3">
            <div className="text-xs text-muted mb-1">{m.name}</div>
            <div className={`text-lg font-semibold ${tone === 'tech' ? 'text-ink' : 'text-accent'}`}>
              {m.display ?? '—'}
            </div>
            {m.value != null && typeof m.value === 'number' && m.unit === '%' && (
              <div className="h-1 bg-page rounded-full mt-2 overflow-hidden">
                <div className="h-full bg-accent" style={{ width: `${m.value * 100}%` }} />
              </div>
            )}
          </div>
        ))}
      </div>
      {explain && (
        <Modal open={helpOpen} title={explain.title} onClose={() => setHelpOpen(false)} width="max-w-2xl">
          <div className="space-y-3 text-sm">
            {explain.items.map(it => (
              <div key={it.name} className="border border-hairline rounded-default p-3">
                <div className="font-medium text-accent">{it.name}</div>
                <div className="text-xs text-muted mt-1 leading-relaxed">{it.desc}</div>
              </div>
            ))}
          </div>
          <div className="flex justify-end mt-4">
            <button className="btn" onClick={() => setHelpOpen(false)}>关闭</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function CaseRow({ c }) {
  const [open, setOpen] = useState(false)
  const [verdict, setVerdict] = useState('')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { runId } = useParams()

  const submitVerdict = async (v) => {
    setSubmitting(true)
    try {
      await api.createReview(runId, { case_id: c.case_id, verdict: v, comments: note, rating: v === 'pass' ? 5 : 1 })
      setVerdict(v); setNote('')
    } catch (e) { /* 忽略 */ }
    finally { setSubmitting(false) }
  }
  return (
    <div className="border border-hairline rounded-default mb-2">
      <button className="w-full flex items-center gap-3 p-3 text-left hover:bg-page/50" onClick={() => setOpen(!open)}>
        <span className={`badge ${c.pass ? 'badge-pass' : 'badge-fail'}`}>{c.pass
          ? <span className="flex items-center gap-1"><Check size={11} /> 通过</span>
          : <span className="flex items-center gap-1"><X size={11} /> 失败</span>}</span>
        <span className="font-mono text-xs text-muted">{c.case_id}</span>
        <span className="text-sm">{c.case_title}</span>
        <span className="text-xs text-muted">{c.case_type}</span>
        {c.needs_review === 1 && <span className="text-xs text-warn font-medium">待人工判定</span>}
        <span className="text-xs text-muted">score={c.score ?? '—'}</span>
        <span className="ml-auto text-xs text-muted">{c.error ? '异常' : `输出 ${c.output_length} 字符`}</span>
        <span className="text-xs text-muted">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 text-sm space-y-3">
          {c.error && <div className="text-danger text-xs">{c.error}</div>}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted">人工判定：</span>
            {verdict ? (
              <span className={verdict === 'pass' ? 'text-accent font-medium' : 'text-danger font-medium'}>
                {verdict === 'pass' ? '已判定通过' : '已判定失败'}
              </span>
            ) : (
              <span className="text-muted">{c.needs_review === 1 ? '待判定' : '未判定'}</span>
            )}
            <button className="btn !py-1 text-xs" disabled={submitting} onClick={() => submitVerdict('pass')}>通过</button>
            <button className="btn !py-1 text-xs" disabled={submitting} onClick={() => submitVerdict('fail')}>失败</button>
            <input className="input !py-1 text-xs flex-1" placeholder="备注（可选，将反哺优化建议）" value={note} onChange={e => setNote(e.target.value)} />
          </div>
          {c.assertions?.length > 0 && (
            <table className="table-base text-xs">
              <thead><tr><th>断言</th><th>结果</th><th>说明</th></tr></thead>
              <tbody>
                {c.assertions.map((a, i) => (
                  <tr key={i}>
                    <td className="font-mono">{a.type}</td>
                    <td>{a.pass ? <Check size={12} className="text-accent" /> : <X size={12} className="text-danger" />}</td>
                    <td className="text-muted break-all">{a.reason || a.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {c.output_preview && (
            <div>
              <div className="label">输出预览</div>
              <pre className="bg-page rounded-default p-3 text-xs whitespace-pre-wrap max-h-64 overflow-y-auto">{c.output_preview.slice(0, 4000)}</pre>
            </div>
          )}
          {c.session_ids?.length > 0 && (
            <div className="text-xs text-muted">会话: {c.session_ids.map(s => <code key={s} className="mr-2">{s}</code>)}</div>
          )}
          {c.process_metrics && (c.process_metrics.tool_calls?.length > 0 || c.process_metrics.delegation?.length > 0) && (
            <div>
              <div className="label">过程拆解（模块级证据）</div>
              {c.process_metrics.agents?.length > 0 && (
                <div className="text-xs text-muted mb-1">参与 agent：{c.process_metrics.agents.join('、')}</div>
              )}
              {c.process_metrics.delegation?.length > 0 && (
                <div className="text-xs mb-2">
                  <span className="text-muted">委派：</span>
                  {c.process_metrics.delegation.map((d, i) => (
                    <span key={i} className="badge badge-pass mr-1">{d.parent_agent} → {d.child_agent}</span>
                  ))}
                </div>
              )}
              {Object.keys(c.process_metrics.tool_summary || {}).length > 0 && (
                <table className="table-base text-xs">
                  <thead><tr><th>工具</th><th>调用</th><th>成功</th><th>失败</th></tr></thead>
                  <tbody>
                    {Object.entries(c.process_metrics.tool_summary).map(([tool, st]) => (
                      <tr key={tool}>
                        <td className="font-mono">{tool}</td>
                        <td>{st.total}</td>
                        <td className="text-accent">{st.success}</td>
                        <td className="text-danger">{st.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ReviewModal({ runId, objectId, onClose, onDone }) {
  const [task, setTask] = useState(null)
  const [rating, setRating] = useState(0)
  const [comments, setComments] = useState('')
  const [metrics, setMetrics] = useState([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getObject(objectId).then(o => {
      setTask(o)
      setMetrics((o.human_metrics || []).map(m => ({ name: m.name, criteria: m.criteria, score: '' })))
    }).catch(() => {})
  }, [objectId])

  const submit = async () => {
    setBusy(true)
    try {
      await api.createReview(runId, {
        rating,
        comments,
        metrics: metrics.map(m => ({ name: m.name, score: m.score === '' ? null : Number(m.score) })),
      })
      onDone(); onClose()
    } catch (e) { alert(e.message) } finally { setBusy(false) }
  }

  return (
    <Modal open title="人工评审" onClose={onClose}>
      <div className="grid gap-3 text-sm">
        <div>
          <label className="label">综合评分（1-5）</label>
          <div className="flex gap-1 text-2xl">
            {[1, 2, 3, 4, 5].map(n => (
              <button key={n} className={n <= rating ? 'text-accent' : 'text-hairline'} onClick={() => setRating(n)}>
                <Star size={22} className={n <= rating ? 'fill-accent' : ''} />
              </button>
            ))}
          </div>
        </div>
        {(task?.human_metrics || []).length > 0 && (
          <div>
            <label className="label">人类自定义指标逐项打分（专家意见：除内置指标外人类可提出指标）</label>
            {metrics.map((m, i) => (
              <div key={m.name} className="flex items-center gap-3 mb-2">
                <span className="w-40 text-xs">{m.name}</span>
                <input type="number" min={0} max={5} step={0.5} className="input w-20"
                  value={m.score} onChange={(e) => {
                    const next = [...metrics]; next[i] = { ...m, score: e.target.value }; setMetrics(next)
                  }} />
                <span className="text-xs text-muted">{m.criteria}</span>
              </div>
            ))}
          </div>
        )}
        <div>
          <label className="label">评审备注（对话框形式，AI 会读取并生成优化建议）</label>
          <textarea className="input" rows={4} value={comments} onChange={(e) => setComments(e.target.value)}
            placeholder="如：交付产物可用但说明文档不清晰；测试未覆盖边界情况…" />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn" onClick={onClose}>取消</button>
        <button className="btn btn-primary" disabled={busy || rating === 0} onClick={submit}>提交评审</button>
      </div>
    </Modal>
  )
}

