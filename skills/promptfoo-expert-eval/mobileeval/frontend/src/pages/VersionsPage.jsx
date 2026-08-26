import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { History, ArrowLeft, RotateCcw } from 'lucide-react'
import { api } from '../api'
import { Empty, Spinner } from '../components/ui'

/** 版本历史：每次优化前自动快照当前版本，滚动保留最近 10 版；支持一键切换回任意历史版本。 */
export default function VersionsPage() {
  const { objectId } = useParams()
  const [versions, setVersions] = useState(null)
  const [obj, setObj] = useState(null)
  const [error, setError] = useState('')
  const [restoring, setRestoring] = useState(null)   // 正在切换的版本号

  const load = () => {
    api.listVersions(objectId).then(setVersions).catch((e) => setError(e.message))
    api.getObject(objectId).then(setObj).catch(() => {})
  }
  useEffect(load, [objectId])

  const restore = async (version) => {
    if (!window.confirm(`确定把专家团切换到 v${version}？\n\n将用 v${version} 快照覆盖当前隔离工作区（若来源为全局专家也会同步全局），并更新当前版本号。切换前当前版本会自动快照，可随时切回。`)) return
    setRestoring(version)
    setError('')
    try {
      const r = await api.restoreVersion(objectId, version)
      setObj((o) => ({ ...o, current_version: r.current_version }))
      alert(`已切换到 v${r.current_version}（恢复 ${r.restored} 个 agent 定义）`)
      load()
    } catch (e) { setError(`切换失败：${e.message}`) }
    finally { setRestoring(null) }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Link to={`/objects/${objectId}`} className="btn !px-2 text-xs"><ArrowLeft size={13} />返回评测中心</Link>
          <h2 className="font-semibold flex items-center gap-1.5"><History size={16} className="text-accent" /> 版本历史</h2>
        </div>
        {obj && <div className="text-xs text-muted">当前版本 v{obj.current_version || 1} · {obj.name}</div>}
      </div>

      {error && <div className="card !border-danger/40 text-danger text-xs mb-3">{error}</div>}
      {versions === null ? <Empty text="加载中…" /> : versions.length === 0 ? (
        <Empty text="暂无版本记录。执行「迭代优化」时，优化前版本会自动快照保存到这里。" />
      ) : (
        <div className="card">
          <table className="table-base">
            <thead>
              <tr><th>版本</th><th>快照位置</th><th>得分</th><th>备注</th><th>时间</th><th className="text-right">操作</th></tr>
            </thead>
            <tbody>
              {versions.map((v) => {
                const isCurrent = obj && v.version === (obj.current_version || 1)
                return (
                  <tr key={v.id} className={isCurrent ? 'bg-accent/5' : ''}>
                    <td className="font-mono font-semibold">
                      v{v.version}
                      {isCurrent && <span className="badge badge-pass ml-2">当前</span>}
                    </td>
                    <td className="text-xs text-muted break-all">{v.path || '—'}</td>
                    <td>{v.score != null ? v.score.toFixed(2) : '—'}</td>
                    <td className="text-xs max-w-[280px] truncate" title={v.note}>{v.note || ''}</td>
                    <td className="text-xs text-muted">{v.created_at}</td>
                    <td className="text-right whitespace-nowrap">
                      {!isCurrent && (
                        <button className="btn !px-2 text-xs" disabled={restoring !== null}
                          onClick={() => restore(v.version)}>
                          {restoring === v.version ? <Spinner /> : <><RotateCcw size={12} />切换到此版本</>}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="text-xs text-muted mt-2">切换会先自动快照当前版本（保证可逆），再恢复所选历史版本的 agent 定义。</div>
        </div>
      )}
    </div>
  )
}
