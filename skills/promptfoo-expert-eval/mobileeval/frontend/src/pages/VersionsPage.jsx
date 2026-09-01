import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { History, ArrowLeft, RotateCcw, GitCompareArrows } from 'lucide-react'
import { api } from '../api'
import { Empty, Spinner, Modal } from '../components/ui'

const DIFF_LINE_CLS = {
  add: 'bg-success/10 text-success',
  del: 'bg-danger/10 text-danger',
  hunk: 'text-accent',
  meta: 'text-muted italic',
  ctx: 'text-ink/80',
}
const DIFF_STATUS_TEXT = { changed: '修改', added: '新增', removed: '删除' }

/** 两版专家定义 diff 弹窗 */
function DiffModal({ diff, onClose }) {
  if (!diff) return null
  return (
    <Modal open title={`版本差异：${diff.a} → ${diff.b}`} onClose={onClose} width="max-w-3xl">
      {diff.files.length === 0 ? (
        <Empty text={`两版定义完全一致（${diff.same_count} 个文件无变化）`} />
      ) : (
        <div className="space-y-3 max-h-[65vh] overflow-y-auto">
          <div className="text-xs text-muted">
            {diff.files.length} 个文件有变化{diff.same_count ? `，${diff.same_count} 个文件无变化` : ''}
          </div>
          {diff.files.map((f) => (
            <div key={f.path} className="border border-hairline rounded-default overflow-hidden">
              <div className="flex items-center gap-2 px-2.5 py-1.5 bg-page/60 text-xs border-b border-hairline">
                <code className="font-semibold">{f.path}</code>
                <span className="text-muted">{DIFF_STATUS_TEXT[f.status] || f.status}</span>
                <span className="ml-auto text-success">+{f.added}</span>
                <span className="text-danger">-{f.removed}</span>
              </div>
              <pre className="text-[11px] leading-4 font-mono p-2 overflow-x-auto">
                {f.lines.map((ln, i) => (
                  <div key={i} className={`whitespace-pre ${DIFF_LINE_CLS[ln.kind] || ''}`}>{ln.text || ' '}</div>
                ))}
              </pre>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

/** 版本历史：每次优化前自动快照当前版本，滚动保留最近 10 版；支持一键切换回任意历史版本。 */
export default function VersionsPage() {
  const { objectId } = useParams()
  const [versions, setVersions] = useState(null)
  const [obj, setObj] = useState(null)
  const [error, setError] = useState('')
  const [restoring, setRestoring] = useState(null)   // 正在切换的版本号
  const [diffA, setDiffA] = useState('')             // diff 左版本（默认最新快照）
  const [diffB, setDiffB] = useState('current')      // diff 右版本（默认当前工作区）
  const [diff, setDiff] = useState(null)             // diff 弹窗数据
  const [diffBusy, setDiffBusy] = useState(false)
  const [diffError, setDiffError] = useState('')

  const load = () => {
    api.listVersions(objectId)
      .then((vs) => { setVersions(vs); if (!diffA && vs.length) setDiffA(`v${vs[0].version}`) })
      .catch((e) => setError(e.message))
    api.getObject(objectId).then(setObj).catch(() => {})
  }
  useEffect(load, [objectId])

  // 查看两版专家定义差异（优化闭环：看清 optimize-expert 到底改了什么）
  const showDiff = async () => {
    if (!diffA || !diffB) return
    if (diffA === diffB) { setDiffError('请选择两个不同的版本'); return }
    setDiffBusy(true); setDiffError('')
    try { setDiff(await api.diffVersions(objectId, diffA.replace(/^v/, ''), diffB.replace(/^v/, ''))) }
    catch (e) { setDiffError(e.message) }
    finally { setDiffBusy(false) }
  }

  const restore = async (version) => {
    if (!window.confirm(`确定把${obj?.kind === 'team' ? '专家团' : '专家'}切换到 v${version}？\n\n将用 v${version} 快照覆盖当前隔离工作区（若来源为全局专家也会同步全局），并更新当前版本号。切换前当前版本会自动快照，可随时切回。`)) return
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
          <Link to={`/objects/${objectId}`} className="btn !px-2 !py-1 text-xs"><ArrowLeft size={13} /> 返回评测中心</Link>
          <h2 className="font-semibold flex items-center gap-1.5"><History size={16} className="text-accent" /> 版本历史</h2>
        </div>
        {obj && <div className="text-xs text-muted">当前版本 v{obj.current_version || 1} · {obj.name}</div>}
      </div>

      {error && <div className="card !border-danger/40 text-danger text-xs mb-3">{error}</div>}
      {versions === null ? <Empty text="加载中…" /> : versions.length === 0 ? (
        <Empty text="暂无版本记录。执行「迭代优化」时，优化前版本会自动快照保存到这里。" />
      ) : (
        <>
        {/* 版本 diff：看两版专家定义改了什么（优化闭环） */}
        <div className="card mb-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <GitCompareArrows size={15} className="text-accent" />
            <span className="font-semibold mr-1">版本差异</span>
            <select className="input !w-auto !py-1 text-xs" value={diffA} onChange={(e) => setDiffA(e.target.value)}>
              {versions.map((v) => <option key={v.version} value={`v${v.version}`}>v{v.version}（快照）</option>)}
              <option value="current">当前工作区</option>
            </select>
            <span className="text-muted text-xs">→</span>
            <select className="input !w-auto !py-1 text-xs" value={diffB} onChange={(e) => setDiffB(e.target.value)}>
              <option value="current">当前工作区</option>
              {versions.map((v) => <option key={v.version} value={`v${v.version}`}>v{v.version}（快照）</option>)}
            </select>
            <button className="btn btn-primary !py-1 text-xs" disabled={diffBusy} onClick={showDiff}>
              {diffBusy ? <Spinner light /> : '查看差异'}
            </button>
            {diffError && <span className="text-danger text-xs">{diffError}</span>}
          </div>
        </div>
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
                        <button className="btn !px-2 !py-1 text-xs" disabled={restoring !== null}
                          onClick={() => restore(v.version)}>
                          {restoring === v.version ? <Spinner /> : <RotateCcw size={12} className="inline mr-1" />}切换到此版本
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
        </>
      )}
      <DiffModal diff={diff} onClose={() => setDiff(null)} />
    </div>
  )
}
