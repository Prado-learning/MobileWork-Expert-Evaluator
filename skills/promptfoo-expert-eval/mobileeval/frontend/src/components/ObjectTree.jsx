import React, { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Package, Cpu, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { api } from '../api'
import { KindBadge } from './ui'

/** 左侧导航：专家/专家团列表（AI 对话由 OpenWork 完成，此处只导航数据页面）。 */
export default function ObjectTree({ collapsed, onToggleCollapse }) {
  const [objects, setObjects] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    const load = () => api.listObjects().then(setObjects).catch((e) => setError(e.message))
    load()
    // 自动刷新：OpenWork 的 AI 可能在后台导入/删除专家团，页面可见时每 5s 静默刷新侧栏
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 5000)
    return () => clearInterval(t)
  }, [])

  // ---------------- 折叠模式：窄条图标栏 ----------------
  if (collapsed) {
    return (
      <div className="h-full flex flex-col bg-page">
        <div className="py-2 border-b border-hairline flex flex-col items-center gap-1">
          <button className="btn !px-1.5 text-xs" onClick={onToggleCollapse} title="展开侧栏">
            <PanelLeftOpen size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 flex flex-col items-center gap-1">
          <NavLink to="/objects" title="全部专家/专家团" className={({ isActive }) =>
            `block w-8 h-8 flex items-center justify-center rounded-default ${isActive ? 'bg-accent/10 text-accent' : 'text-ink hover:bg-hairline/50'}`}>
            <Package size={17} />
          </NavLink>
          <NavLink to="/models" title="评测模型" className={({ isActive }) =>
            `block w-8 h-8 flex items-center justify-center rounded-default ${isActive ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-hairline/50'}`}>
            <Cpu size={16} />
          </NavLink>
          {objects.map((o) => (
            <NavLink key={o.id} to={`/objects/${o.id}`} title={o.name} className={({ isActive }) =>
              `block w-8 h-8 flex items-center justify-center rounded-default text-xs ${isActive ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-hairline/50'}`}>
              {o.name.slice(0, 1)}
            </NavLink>
          ))}
        </div>
      </div>
    )
  }

  // ---------------- 展开模式 ----------------
  return (
    <div className="h-full flex flex-col bg-page">
      <div className="px-4 py-3 border-b border-hairline flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold text-sm flex items-baseline gap-2">
            <span>MobileEval</span>
            <span className="text-xs text-muted font-normal">评测中心</span>
          </div>
          <div className="text-[11px] text-muted mt-0.5 truncate">专家/专家团 → 用例 → 运行</div>
        </div>
        <button className="btn !px-1.5 text-xs shrink-0" onClick={onToggleCollapse} title="折叠侧栏">
          <PanelLeftClose size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        <NavLink to="/objects" end className={({ isActive }) =>
          `flex items-center gap-1.5 px-2 py-1.5 rounded-default text-sm mb-1 ${isActive ? 'bg-accent/10 text-accent font-medium' : 'text-ink hover:bg-hairline/50'}`}>
          <Package size={15} />
          <span>全部专家/专家团</span>
        </NavLink>
        <NavLink to="/models" className={({ isActive }) =>
          `flex items-center gap-1.5 px-2 py-1.5 rounded-default text-sm mb-1 ${isActive ? 'bg-accent/10 text-accent font-medium' : 'text-ink hover:bg-hairline/50'}`}>
          <Cpu size={15} />
          <span>评测模型</span>
        </NavLink>

        {error && <div className="text-danger text-xs px-2 py-1">{error}</div>}
        {objects.length === 0 && !error && <div className="text-muted text-xs px-2 py-2">暂无专家/专家团，点击「全部」进入新建</div>}
        {objects.map((o) => (
          <NavLink key={o.id} to={`/objects/${o.id}`} className={({ isActive }) =>
            `block px-2 py-1.5 rounded-default text-sm mb-0.5 ${isActive ? 'bg-accent/10 text-accent font-medium' : 'text-ink hover:bg-hairline/50'}`}>
            <span className="truncate block">{o.name}</span>
            <span className="flex gap-2 items-center mt-0.5">
              <KindBadge kind={o.kind} />
              <span className="text-[11px] text-muted">{o.run_count} 次评测</span>
            </span>
          </NavLink>
        ))}
      </div>
    </div>
  )
}
