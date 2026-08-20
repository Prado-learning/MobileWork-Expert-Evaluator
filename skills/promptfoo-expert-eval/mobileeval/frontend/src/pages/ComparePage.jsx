import React, { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, GitCompare } from 'lucide-react'
import { api } from '../api'
import { Empty, StatusBadge } from '../components/ui'

const SCORE_OK = (v) => v != null && v !== '' && v !== '—'

/** 优化前后对比报告：分数 / 逐 case 通过 / 建议。 */
export default function ComparePage() {
  const { objectId } = useParams()
  const [params] = useSearchParams()
  const baseId = Number(params.get('base') || 0)
  const [optId, setOptId] = useState(Number(params.get('opt') || 0))
  const [data, setData] = useState(null)
  const [runs, setRuns] = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [error, setError] = useState('')

  const load = async (opt) => {
    if (!baseId || !opt) return
    setError('')
    try {
      const d = await api.compareRunsPair(baseId, opt)
      setData(d)
    } catch (e) { setError(e.message) }
  }

  useEffect(() => {
    api.listRuns({ object_id: objectId }).then(setRuns).catch(() => {})
    if (baseId) api.listSuggestions(baseId).then(setSuggestions).catch(() => {})
  }, [objectId, baseId])

  useEffect(() => { if (optId) load(optId) }, [optId]) // eslint-disable-line

  if (!baseId) return <Empty text="缺少 base 参数（基线评测 id）" />
  const candRuns = runs.filter((r) => r.id !== baseId)

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Link to={`/objects/${objectId}/optimize`} className="btn !px-2 !py-1 text-xs"><ArrowLeft size={13} /> 返回优化</Link>
          <h2 className="font-semibold flex items-center gap-1.5"><GitCompare size={16} className="text-accent" /> 优化对比报告</h2>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted">优化后评测：</span>
          <select className="input !w-auto !py-1" value={optId || ''} onChange={(e) => setOptId(Number(e.target.value))}>
            <option value="">— 选择 —</option>
            {candRuns.map((r) => <option key={r.id} value={r.id}>run #{r.id}（{r.created_at}）</option>)}
          </select>
        </div>
      </div>

      {error && <div className="text-danger text-xs mb-3">{error}</div>}
      {!data ? <Empty text={optId ? '加载中…' : '选择优化后的评测（回归测试）以对比'} /> : (
        <>
          {/* 总览 */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            {[['基线', data.base], ['优化后', data.opt]].map(([label, r]) => (
              <div key={label} className="card">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold text-sm">{label}（run #{r.id}）</h3>
                  <StatusBadge status={r.status} />
                </div>
                <div className="grid grid-cols-4 gap-2 text-center">
                  <div>
                    <div className="text-xl font-semibold">{SCORE_OK(r.score) ? r.score.toFixed(2) : '—'}</div>
                    <div className="text-[11px] text-muted">得分</div>
                  </div>
                  <div><div className="text-xl font-semibold text-pass">{r.pass}</div><div className="text-[11px] text-muted">通过</div></div>
                  <div><div className="text-xl font-semibold text-fail">{r.fail}</div><div className="text-[11px] text-muted">失败</div></div>
                  <div><div className="text-xl font-semibold text-warn">{r.error}</div><div className="text-[11px] text-muted">异常</div></div>
                </div>
              </div>
            ))}
          </div>

          {/* 逐 case 对比 */}
          <div className="card mb-4">
            <h3 className="font-semibold text-sm mb-2">逐 case 对比</h3>
            <table className="table-base">
              <thead><tr><th>case</th><th>标题</th><th>基线</th><th>优化后</th><th>变化</th></tr></thead>
              <tbody>
                {data.cases.map((c) => {
                  const b = c.base, o = c.opt
                  const change = b.pass !== o.pass
                    ? (o.pass ? '修复 ✓' : '回归 ✗')
                    : (SCORE_OK(o.score) && SCORE_OK(b.score) && o.score !== b.score ? `分 ${b.score?.toFixed(2)}→${o.score?.toFixed(2)}` : '—')
                  return (
                    <tr key={c.case_id}>
                      <td className="font-mono">{c.case_id}</td>
                      <td className="text-xs">{c.title}</td>
                      <td><CaseBadge pass={b.pass} error={b.error} /></td>
                      <td><CaseBadge pass={o.pass} error={o.error} /></td>
                      <td className={`text-xs font-medium ${change.startsWith('修复') ? 'text-pass' : change.startsWith('回归') ? 'text-fail' : 'text-muted'}`}>{change}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* 优化建议依据 */}
          {suggestions.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-sm mb-2">优化依据（基线评测建议）</h3>
              <div className="text-xs text-muted whitespace-pre-wrap">{suggestions[0].content}</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function CaseBadge({ pass, error }) {
  if (error) return <span className="text-[11px] text-warn">异常</span>
  return <span className={`text-[11px] font-medium ${pass ? 'text-pass' : 'text-fail'}`}>{pass ? '通过' : '失败'}</span>
}
