import React from 'react'
import { X, HelpCircle } from 'lucide-react'

export function StatusBadge({ status }) {
  const map = {
    passed: { cls: 'badge-pass', text: '通过' },
    failed: { cls: 'badge-fail', text: '失败' },
    running: { cls: 'badge-running', text: '运行中' },
    pending: { cls: 'badge-muted', text: '等待中' },
    error: { cls: 'badge-fail', text: '异常' },
    aborted: { cls: 'badge-muted', text: '已中止' },
  }
  const m = map[status] || map.pending
  return <span className={`badge ${m.cls}`}>{m.text}</span>
}

export function KindBadge({ kind }) {
  return kind === 'team'
    ? <span className="badge badge-team">专家团</span>
    : <span className="badge badge-single">单专家</span>
}

export function ScenarioBadge({ type }) {
  const map = {
    structured: { text: '结构化', cls: 'badge-pass' },
    hybrid: { text: '混合式', cls: 'badge-team' },
    open_ended: { text: '开放式', cls: 'badge-muted' },
  }
  const m = map[type] || map.hybrid
  return <span className={`badge ${m.cls}`}>{m.text}</span>
}

export function Modal({ open, title, onClose, children, width = 'max-w-lg' }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div className={`card w-full ${width} max-h-[85vh] overflow-y-auto`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold">{title}</h3>
          <button className="btn btn-danger !px-2 !py-0.5" onClick={onClose}><X size={13} /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Spinner({ light = false }) {
  return <span className={`inline-block w-3.5 h-3.5 border-2 rounded-full animate-spin align-middle ${light ? 'border-white border-t-transparent' : 'border-accent border-t-transparent'}`} />
}

/** 小圆提示按钮：点击弹出说明 */
export function HelpButton({ onClick, title = '说明' }) {
  return (
    <button type="button" className="btn !px-1.5 !py-0.5" onClick={onClick} title={title} aria-label={title}>
      <HelpCircle size={13} />
    </button>
  )
}

/** 弹窗：评测任务 vs 评测用例 关系说明 */
export function TaskVsCaseHelp({ open, onClose }) {
  return (
    <Modal open={open} title="评测任务 vs 评测用例" onClose={onClose} width="max-w-xl">
      <div className="space-y-3 text-sm">
        <p className="text-xs text-muted">完整层级：专家/专家团（对象）→ 评测任务 → 评测用例 → 评测运行。</p>
        <div className="border border-hairline rounded-default p-3">
          <div className="font-medium mb-1">评测任务（考纲）</div>
          <p className="text-xs text-muted">挂在某个专家/专家团下的评测目标定义，描述「测什么能力、按什么标准测」：场景类型、自主度、固定提示词、断言、业务指标。任务本身不直接执行。</p>
        </div>
        <div className="border border-hairline rounded-default p-3">
          <div className="font-medium mb-1">评测用例（考题）</div>
          <p className="text-xs text-muted">挂在任务下的一条条具体考题，每条独立（标题/提示词/输出目录/断言），需逐条人工审核，通过（approved）后才会参与评测。</p>
        </div>
        <div className="border border-hairline rounded-default p-3">
          <div className="font-medium mb-1">两者关系</div>
          <p className="text-xs text-muted">任务 = 考纲，用例 = 具体题目。一次评测运行 = 用该专家团全部已审核用例真实跑一遍；若还没有已审核用例，系统会用任务定义自动生成单个用例兜底。</p>
        </div>
      </div>
    </Modal>
  )
}

export function Empty({ text = '暂无数据' }) {
  return <div className="text-center text-muted text-sm py-10">{text}</div>
}

export function fmtTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 19)
}

export function fmtMs(ms) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}
