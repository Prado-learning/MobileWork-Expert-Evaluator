import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer } from 'recharts'
import { Plus, ChevronDown, ChevronUp, FlaskConical, X, Check, ArrowLeft } from 'lucide-react'
import { api } from '../api'

const VAR_LABELS = {
  model: '基础模型',
  version: '专家版本',
  agent_on: '是否启用专家团',
}

export default function ExperimentsPage() {
  const { objectId } = useParams()
  const [experiments, setExperiments] = useState([])
  const [showNew, setShowNew] = useState(false)
  const [form, setForm] = useState({ name: '', variable: 'model', description: '' })
  const [expanded, setExpanded] = useState(null)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')

  const load = () => {
    api.listExperiments(objectId).then(setExperiments).catch(e => setError(e.message))
  }
  useEffect(load, [objectId])

  const create = async () => {
    if (!form.name.trim()) return
    setError('')
    try {
      await api.createExperiment({ ...form, object_id: Number(objectId) })
      setShowNew(false); setForm({ name: '', variable: 'model', description: '' })
      load()
    } catch (e) { setError(`创建失败：${e.message}`) }
  }

  const toggle = async (id) => {
    if (expanded === id) { setExpanded(null); setDetail(null); return }
    setExpanded(id)
    try { setDetail(await api.getExperiment(id)) } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link to={`/objects/${objectId}`} className="btn !px-2.5" aria-label="返回"><ArrowLeft size={14} /></Link>
        <h1 className="text-xl font-semibold flex items-center gap-2"><FlaskConical size={20} className="text-accent" /> 对照实验</h1>
        <span className="text-xs text-muted">同一组用例在不同变量下对比，量化专家介入价值</span>
        <button className="btn btn-primary ml-auto" onClick={() => setShowNew(true)}><Plus size={14} /> 新建实验</button>
      </div>

      {error && <div className="text-danger text-sm mb-3">{error}</div>}

      {experiments.length === 0 ? (
        <div className="card text-muted text-sm py-8 text-center">
          暂无对照实验。创建一个实验，然后对同一任务在不同变量（模型/版本/是否启用专家团）下各发起一次评测即可对比。
        </div>
      ) : (
        experiments.map(exp => (
          <div key={exp.id} className="border border-hairline rounded-default mb-2">
            <button className="w-full flex items-center gap-3 p-3 text-left hover:bg-page/50" onClick={() => toggle(exp.id)}>
              <span className="badge">{VAR_LABELS[exp.variable] || exp.variable}</span>
              <span className="text-sm font-medium">{exp.name}</span>
              <span className="text-xs text-muted">{exp.description}</span>
              <span className="ml-auto text-xs text-muted">{expanded === exp.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
            </button>
            {expanded === exp.id && detail && (
              <div className="px-3 pb-3">
                {detail.variants.length === 0 ? (
                  <div className="text-xs text-muted py-3">该实验下还没有评测运行。发起评测时指定本实验与变体即可。</div>
                ) : (
                  <div>
                    <div className="h-40 mb-3">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={detail.variants.map(v => ({ name: v.variant, score: v.score_avg ?? 0, pass: v.pass_rate ?? 0 }))}>
                          <XAxis dataKey="name" fontSize={11} />
                          <YAxis domain={[0, 1]} fontSize={11} />
                          <Tooltip />
                          <Bar dataKey="score" name="平均得分" radius={[4, 4, 0, 0]}>
                            {detail.variants.map((v, i) => <Cell key={i} fill="#1890ff" />)}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <table className="table-base text-xs w-full">
                      <thead><tr><th>变体</th><th>运行数</th><th>平均得分</th><th>通过率</th><th>模型</th></tr></thead>
                      <tbody>
                        {detail.variants.map(v => (
                          <tr key={v.variant}>
                            <td className="font-medium">{v.variant}</td>
                            <td>{v.run_count}</td>
                            <td>{v.score_avg != null ? v.score_avg.toFixed(3) : '—'}</td>
                            <td>{v.pass_rate != null ? `${(v.pass_rate * 100).toFixed(1)}%` : '—'}</td>
                            <td className="text-muted">{v.models.join('、')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        ))
      )}

      {showNew && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="card w-96">
            <h3 className="font-semibold mb-3">新建对照实验</h3>
            <div className="space-y-3">
              <div>
                <label className="label">实验名称</label>
                <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="如：deepseek vs 其他模型" />
              </div>
              <div>
                <label className="label">对比变量</label>
                <select className="input" value={form.variable} onChange={e => setForm({ ...form, variable: e.target.value })}>
                  <option value="model">基础模型</option>
                  <option value="version">专家版本</option>
                  <option value="agent_on">是否启用专家团</option>
                </select>
              </div>
              <div>
                <label className="label">描述</label>
                <input className="input" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
              </div>
              <div className="flex justify-end gap-2">
                <button className="btn" onClick={() => setShowNew(false)}><X size={13} />取消</button>
                <button className="btn btn-primary" disabled={!form.name.trim()} onClick={create}><Check size={13} />创建</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
