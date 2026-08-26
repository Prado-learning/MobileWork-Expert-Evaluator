import React, { useEffect, useState, useMemo } from 'react'
import { Plus, Pencil, Trash2, Star, KeyRound, X, Save, Search, ChevronLeft, ChevronRight, Eye, EyeOff } from 'lucide-react'
import { api } from '../api'
import { Empty, Spinner, Modal } from '../components/ui'

const PAGE_SIZE = 10

function ModelForm({ initial, onSave, onClose }) {
  const [form, setForm] = useState({
    model: initial?.model || '',
    base_url: initial?.base_url || '',
    api_key: initial?.api_key || '',
    is_default: initial?.is_default || false,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [showKey, setShowKey] = useState(false)

  const save = async () => {
    if (!form.model.trim()) {
      setError('请填写模型名称')
      return
    }
    setBusy(true); setError('')
    try {
      // 编辑：仅提交 name/model/is_default，接口地址与密钥保持原值（后端空值不覆盖）
      // 添加：name 直接等于模型名称，服务商留空由系统默认推断
      await onSave(initial
        ? { name: form.model.trim(), model: form.model.trim(), is_default: form.is_default }
        : { name: form.model.trim(), model: form.model.trim(), provider: '', base_url: form.base_url, api_key: form.api_key, is_default: form.is_default })
      onClose()
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  return (
    <Modal open title={initial ? '编辑模型' : '添加模型'} onClose={onClose}>
      <div className="space-y-3">
        <div>
          <label className="label">模型名称</label>
          <input className="input" value={form.model} placeholder="如 deepseek-v4-flash"
            onChange={(e) => setForm({ ...form, model: e.target.value })} />
        </div>
        {!initial && (
          <>
            <div>
              <label className="label">接口地址</label>
              <input className="input" value={form.base_url} placeholder="https://api.deepseek.com/v1"
                onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
            </div>
            <div>
              <label className="label">API Key</label>
              <div className="relative">
                <KeyRound size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
                <input className="input !pl-8 !pr-9" type={showKey ? 'text' : 'password'} value={form.api_key}
                  placeholder="sk-..." autoComplete="off"
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
                <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-ink p-0.5"
                  onClick={() => setShowKey(!showKey)} aria-label={showKey ? '隐藏密钥' : '显示密钥'}>
                  {showKey ? <Eye size={15} /> : <EyeOff size={15} />}
                </button>
              </div>
            </div>
          </>
        )}
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={form.is_default}
            onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
          评测时默认使用此模型
        </label>
        {error && <div className="text-danger text-sm">{error}</div>}
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={onClose}><X size={13} />取消</button>
          <button className="btn btn-primary" disabled={busy} onClick={save}>
            {busy ? <Spinner light /> : <><Save size={13} />保存</>}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** 评测模型管理：发起评测时选择要使用的模型。 */
export default function ModelsPage() {
  const [models, setModels] = useState(null)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  // 查询 / 筛选 / 分页
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState('all')   // all | default
  const [page, setPage] = useState(1)

  const load = () => {
    setError('')
    api.listModels().then(setModels).catch((e) => setError(e.message))
  }
  useEffect(() => { load() }, [])

  // 过滤 + 分页（本地计算）
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (models || []).filter((m) => {
      if (kindFilter === 'default' && m.is_default !== 1) return false
      if (!q) return true
      return (m.name || '').toLowerCase().includes(q)
        || (m.provider || '').toLowerCase().includes(q)
        || (m.model || '').toLowerCase().includes(q)
        || (m.base_url || '').toLowerCase().includes(q)
    })
  }, [models, query, kindFilter])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  // 查询/筛选变化时回到第一页
  useEffect(() => { setPage(1) }, [query, kindFilter])

  const del = async (m) => {
    if (!window.confirm(`确认删除模型「${m.name}」？已发起的评测不受影响。`)) return
    try {
      await api.deleteModel(m.id)
      load()
    } catch (e) { setError(e.message) }
  }

  return (
    <div className="flex flex-col min-h-[calc(100vh-96px)]">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">管理评测模型</h1>
        <button className="btn btn-primary" onClick={() => { setEditing(null); setShowForm(true) }}>
          <Plus size={14} />添加模型
        </button>
      </div>

      <div className="text-xs text-muted mb-4 border border-dashed border-hairline rounded-default px-3 py-2 bg-accent/5 leading-relaxed">
        发起评测前，需要先在这里配置好要使用的模型。密钥只保存在本机，不会明文显示。
      </div>

      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}

      {/* 查询 / 筛选 */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
          <input className="input !pl-8" placeholder="搜索名称 / 服务商 / 模型" value={query}
            onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex items-center gap-1 border border-hairline rounded-default p-0.5">
          {[['all', '全部'], ['default', '默认模型']].map(([k, label]) => (
            <button key={k} className={`px-2.5 py-1 text-xs rounded-default ${kindFilter === k ? 'bg-accent text-white font-medium' : 'text-muted hover:text-ink'}`}
              onClick={() => setKindFilter(k)}>{label}</button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1">
        {!models ? (
          <Empty text="加载中…" />
        ) : filtered.length === 0 ? (
          <Empty text={models.length === 0 ? '还没有配置模型，点击右上角「添加模型」即可' : '无匹配结果'} />
        ) : (
          <div className="card !p-0 overflow-hidden">
            <div className="divide-y divide-hairline">
              {pageRows.map((m) => (
                <div key={m.id} className="flex items-center gap-4 px-4 py-3 hover:bg-page/60 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{m.name}</span>
                      {m.is_default === 1 && (
                        <span className="badge badge-pass !text-[10px]">
                          <Star size={10} className="mr-0.5 inline" />默认
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted mt-0.5 truncate">
                      {m.base_url ? m.base_url : '默认端点'} · {m.api_key_hint ? m.api_key_hint : '未配置'}
                    </div>
                  </div>
                  <div className="flex-none flex items-center gap-1.5">
                    <button className="btn !px-2 text-xs" onClick={() => { setEditing(m); setShowForm(true) }}>
                      <Pencil size={12} />编辑
                    </button>
                    <button className="btn btn-danger !px-2 text-xs" onClick={() => del(m)}>
                      <Trash2 size={12} />删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 分页（始终显示，固定在页面底部） */}
      <div className="flex items-center justify-center gap-2 mt-4 pt-3 border-t border-hairline">
        <button className="btn !px-2.5" disabled={page <= 1 || filtered.length === 0} onClick={() => setPage(page - 1)} aria-label="上一页"><ChevronLeft size={15} /></button>
        <span className="text-sm text-muted">第 {filtered.length === 0 ? 0 : page} / {totalPages} 页 · 共 {filtered.length} 条</span>
        <button className="btn !px-2.5" disabled={page >= totalPages || filtered.length === 0} onClick={() => setPage(page + 1)} aria-label="下一页"><ChevronRight size={15} /></button>
      </div>

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
