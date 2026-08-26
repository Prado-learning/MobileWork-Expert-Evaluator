import React, { useEffect, useState, useCallback } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { Users, ChevronDown, Crown, Play, Trash2, ArrowLeft, History, FlaskConical, Wand2, GitCompare, X } from 'lucide-react'
import { api } from '../api'
import { KindBadge, StatusBadge, Empty, fmtTime, fmtMs, Modal, Spinner } from '../components/ui'
import CaseManager from '../components/CaseManager'
import CompareModal from '../components/CompareModal'

export default function ObjectDetailPage() {
  const { objectId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [obj, setObj] = useState(null)
  const [runs, setRuns] = useState([])
  const [error, setError] = useState('')
  const [selected, setSelected] = useState([])
  const [compare, setCompare] = useState(null)
  const [compareOpen, setCompareOpen] = useState(false)   // 历史对比详细弹窗
  const [polling, setPolling] = useState(false)
  const [agents, setAgents] = useState(null)          // 专家团成员信息（null=未加载）
  const [teamOpen, setTeamOpen] = useState(true)      // 专家团信息卡片折叠
  const [agentOpen, setAgentOpen] = useState({})      // 成员展开状态（按成员 id）
  const [showRun, setShowRun] = useState(false)       // 发起评测弹窗
  const [runForm, setRunForm] = useState({ model_id: '', version: '', agent_on: 1, repeat: 1, concurrency: 4, experiment_id: '', variant: '' })
  const [experiments, setExperiments] = useState([])
  const [models, setModels] = useState([])           // 全局评测模型
  const [versions, setVersions] = useState([])       // 版本历史（发起评测时选择专家版本）
  const [launching, setLaunching] = useState(false)
  const [tab, setTab] = useState(() => {
    const t = searchParams.get('tab')
    return t === 'cases' || t === 'results' ? t : 'info'
  })   // info=基础信息 | cases=评测用例 | results=评测结果

  const load = useCallback(async () => {
    try {
      setObj(await api.getObject(objectId))
      const rs = await api.listRuns({ object_id: objectId })
      setRuns(rs)
      setError('')
      setPolling(rs.some(r => r.status === 'running' || r.status === 'pending'))
    } catch (e) { setError(e.message) }
  }, [objectId])

  useEffect(() => { load() }, [load])
  useEffect(() => { api.listExperiments(objectId).then(setExperiments).catch(() => {}) }, [objectId])
  // 全局评测模型（发起评测时选择）
  useEffect(() => {
    api.listModels()
      .then((ms) => {
        setModels(ms)
        setRunForm((f) => ({ ...f, model_id: f.model_id || (ms.find(m => m.is_default === 1)?.id || ms[0]?.id || '') }))
      })
      .catch(() => {})
  }, [])
  // 专家团信息：对象加载成功后惰性拉取（成员来自工作区 .opencode，读一次即可）
  useEffect(() => {
    if (obj && agents === null) {
      api.listObjectAgents(objectId)
        .then((d) => setAgents(d))
        .catch(() => setAgents({ agents: [] }))
    }
  }, [obj, agents, objectId])
  useEffect(() => {
    if (!polling) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [polling, load])

  const openRunModal = () => {
    const def = models.find(m => m.is_default === 1) || models[0]
    setRunForm({ model_id: def?.id || '', version: `v${obj.current_version || 1}`, agent_on: 1, repeat: 1, concurrency: 4, experiment_id: '', variant: '' })
    // 加载版本历史供「专家版本」下拉选择
    api.listVersions(objectId).then(setVersions).catch(() => setVersions([]))
    setShowRun(true)
  }

  const launch = async () => {
    if (!runs.length && !window.confirm('该对象可能还没有审核通过的用例，评测会直接失败。确认发起？')) return
    setLaunching(true); setError('')
    try {
      await api.createObjectRun(objectId, runForm)
      setShowRun(false); load()
    } catch (e) { setError(`发起失败：${e.message}`) }
    finally { setLaunching(false) }
  }

  const doCompare = async () => {
    if (selected.length < 2) return
    setCompare(await api.compareRuns(selected))
    setCompareOpen(true)
  }

  const chartData = runs.slice().reverse().map((r) => ({
    name: `#${r.id}`, score: r.score ?? 0, pass: r.pass_count ?? 0, fail: r.fail_count ?? 0,
  }))

  if (!obj) return <Empty text="加载中…" />
  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link to="/objects" className="btn !px-2.5" aria-label="返回"><ArrowLeft size={14} /></Link>
        <h1 className="text-xl font-semibold truncate">{obj.name}</h1>
        {obj.current_version ? <span className="text-xs text-muted">v{obj.current_version}</span> : null}
        <div className="ml-auto flex-none">
          <button className="btn btn-primary" onClick={openRunModal}><Play size={13} />发起评测</button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <Link to={`/objects/${obj.id}/versions`} className="btn text-xs"><History size={13} />历史版本</Link>
        <Link to={`/objects/${obj.id}/experiments`} className="btn text-xs"><FlaskConical size={13} />对照实验</Link>
        <Link to={`/objects/${obj.id}/optimize`} className="btn text-xs"><Wand2 size={13} />迭代优化</Link>
      </div>
      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}

      {/* Tab 栏 */}
      <div className="flex gap-1 border-b border-hairline mb-4">
        {[['info', '基础信息'], ['cases', '评测用例'], ['results', '评测结果']].map(([k, label]) => (
          <button key={k} className={`px-3.5 py-2 text-sm border-b-2 -mb-px ${tab === k ? 'border-accent text-ink font-medium' : 'border-transparent text-muted hover:text-ink'}`}
            onClick={() => { setTab(k); setSearchParams(k === 'info' ? {} : { tab: k }, { replace: true }) }}>{label}</button>
        ))}
      </div>

      {tab === 'info' && (
        <>
          <div className="card mb-4 grid md:grid-cols-4 gap-3 text-sm">
            <div><div className="label">{obj.kind === 'team' ? '团长' : '专家'}</div><code>{obj.agent_name}</code></div>
            <div>
              <div className="label">评测模型</div>
              <Link to="/models" className="text-accent text-xs">
                {models.find(m => m.is_default === 1)?.name || (models[0] ? models[0].name : '未配置')}
              </Link>
            </div>
            <div><div className="label">来源</div>{obj.source === 'uploaded' ? '已上传' : '本机'}</div>
            <div><div className="label">工作区</div><code className="text-xs break-all">{obj.workspace_dir || '—'}</code></div>
          </div>

          {/* 专家团信息：可折叠卡片，点标题整行展开/收起；成员项点名称行展开详情 */}
          <div className="card mb-4">
            <div className="flex items-center gap-2 cursor-pointer select-none" onClick={() => setTeamOpen(!teamOpen)}>
              <Users size={15} className="text-muted shrink-0" />
              <h3 className="font-semibold flex-1">成员{agents?.agents?.length ? `（${agents.agents.length}）` : ''}</h3>
              <ChevronDown size={15} className={`text-muted transition-transform ${teamOpen ? '' : '-rotate-90'}`} />
            </div>
            {teamOpen && (
              <div className="mt-3">
                {agents === null ? <div className="text-xs text-muted flex items-center gap-2"><Spinner /> 加载中…</div>
                  : !agents.agents?.length ? (
                    <div className="text-xs text-muted">{agents.note || '未解析到成员定义'}</div>
                  ) : (
                    <div className="space-y-1.5">
                      {agents.agents.map((a) => {
                        const isPrimary = a.mode === 'primary'
                        const open = agentOpen[a.id]
                        return (
                          <div key={a.id} className={`border border-hairline rounded-default ${open ? '' : 'hover:border-accent/40'}`}>
                            <div className="flex items-center gap-2 px-2.5 py-1.5 cursor-pointer select-none" onClick={() => setAgentOpen((s) => ({ ...s, [a.id]: !s[a.id] }))}>
                              {isPrimary ? <Crown size={13} className="text-warn shrink-0" /> : <ChevronDown size={12} className={`text-muted shrink-0 transition-transform ${open ? '' : '-rotate-90'}`} />}
                              <code className="text-xs font-semibold">{a.id}</code>
                              {isPrimary && <span className="text-[10px] text-warn border border-warn/40 rounded-full px-1.5 py-px">团长</span>}
                              <span className="text-xs text-muted truncate flex-1">{a.role || a.description || '—'}</span>
                              {a.steps != null && <span className="text-[10px] text-muted shrink-0">{a.steps} 步</span>}
                              <ChevronDown size={12} className={`text-muted shrink-0 transition-transform ${open ? '' : '-rotate-90'} ${isPrimary ? 'invisible' : ''}`} />
                            </div>
                            {open && (
                              <div className="px-2.5 pb-2 pt-1 border-t border-hairline text-xs space-y-1.5">
                                {(a.role || a.description) && (
                                  <div><span className="text-muted">职责：</span><span className="break-words">{a.role || a.description}</span></div>
                                )}
                                {a.description && a.role && a.description !== a.role && (
                                  <div><span className="text-muted">描述：</span><span className="break-words">{a.description}</span></div>
                                )}
                                <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
                                  <span>bash <code className="text-ink">{a.bash || '—'}</code></span>
                                  <span>edit <code className="text-ink">{a.edit ?? '—'}</code></span>
                                  <span>webfetch <code className="text-ink">{a.webfetch ?? '—'}</code></span>
                                  <span>external_directory <code className="text-ink">{a.external || '—'}</code></span>
                                </div>
                                {a.task_allow?.length > 0 && (
                                  <div><span className="text-muted">可委派：</span>{a.task_allow.map((t) => <code key={t} className="mr-1.5 text-ink">{t}</code>)}</div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
              </div>
            )}
          </div>
        </>
      )}

      {tab === 'cases' && (
        <div className="mb-4">
          <CaseManager objectId={Number(objectId)} />
        </div>
      )}

      {tab === 'results' && (
        <>
          <div className="grid md:grid-cols-2 gap-4 mb-4">
            <div className="card">
              <h3 className="font-semibold mb-2">分数趋势</h3>
              {runs.length === 0 ? <Empty text="暂无运行" /> : (
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={chartData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e6eb" />
                    <XAxis dataKey="name" fontSize={11} />
                    <YAxis domain={[0, 1]} fontSize={11} />
                    <Tooltip />
                    <Line type="monotone" dataKey="score" stroke="#1890ff" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="card">
              <h3 className="font-semibold mb-2">历史对比</h3>
              {runs.length === 0 ? <Empty text="暂无运行" /> : (
                <>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {runs.map(r => (
                      <label key={r.id} className="flex items-center gap-1.5 text-xs cursor-pointer">
                        <input type="checkbox" checked={selected.includes(r.id)}
                          onChange={(e) => setSelected(e.target.checked ? [...selected, r.id] : selected.filter(x => x !== r.id))} />
                        #{r.id} {r.score != null ? r.score.toFixed(2) : r.status}
                        <span className="text-muted">{r.version}·{r.agent_on === 0 ? '无专家' : '专家团'}</span>
                      </label>
                    ))}
                  </div>
                  <button className="btn btn-primary" disabled={selected.length < 2} onClick={doCompare}><GitCompare size={13} />对比</button>
                </>
              )}
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-3">评测记录（{runs.length}）</h3>
            {runs.length === 0 ? <Empty text="点击「发起评测」开始" /> : (
              <div className="overflow-x-auto">
                <table className="table-base min-w-[960px]">
                  <thead>
                    <tr><th>#</th><th>状态</th><th>分数</th><th>进度</th><th>版本</th><th>模型</th><th>模式</th><th>次数</th><th>耗时</th><th>时间</th><th className="sticky right-0 bg-surface z-10 border-l border-hairline">操作</th></tr>
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
                          <td className="text-xs">{r.version || '—'}</td>
                          <td className="text-xs">{r.model_name || r.model || '—'}</td>
                          <td className="text-xs">{r.agent_on === 0 ? <span className="text-warn">无专家</span> : '专家团'}</td>
                          <td className="text-xs">{r.repeat || 1}</td>
                          <td>{fmtMs(r.duration_ms)}</td>
                          <td className="text-xs text-muted">{fmtTime(r.created_at)}</td>
                          <td className="text-right whitespace-nowrap sticky right-0 bg-surface z-10 border-l border-hairline">
                            <Link to={`/runs/${r.id}`} className="text-accent text-xs mr-2">报告</Link>
                            <button className="text-danger text-xs" onClick={async () => { await api.deleteRun(r.id); load() }}><Trash2 size={11} className="inline mr-0.5" />删除</button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* 发起评测弹窗 */}
      <Modal open={showRun} title="发起评测" onClose={() => setShowRun(false)}>
        <div className="grid gap-3 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">专家版本</label>
              <select className="input" value={runForm.version || `v${obj.current_version || 1}`}
                onChange={(e) => setRunForm({ ...runForm, version: e.target.value })}>
                {Array.from(new Set([obj.current_version || 1, ...versions.map(v => v.version)]))
                  .sort((a, b) => b - a).map(vn => (
                    <option key={vn} value={`v${vn}`}>v{vn}{vn === (obj.current_version || 1) ? '（当前）' : '（历史）'}</option>
                  ))}
              </select>
            </div>
            <div>
              <label className="label">评测模型</label>
              {models.length === 0 ? (
                <Link to="/models" className="text-accent text-xs">尚未配置模型</Link>
              ) : (
                <select className="input" value={runForm.model_id}
                  onChange={(e) => setRunForm({ ...runForm, model_id: e.target.value })}>
                  {models.map(m => (
                    <option key={m.id} value={m.id}>{m.name}{m.is_default === 1 ? '（默认）' : ''}</option>
                  ))}
                </select>
              )}
            </div>
            <div>
              <label className="label">重复次数</label>
              <input type="number" min={1} className="input" value={runForm.repeat} onChange={(e) => setRunForm({ ...runForm, repeat: e.target.value })} />
            </div>
            <div>
              <label className="label">并发数</label>
              <input type="number" min={1} max={100} className="input" value={runForm.concurrency}
                onChange={(e) => setRunForm({ ...runForm, concurrency: Math.max(1, Math.min(100, Number(e.target.value) || 4)) })} />
            </div>
            <div>
              <label className="label">对照实验</label>
              <select className="input" value={runForm.experiment_id || ''}
                onChange={(e) => setRunForm({ ...runForm, experiment_id: e.target.value })}>
                <option value="">无</option>
                {experiments.map(exp => <option key={exp.id} value={exp.id}>{exp.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label">变体</label>
              <input className="input" value={runForm.variant || ''} placeholder="如 v2 / with-agent"
                onChange={(e) => setRunForm({ ...runForm, variant: e.target.value })} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={runForm.agent_on === 1}
              onChange={(e) => setRunForm({ ...runForm, agent_on: e.target.checked ? 1 : 0 })} />
            {obj.kind === 'team' ? '启用专家团' : '启用专家'}
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={() => setShowRun(false)}><X size={13} />取消</button>
          <button className="btn btn-primary" disabled={launching} onClick={launch}>{launching ? <Spinner light /> : <><Play size={13} />启动</>}</button>
        </div>
      </Modal>

      {/* 历史对比详细弹窗 */}
      <CompareModal open={compareOpen} compare={compare} onClose={() => setCompareOpen(false)} />
    </div>
  )
}
