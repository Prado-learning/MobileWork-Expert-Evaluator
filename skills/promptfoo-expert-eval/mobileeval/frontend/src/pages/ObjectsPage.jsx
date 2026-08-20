import React, { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Modal, KindBadge, StatusBadge, Empty, Spinner, fmtTime } from '../components/ui'
import { WorkspaceDirInput } from '../components/DirectoryPicker'

const SKIP_DIRS = ['node_modules', '.git', '__pycache__', 'dist', '.pytest_cache']
function shouldSkipRel(rel) {
  const parts = rel.split('/')
  if (parts.some(p => SKIP_DIRS.includes(p))) return true
  if (parts[0] === '__MACOSX') return true
  return ['.DS_Store', 'Thumbs.db'].includes(parts[parts.length - 1])
}

export default function ObjectsPage() {
  const [objects, setObjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [mode, setMode] = useState('upload')
  const [form, setForm] = useState({ name: '', kind: 'team', agent_name: 'software-team-lead', description: '', workspace_dir: '', provider: 'deepseek', model: 'deepseek-v4-flash' })
  const [dirFiles, setDirFiles] = useState(null)
  const [uploading, setUploading] = useState(false)
  const dirInputRef = useRef(null)

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
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold">专家 / 专家团</h1>
          <p className="text-muted text-xs mt-0.5">顶层对象；每个专家团下挂多个评测任务，任务下是多次评测记录</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowNew(true)}>+ 添加专家/专家团</button>
      </div>

      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}
      {loading ? <Empty text="加载中…" /> : objects.length === 0 ? (
        <Empty text="还没有专家/专家团，点击右上角添加（上传专家包文件夹，或在中间对话框让 AI 协助）" />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {objects.map((o) => (
            <Link key={o.id} to={`/objects/${o.id}`} className="card hover:border-accent/50 transition-colors block">
              <div className="flex items-center justify-between mb-2">
                <div className="font-medium">{o.name}</div>
                <KindBadge kind={o.kind} />
              </div>
              <div className="text-xs text-muted mb-2 break-all">
                agent <code>{o.agent_name}</code> · {o.source === 'uploaded' ? '已上传' : '本机路径'}
              </div>
              <div className="flex gap-4 text-xs text-muted">
                <span>任务 {o.task_count}</span>
                <span>评测 {o.run_count}</span>
                <span>已审 case {o.approved_case_count}</span>
                {o.last_run && <span className="ml-auto flex items-center gap-1"><StatusBadge status={o.last_run.status} /> {o.last_run.score?.toFixed(2)}</span>}
                <span>{fmtTime(o.created_at).slice(0, 10)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      <Modal open={showNew} title="添加被测对象" onClose={reset}>
        <div className="flex gap-1 border-b border-hairline mb-4">
          {[['upload', '上传专家文件夹'], ['manual', '手动配置（服务器路径）']].map(([k, label]) => (
            <button key={k} className={`px-3 py-1.5 text-sm border-b-2 -mb-px ${mode === k ? 'border-accent text-ink font-medium' : 'border-transparent text-muted hover:text-ink'}`}
              onClick={() => setMode(k)}>{label}</button>
          ))}
        </div>
        {mode === 'upload' ? (
          <div className="grid gap-3">
            <div>
              <label className="label">选择专家/专家团文件夹（含 .opencode 配置；服务器自动构建评测工作区并做非交互权限适配）</label>
              <input ref={dirInputRef} type="file" webkitdirectory="" className="hidden" onChange={handleDirSelect} />
              <button className="btn" onClick={() => dirInputRef.current?.click()}>
                {dirFiles ? `已选（${dirFiles.length} 个文件，自动过滤 node_modules）` : '选择文件夹…'}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">名称（默认取文件夹名）</label>
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
              <label className="label">名称 *</label>
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
              <label className="label">评测工作区（含 .opencode 配置）</label>
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
          <button className="btn" onClick={reset}>取消</button>
          {mode === 'upload'
            ? <button className="btn btn-primary" disabled={uploading || !dirFiles} onClick={submitUpload}>{uploading ? <Spinner light /> : '上传并添加'}</button>
            : <button className="btn btn-primary" onClick={createManual}>创建</button>}
        </div>
      </Modal>
    </div>
  )
}
