import React, { useEffect, useState, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, FolderOpen, X, Upload, Check, UserPlus, Search, ChevronLeft, ChevronRight, Trash2, Eye, Copy } from 'lucide-react'
import { api } from '../api'
import { Modal, KindBadge, Empty, Spinner, fmtTime } from '../components/ui'
import { WorkspaceDirInput } from '../components/DirectoryPicker'

const PAGE_SIZE = 10

const SKIP_DIRS = ['node_modules', '.git', '__pycache__', 'dist', '.pytest_cache']
function shouldSkipRel(rel) {
  const parts = rel.split('/')
  if (parts.some(p => SKIP_DIRS.includes(p))) return true
  if (parts[0] === '__MACOSX') return true
  return ['.DS_Store', 'Thumbs.db'].includes(parts[parts.length - 1])
}

export default function ObjectsPage() {
  const navigate = useNavigate()
  const [objects, setObjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [mode, setMode] = useState('upload')
  const [form, setForm] = useState({ name: '', kind: 'team', agent_name: 'software-team-lead', description: '', workspace_dir: '', provider: 'deepseek', model: 'deepseek-v4-flash' })
  const [dirFiles, setDirFiles] = useState(null)
  const [uploading, setUploading] = useState(false)
  const dirInputRef = useRef(null)
  // 创建专家/专家团 引导提示
  const [showCreateGuide, setShowCreateGuide] = useState(false)
  const [copied, setCopied] = useState(false)

  const TEMPLATE_PROMPT = '请加载本插件捆绑的 mobilework-expert-manager 技能（skills/mobilework-expert-manager/SKILL.md），按其中协议帮我创建一个专家或专家团：\n\n<这里填写创建要求，例如：负责代码评审的专家团，包含 3 个成员>\n\n完成后告诉我产物路径，并询问我是否需要把它导入评测中心。'

  const copyTemplate = async () => {
    const text = TEMPLATE_PROMPT
    // 优先 Clipboard API；失败（如页面未聚焦）回退 execCommand（不依赖聚焦状态）
    let ok = false
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        ok = true
      }
    } catch { /* fallthrough */ }
    if (!ok) {
      try {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        ok = document.execCommand('copy')
        document.body.removeChild(ta)
      } catch { ok = false }
    }
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }
  // 查询 / 筛选 / 分页
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState('all')
  const [page, setPage] = useState(1)

  const load = async () => {
    try { setObjects(await api.listObjects()); setError('') }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }
  useEffect(() => {
    load()
    // 自动刷新：OpenWork 的 AI 可能在后台导入/删除专家团，页面可见时每 5s 静默刷新列表
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 5000)
    return () => clearInterval(t)
  }, [])

  // 过滤 + 分页（本地计算）
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return objects.filter((o) => {
      if (kindFilter !== 'all' && o.kind !== kindFilter) return false
      if (!q) return true
      return (o.name || '').toLowerCase().includes(q)
        || (o.agent_name || '').toLowerCase().includes(q)
        || (o.description || '').toLowerCase().includes(q)
    })
  }, [objects, query, kindFilter])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  // 查询/筛选变化时回到第一页
  useEffect(() => { setPage(1) }, [query, kindFilter])

  const delObject = async (o) => {
    if (!window.confirm(`确认删除「${o.name}」？其用例、评测记录与隔离工作区将一并删除，不可恢复。`)) return
    try {
      await api.deleteObject(o.id); load()
    } catch (e) { setError(`删除失败：${e.message}`) }
  }

  const reset = () => {
    setForm({ name: '', kind: 'team', agent_name: 'software-team-lead', description: '', workspace_dir: '', provider: 'deepseek', model: 'deepseek-v4-flash' })
    setDirFiles(null); setMode('upload'); setShowNew(false)
  }

  const handleDirSelect = (e) => {
    const files = e.target.files
    setDirFiles(files)
    if (files.length) {
      const dirName = files[0].webkitRelativePath.split('/')[0]
      setForm((f) => ({ ...f, name: f.name || dirName }))
    }
  }

  const createManual = async () => {
    try {
      await api.createObject(form); reset(); load()
    } catch (e) { setError(`创建失败：${e.message}`) }
  }

  const submitUpload = async () => {
    if (!dirFiles?.length) return
    setUploading(true); setError('')
    try {
      const fd = new FormData()
      let n = 0
      for (const f of dirFiles) {
        const rel = f.webkitRelativePath
        if (shouldSkipRel(rel)) continue
        fd.append('files', f, rel); n++
      }
      if (!n) throw new Error('所选文件夹没有可上传的文件（已过滤 node_modules 等）')
      fd.append('name', form.name)
      fd.append('kind', form.kind)
      fd.append('description', form.description)
      const res = await fetch('/api/objects/upload', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `上传失败 ${res.status}`)
      reset(); load()
    } catch (e) { setError(`上传失败：${e.message}`) }
    finally { setUploading(false) }
  }

  return (
    <div className="flex flex-col min-h-[calc(100vh-96px)]">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">管理专家 / 专家团</h1>
        <div className="flex items-center gap-2">
          <button className="btn" onClick={() => setShowCreateGuide(true)} title="在对话框中用自然语言创建专家/专家团"><UserPlus size={14} />新建</button>
          <button className="btn btn-primary" onClick={() => setShowNew(true)} title="上传专家文件夹或配置服务器路径"><Plus size={14} />添加</button>
        </div>
      </div>

      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}

      {/* 查询 / 筛选 */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
          <input className="input !pl-8" placeholder="搜索名称 / agent / 描述" value={query}
            onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex items-center gap-1 border border-hairline rounded-default p-0.5">
          {[['all', '全部'], ['team', '专家团'], ['single', '单专家']].map(([k, label]) => (
            <button key={k} className={`px-2.5 py-1 text-xs rounded-default ${kindFilter === k ? 'bg-accent text-white font-medium' : 'text-muted hover:text-ink'}`}
              onClick={() => setKindFilter(k)}>{label}</button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1">
        {loading ? <Empty text="加载中…" /> : filtered.length === 0 ? (
          <Empty text={objects.length === 0 ? '还没有专家/专家团' : '无匹配结果'} />
        ) : (
          <div className="card !p-0 overflow-hidden">
            <div className="divide-y divide-hairline">
              {pageRows.map((o) => (
                <div key={o.id} className="flex items-center gap-4 px-4 py-3 hover:bg-page/60 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium truncate">{o.name}</span>
                      <KindBadge kind={o.kind} />
                    </div>
                    <div className="text-xs text-muted mt-0.5 flex items-center gap-3 flex-wrap">
                      <code>{o.agent_name}</code>
                      <span>任务 {o.task_count}</span>
                      <span>评测 {o.run_count}</span>
                      <span>已审用例 {o.approved_case_count}</span>
                      {o.last_run?.score != null && <span>最近 {o.last_run.score.toFixed(2)}</span>}
                      <span>{fmtTime(o.created_at).slice(0, 10)}</span>
                    </div>
                  </div>
                  <div className="flex-none flex items-center gap-1.5">
                    <button className="btn !px-2 text-xs" onClick={() => navigate(`/objects/${o.id}`)}><Eye size={13} />详情</button>
                    <button className="btn btn-danger !px-2 text-xs" onClick={() => delObject(o)}><Trash2 size={13} />删除</button>
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

      <Modal open={showNew} title="添加对象" onClose={reset}>
        <div className="flex gap-1 border-b border-hairline mb-4">
          {[['upload', '上传文件夹'], ['manual', '服务器路径']].map(([k, label]) => (
            <button key={k} className={`px-3 py-1.5 text-sm border-b-2 -mb-px ${mode === k ? 'border-accent text-ink font-medium' : 'border-transparent text-muted hover:text-ink'}`}
              onClick={() => setMode(k)}>{label}</button>
          ))}
        </div>
        {mode === 'upload' ? (
          <div className="grid gap-3">
            <div>
              <label className="label">选择专家文件夹（含 .opencode 配置）</label>
              <input ref={dirInputRef} type="file" webkitdirectory="" className="hidden" onChange={handleDirSelect} />
              <button className="btn" onClick={() => dirInputRef.current?.click()}><FolderOpen size={13} />
                {dirFiles ? `已选 ${dirFiles.length} 个文件` : '选择文件夹…'}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">名称</label>
                <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <label className="label">类型</label>
                <select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                  <option value="team">专家团</option>
                  <option value="single">单专家</option>
                </select>
              </div>
            </div>
            <div>
              <label className="label">描述</label>
              <input className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
          </div>
        ) : (
          <div className="grid gap-3">
            <div>
              <label className="label">名称</label>
              <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">类型</label>
                <select className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                  <option value="team">专家团</option>
                  <option value="single">单专家</option>
                </select>
              </div>
              <div>
                <label className="label">agent 名称</label>
                <input className="input" value={form.agent_name} onChange={(e) => setForm({ ...form, agent_name: e.target.value })} />
              </div>
            </div>
            <div>
              <label className="label">评测工作区</label>
              <WorkspaceDirInput value={form.workspace_dir} onChange={(v) => setForm({ ...form, workspace_dir: v })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">评测模型 provider</label>
                <select className="input" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                  <option value="deepseek">deepseek</option>
                  <option value="anthropic">anthropic</option>
                  <option value="openai">openai</option>
                </select>
              </div>
              <div>
                <label className="label">评测模型</label>
                <input className="input" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="deepseek-v4-flash" />
              </div>
            </div>
            <div>
              <label className="label">描述</label>
              <input className="input" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn" onClick={reset}><X size={13} />取消</button>
          {mode === 'upload'
            ? <button className="btn btn-primary" disabled={uploading || !dirFiles} onClick={submitUpload}>{uploading ? <Spinner light /> : <><Upload size={13} />上传</>}</button>
            : <button className="btn btn-primary" onClick={createManual}><Plus size={13} />创建</button>}
        </div>
      </Modal>

      <Modal open={showCreateGuide} title="创建专家 / 专家团" onClose={() => setShowCreateGuide(false)}>
        <div className="grid gap-4 text-sm text-muted leading-relaxed">
          <div>在对话框中发送下面的提示词，即可自动创建专家或专家团。</div>
          <div className="relative card !p-3 pr-14 bg-page/60 text-xs font-mono leading-relaxed whitespace-pre-line">
            <button type="button"
              className={`absolute top-2 right-2 inline-flex items-center gap-1 text-xs rounded-default border px-2 py-0.5 transition-colors ${copied ? 'border-accent text-accent' : 'border-hairline text-muted hover:text-ink'}`}
              onClick={copyTemplate}>
              <Copy size={11} />{copied ? '已复制' : '复制'}
            </button>
            {TEMPLATE_PROMPT}
          </div>
        </div>
        <div className="flex justify-end mt-4">
          <button className="btn btn-primary" onClick={() => setShowCreateGuide(false)}><Check size={13} />知道了</button>
        </div>
      </Modal>
    </div>
  )
}
