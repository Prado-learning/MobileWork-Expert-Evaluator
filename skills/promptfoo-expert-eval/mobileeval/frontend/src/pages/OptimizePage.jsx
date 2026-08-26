import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Wand2, ArrowLeft, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { Modal, Spinner, Empty, StatusBadge } from '../components/ui'

/** 迭代优化：选基线评测 → 看建议 → 确认优化 → 保存旧版 + 写回全局 → 返回对比入口。 */
export default function OptimizePage() {
  const { objectId } = useParams()
  const [runs, setRuns] = useState(null)
  const [obj, setObj] = useState(null)
  const [versions, setVersions] = useState([])
  const [optims, setOptims] = useState([])
  const [selectedRun, setSelectedRun] = useState(null)
  const [suggestion, setSuggestion] = useState('')
  const [loadingSug, setLoadingSug] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listRuns({ object_id: objectId }).then(setRuns).catch((e) => setError(e.message))
    api.getObject(objectId).then(setObj).catch(() => {})
    api.listVersions(objectId).then(setVersions).catch(() => {})
    api.listOptimizations(objectId).then(setOptims).catch(() => {})
  }, [objectId])

  const loadSuggestions = async (run) => {
    setSelectedRun(run)
    setResult(null)
    setError('')
    setLoadingSug(true)
    setSuggestion('')
    try {
      const list = await api.listSuggestions(run.id)
      setSuggestion(list[0]?.content || '（该评测暂无优化建议，可到报告页「生成建议」）')
    } catch (e) { setSuggestion(`读取建议失败：${e.message}`) }
    finally { setLoadingSug(false) }
  }

  const confirmOptimize = async () => {
    if (!selectedRun) return
    setOptimizing(true); setError(''); setResult(null)
    try {
      const r = await api.optimizeExpert(objectId, { run_id: selectedRun.id })
      setResult(r)
      api.listVersions(objectId).then(setVersions).catch(() => {})
      api.listOptimizations(objectId).then(setOptims).catch(() => {})
    } catch (e) { setError(`优化失败：${e.message}`) }
    finally { setOptimizing(false) }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Link to={`/objects/${objectId}`} className="btn !px-2 text-xs"><ArrowLeft size={13} />返回评测中心</Link>
          <h2 className="font-semibold flex items-center gap-1.5"><Wand2 size={16} className="text-accent" /> 迭代优化</h2>
        </div>
        {obj && <div className="text-xs text-muted">{obj.name} · 当前 v{obj.current_version || 1}</div>}
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* 左：基线评测 */}
        <div className="card col-span-1">
          <h3 className="font-semibold text-sm mb-2">1. 选择基线评测</h3>
          {runs === null ? <Empty text="加载中…" /> : runs.length === 0 ? (
            <Empty text="还没有评测，先到评测中心发起一次评测" />
          ) : (
            <div className="space-y-1.5 max-h-72 overflow-y-auto">
              {runs.map((r) => (
                <button key={r.id} onClick={() => loadSuggestions(r)}
                  className={`w-full text-left border rounded-default p-2 text-xs ${selectedRun?.id === r.id ? 'border-accent bg-accent/5' : 'border-hairline hover:border-accent/40'}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono">run #{r.id}</span>
                    <StatusBadge status={r.status} />
                  </div>
                  <div className="text-muted mt-1">得分 {r.score != null ? r.score.toFixed(2) : '—'} · {r.pass_count}/{r.fail_count} · {r.created_at}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 中：优化建议 */}
        <div className="card col-span-1">
          <h3 className="font-semibold text-sm mb-2">2. 优化建议</h3>
          {loadingSug ? <div className="flex items-center gap-2 text-xs text-muted"><Spinner /> 生成建议中…</div>
            : suggestion ? <div className="text-xs whitespace-pre-wrap max-h-72 overflow-y-auto text-muted">{suggestion}</div>
            : <Empty text="选择左侧基线评测后，读取该评测的优化建议；暂无建议时可到报告页「生成建议」" />}
        </div>

        {/* 右：执行与结果 */}
        <div className="card col-span-1">
          <h3 className="font-semibold text-sm mb-2">3. 执行优化</h3>
          <div className="text-xs text-muted space-y-1 mb-3">
            <p>· 优化前自动快照当前版本（版本管理，保留最近 10 版）</p>
            <p>· 逐个 agent 基于建议重写定义，<b className="text-ink">直接写回 OpenWork 全局版本</b>（当前使用版本立即生效）+ 隔离工作区副本</p>
            <p>· 优化后可发起回归评测，再到对比页查看差异</p>
          </div>
          <button className="btn btn-primary w-full justify-center" disabled={!selectedRun || optimizing} onClick={confirmOptimize}>
            {optimizing ? <Spinner light /> : <><Wand2 size={14} /> 确认并优化（v{obj?.current_version || 1} → v{(obj?.current_version || 1) + 1}）</>}
          </button>
          {error && <div className="text-danger text-xs mt-2">{error}</div>}
          {result && (
            <div className="mt-3 border border-accent/40 bg-accent/5 rounded-default p-3 text-xs">
              <div className="font-semibold mb-1 text-accent">优化完成</div>
              <p>v{result.version_from} → v{result.version_to}，已保存旧版快照</p>
              <p className="text-muted">优化的 agent：{result.optimized?.join('、')}</p>
              <Link to={`/compare/${objectId}?base=${result.baseline_run_id}`} className="text-accent font-medium inline-block mt-2">
                查看对比报告 →
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* 历史优化记录 */}
      {optims.length > 0 && (
        <div className="card mt-4">
          <h3 className="font-semibold text-sm mb-2 flex items-center gap-1.5"><RefreshCw size={14} className="text-accent" /> 历史优化</h3>
          <table className="table-base">
            <thead><tr><th>#</th><th>版本</th><th>基线评测</th><th>优化后评测</th><th>对比</th><th>时间</th></tr></thead>
            <tbody>
              {optims.map((o) => (
                <tr key={o.id}>
                  <td className="font-mono">{o.id}</td>
                  <td>v{o.version_from} → v{o.version_to}</td>
                  <td className="font-mono">run #{o.baseline_run_id}</td>
                  <td className="font-mono">{o.optimized_run_id ? `run #${o.optimized_run_id}` : '—'}</td>
                  <td>
                    {o.optimized_run_id
                      ? <Link to={`/compare/${objectId}?base=${o.baseline_run_id}&opt=${o.optimized_run_id}`} className="text-accent text-xs">对比</Link>
                      : <Link to={`/compare/${objectId}?base=${o.baseline_run_id}`} className="text-muted text-xs">选优化后评测</Link>}
                  </td>
                  <td className="text-xs text-muted">{o.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
