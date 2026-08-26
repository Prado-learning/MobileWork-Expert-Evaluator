import React, { useMemo } from 'react'
import { Check, X, AlertTriangle, Minus, TrendingUp, TrendingDown, ArrowLeftRight } from 'lucide-react'
import { Modal, StatusBadge, fmtTime, fmtMs } from './ui'

/** case 状态：通过 / 失败 / 异常(链路问题待复核) / 无数据 */
function st(c) {
  if (!c) return 'none'
  if (c.pass === 1 || c.pass === true) return 'pass'
  if (c.error) return 'error'
  return 'fail'
}
const ST_META = {
  pass: { icon: <Check size={13} className="text-accent" />, text: '通过', cls: 'bg-accent/5 text-accent' },
  fail: { icon: <X size={13} className="text-danger" />, text: '失败', cls: 'bg-danger/5 text-danger' },
  error: { icon: <AlertTriangle size={13} className="text-warn" />, text: '异常', cls: 'bg-warn/10 text-warn' },
  none: { icon: <Minus size={13} className="text-muted/50" />, text: '无数据', cls: 'text-muted' },
}

/**
 * 历史运行详细对比弹窗：run 概览 + 差异摘要 + case×run 矩阵 + case 明细。
 * compare 来自 GET /api/runs/compare?ids=…：{ runs:[{id,status,score,…,cases:[case_results]}], matrix }
 */
export default function CompareModal({ compare, onClose, open = true }) {
  const runs = compare?.runs || []
  const allCases = useMemo(() => {
    const m = new Map()
    for (const r of runs) {
      for (const c of r.cases || []) {
        const k = c.case_id
        if (!m.has(k)) m.set(k, { case_id: k, case_title: c.case_title || '', runs: {} })
        m.get(k).runs[r.id] = c
      }
    }
    return [...m.values()]
  }, [runs])

  // 差异摘要：以第一次运行为基准，统计后续 run 相对基准的变化
  const diff = useMemo(() => {
    if (runs.length < 2) return null
    const base = runs[0]
    let regress = 0, improve = 0, samePass = 0, sameFail = 0, uncertain = 0
    for (const row of allCases) {
      const bs = st(row.runs[base.id])
      for (const r of runs.slice(1)) {
        const s = st(row.runs[r.id])
        if (s === 'none' || bs === 'none') { uncertain++; continue }
        if (bs === 'pass' && s === 'fail') regress++
        else if (bs === 'fail' && s === 'pass') improve++
        else if (s === 'pass') samePass++
        else if (s === 'fail') sameFail++
        else uncertain++
      }
    }
    return { regress, improve, samePass, sameFail, uncertain }
  }, [runs, allCases])

  return (
    <Modal open={open} title="运行对比" onClose={onClose} width="max-w-5xl">
      {/* run 概览 */}
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3 mb-4">
        {runs.map((r, i) => (
          <div key={r.id} className="border border-hairline rounded-default p-3 text-sm">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-semibold">#{r.id}</span>
              <StatusBadge status={r.status} />
              {i === 0 && runs.length > 1 && <span className="badge badge-muted">基准</span>}
            </div>
            <div className="flex items-baseline gap-2 my-1">
              <span className="text-2xl font-bold">{r.score != null ? r.score.toFixed(2) : '—'}</span>
              <span className="text-xs text-muted">通过 {r.pass_count}/{r.total_cases || 0}
                {r.fail_count ? ` · 失败 ${r.fail_count}` : ''}
                {r.error_count ? ` · 异常 ${r.error_count}` : ''}</span>
            </div>
            <div className="text-xs text-muted space-y-0.5">
              <div>模型：{r.model_name || r.model || '—'} {r.version ? `· v${r.version}` : ''}</div>
              <div>耗时 {fmtMs(r.duration_ms)} · {fmtTime(r.created_at)}</div>
            </div>
          </div>
        ))}
      </div>

      {/* 差异摘要 */}
      {diff && (
        <div className="flex flex-wrap gap-2 mb-4 text-xs">
          <span className="badge badge-fail"><TrendingDown size={12} /> 回归（通过→失败）<b>{diff.regress}</b></span>
          <span className="badge badge-pass"><TrendingUp size={12} /> 改进（失败→通过）<b>{diff.improve}</b></span>
          <span className="badge badge-pass"><Check size={12} /> 一致通过 <b>{diff.samePass}</b></span>
          <span className="badge badge-fail"><X size={12} /> 一致失败 <b>{diff.sameFail}</b></span>
          <span className="badge badge-running"><AlertTriangle size={12} /> 异常/无数据 <b>{diff.uncertain}</b></span>
        </div>
      )}

      {/* case×run 矩阵 */}
      <div className="overflow-x-auto border border-hairline rounded-default mb-4">
        <table className="table-base text-xs">
          <thead>
            <tr>
              <th className="w-8"></th>
              <th>用例</th>
              {runs.map(r => <th key={r.id} className="text-center">#{r.id}</th>)}
            </tr>
          </thead>
          <tbody>
            {allCases.map((row, idx) => (
              <tr key={row.case_id} className={idx % 2 ? 'bg-page/60' : ''}>
                <td className="text-muted">{idx + 1}</td>
                <td className="max-w-[220px]">
                  <code className="font-mono text-xs">{row.case_id}</code>
                  {row.case_title ? <div className="truncate text-muted">{row.case_title}</div> : null}
                </td>
                {runs.map(r => {
                  const c = row.runs[r.id]
                  const s = st(c)
                  const m = ST_META[s]
                  return (
                    <td key={r.id} className="text-center">
                      <span className="inline-flex flex-col items-center gap-0.5">
                        <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 ${s === 'none' ? m.cls : m.cls}`}>
                          {m.icon}{m.text}
                        </span>
                        {c && c.score != null && <span className="text-muted">{c.score.toFixed(2)}</span>}
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
            {allCases.length === 0 && <tr><td colSpan={runs.length + 2} className="text-center text-muted py-6">暂无用例数据</td></tr>}
          </tbody>
        </table>
      </div>

      {/* 用例明细：各 run 的 score 与 error */}
      <div>
        <div className="font-semibold text-sm mb-2 flex items-center gap-2"><ArrowLeftRight size={14} className="text-accent" /> 用例明细</div>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {allCases.map(row => (
            <div key={row.case_id} className="border border-hairline rounded-default p-2.5 text-xs">
              <div className="flex items-center gap-2 mb-1">
                <code className="font-mono">{row.case_id}</code>
                <span className="font-medium truncate">{row.case_title || '—'}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {runs.map(r => {
                  const c = row.runs[r.id]
                  const s = st(c)
                  const m = ST_META[s]
                  return (
                    <div key={r.id} className={`rounded-default px-2 py-1 border border-hairline ${s === 'pass' ? 'bg-accent/5' : s === 'fail' ? 'bg-danger/5' : s === 'error' ? 'bg-warn/10' : ''}`}>
                      <span className="text-muted">#{r.id}</span> {m.icon}
                      <span className="ml-1">{c && c.score != null ? c.score.toFixed(2) : '—'}</span>
                      {s === 'error' && c?.error ? (
                        <div className="mt-0.5 text-warn max-w-[420px] truncate">{String(c.error).slice(0, 90)}</div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
          {allCases.length === 0 && <div className="text-center text-muted py-4">暂无用例数据</div>}
        </div>
      </div>

      <div className="flex justify-end mt-4">
        <button className="btn" onClick={onClose}><X size={13} />关闭</button>
      </div>
    </Modal>
  )
}
