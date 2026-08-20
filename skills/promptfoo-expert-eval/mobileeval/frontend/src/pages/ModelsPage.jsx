import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Pencil, Trash2, Star, KeyRound } from 'lucide-react'
import { api } from '../api'
import { Empty, Spinner, Modal } from '../components/ui'

const PROVIDERS = [
  { id: 'deepseek', label: 'DeepSeek' },
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'openrouter', label: 'OpenRouter' },
  { id: 'other', label: '自定义' },
]

function ModelForm({ initial, onSave, onClose }) {
  const [form, setForm] = useState({
    name: initial?.name || '',
    provider: initial?.provider || 'deepseek',
    model: initial?.model || '',
    base_url: initial?.base_url || '',
    api_key: initial?.api_key || '',
    is_default: initial?.is_default || false,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    if (!form.name.trim() || !form.model.trim()) {
      setError('名称与模型 id 必填')
      return
    }
    setBusy(true); setError('')
    try {
      await onSave(form)
      onClose()
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return (
    <Modal open title={initial ? '编辑评测模型' : '新增评测模型'} onClose={onClose}>
      <div className="space-y-3">
        <div>
          <label className="label">模型名称（显示用）</label>
          <input className="input" value={form.name} placeholder="如 DeepSeek 官方 / 本地 vLLM"
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Provider（promptfoo provider_id）</label>
            <select className="input" value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}>
              {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label">模型 id</label>
            <input className="input" value={form.model} placeholder="deepseek-v4-flash"
              onChange={(e) => setForm({ ...form, model: e.target.value })} />
          </div>
        </div>
        <div>
          <label className="label">Base URL（可选，自定义网关/本地部署必填）</label>
          <input className="input" value={form.base_url} placeholder="https://api.deepseek.com/v1"
            onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
        </div>
        <div>
          <label className="label">API Key{initial?.api_key_hint ? `（已保存 ${initial.api_key_hint}，留空保持不变）` : ''}</label>
          <div className="relative">
            <KeyRound size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
            <input className="input !pl-8" type="password" value={form.api_key}
              placeholder="sk-..." autoComplete="off"
              onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={form.is_default}
            onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          设为默认模型（发起评测时预选）
        </label>
        {error && <div className="text-danger text-sm">{error}</div>}
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={onClose}>取消</button>
          <button className="btn btn-primary" disabled={busy} onClick={save}>
            {busy ? <Spinner light /> : '保存'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** 全局评测模型管理：发起评测时选择，provider/model/base_url/api_key 传给 promptfoo。 */
export default function ModelsPage() {
  const [models, setModels] = useState(null)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = () => {
    setError('')
    api.listModels().then(setModels).catch((e) => setError(e.message))
  }
  useEffect(() => { load() }, [])

  const del = async (m) => {
    if (!window.confirm(`确认删除模型「${m.name}」？已发起的评测不受影响。`)) return
    try {
      await api.deleteModel(m.id)
      load()
    } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link to="/objects" className="btn !px-2">←</Link>
        <h1 className="text-xl font-semibold">评测模型管理</h1>
        <div className="ml-auto">
          <button className="btn btn-primary" onClick={() => { setEditing(null); setShowForm(true) }}>
            <Plus size={14} className="mr-1 inline" />新增模型
          </button>
        </div>
      </div>
      <p className="text-xs text-muted mb-4">
        全局评测模型：发起评测时下拉选择，评测引擎会把 provider / 模型 / base URL / API Key 传给 promptfoo 调用。
        API Key 仅存本地数据库，列表内以掩码显示。
      </p>
      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}
      {!models ? (
        <Empty text="加载中…" />
      ) : models.length === 0 ? (
        <Empty text="还没有评测模型，点右上角「新增模型」添加（至少一个，发起评测时必选）" />
      ) : (
        <div className="space-y-2">
          {models.map((m) => (
            <div key={m.id} className="card flex items-center gap-3 !py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{m.name}</span>
                  {m.is_default === 1 && (
                    <span className="badge badge-pass !text-[10px]">
                      <Star size={10} className="mr-0.5 inline" />默认
                    </span>
                  )}
                  <span className="text-xs text-muted truncate">{m.provider} / {m.model}</span>
                </div>
                <div className="text-xs text-muted mt-0.5 truncate">
                  {m.base_url ? m.base_url : '默认端点'} · Key {m.api_key_hint ? m.api_key_hint : '未配置'}
                </div>
              </div>
              <div className="flex-none flex gap-1.5">
                <button className="btn !px-2 !py-1 text-xs" onClick={() => { setEditing(m); setShowForm(true) }}>
                  <Pencil size={12} className="mr-1 inline" />编辑
                </button>
                <button className="btn btn-danger !px-2 !py-1 text-xs" onClick={() => del(m)}>
                  <Trash2 size={12} className="mr-1 inline" />删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {showForm && (
        <ModelForm
          initial={editing || null}
          onSave={(body) => editing ? api.updateModel(editing.id, body) : api.createModel(body).then(() => load())}
          onClose={() => { setShowForm(false); setEditing(null); load() }}
        />
      )}
    </div>
  )
}
