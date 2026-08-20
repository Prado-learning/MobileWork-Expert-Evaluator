import React, { useEffect, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { api } from '../api'
import { Modal, Spinner, Empty } from './ui'

/** 目录选择器：通过后端浏览本地目录（本地单机应用），支持打开文件夹选择 + 保留手动输入。 */
export function WorkspaceDirInput({ value, onChange, placeholder }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex gap-2">
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || '输入评测工作区路径，或点击「浏览」选择'} />
      <button type="button" className="btn flex-none" onClick={() => setOpen(true)}>浏览…</button>
      {open && (
        <DirectoryPickerModal
          initial={value}
          onClose={() => setOpen(false)}
          onSelect={(p) => { onChange(p); setOpen(false) }}
        />
      )}
    </div>
  )
}

export function DirectoryPickerModal({ initial, onClose, onSelect }) {
  const [path, setPath] = useState(initial || '')
  const [dirs, setDirs] = useState([])
  const [parent, setParent] = useState(null)
  const [isRoot, setIsRoot] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async (p) => {
    setLoading(true)
    setError('')
    try {
      const r = await api.browse(p)
      setPath(r.path)
      setDirs(r.dirs || [])
      setParent(r.parent)
      setIsRoot(r.is_root)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load(initial || '') }, [])

  return (
    <Modal open title="选择评测工作区目录" onClose={onClose} width="max-w-xl">
      <div className="text-xs text-muted mb-3">
        选择包含 <code>.opencode</code> 配置的评测工作区目录（也可在输入框手动输入路径）。
      </div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-muted flex-none">当前：</span>
        <div className="flex-1 bg-page rounded-default px-2 py-1 font-mono text-xs break-all">{path || '（磁盘根目录）'}</div>
      </div>
      {error && <div className="text-danger text-xs mb-2">{error}</div>}
      <div className="border border-hairline rounded-default max-h-72 overflow-y-auto min-h-[180px]">
        {loading ? <div className="p-6"><Spinner /> 加载中…</div> : dirs.length === 0 ? (
          <Empty text="此目录下没有子目录" />
        ) : (
          <ul className="divide-y divide-hairline">
            {dirs.map((d) => (
              <li key={d}>
                <button className="w-full text-left px-3 py-2 text-sm hover:bg-page flex items-center gap-2"
                  onDoubleClick={() => load(path ? (path.endsWith('\\') || path.endsWith('/') ? path + d : path + '\\' + d) : d)}>
                  <FolderOpen size={14} className="text-accent shrink-0" />
                  <span className="font-mono">{d}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="text-xs text-muted mt-1">单击选中路径栏、双击进入目录</div>
      <div className="flex justify-between gap-2 mt-4">
        <button className="btn" disabled={isRoot} onClick={() => parent && load(parent)}>↑ 上级目录</button>
        <div className="flex gap-2">
          <button className="btn" onClick={onClose}>取消</button>
          <button className="btn btn-primary" onClick={() => onSelect(path)}>选择此目录</button>
        </div>
      </div>
    </Modal>
  )
}
