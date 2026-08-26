import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { Brain, FileInput, Puzzle, CircleCheck, Lightbulb, X, Check, Trash2, Plus, Eye, Upload, Copy } from 'lucide-react'
import { api } from '../api'
import { Modal, Spinner, Empty } from './ui'

const STATUS = {
  pending: { cls: 'badge-running', text: '待审核' },
  approved: { cls: 'badge-pass', text: '已通过' },
}

/** Case 管理：AI 自动生成 case 集 → 人工审核（通过/编辑后通过/删除）→ 评测使用已审核 case。 */
export default function CaseManager({ objectId, onCasesChange }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [genCount, setGenCount] = useState(6)
  const [genMode, setGenMode] = useState('replace')   // replace=覆盖未审核 | append=直接追加
  const [confirmOpen, setConfirmOpen] = useState(false)   // 生成前确认弹窗（模式 + 数量）
  const [logicOpen, setLogicOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState('all')   // all | pending | approved
  // AI 导入用例引导（与"创建专家/专家团"一致：给模板，用户复制到对话框填路径）
  const [importOpen, setImportOpen] = useState(false)
  const [importCopied, setImportCopied] = useState(false)
  const [objectName, setObjectName] = useState('')

  const importTemplate = `请读取本机中的用例文件，文件路径如下：

<这里填写用例文件路径，如：/Users/xxx/测试用例.md>

将它们转换为评测中心的标准用例格式，并导入到「${objectName || '当前专家/专家团'}」的评测用例中。

转换结果先展示给我确认，确认后再写入。`

  const copyImportTemplate = async () => {
    const text = importTemplate
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
      setImportCopied(true)
      setTimeout(() => setImportCopied(false), 2000)
    }
  }

  const load = async () => {
    try {
      const r = await api.listCases(objectId)
      setData(r)
      onCasesChange?.(r.cases || [])
      setError('')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }
  React.useEffect(() => { setLoading(true); load() }, [objectId])

  // 拉取当前对象名称（用于导入模板：替换"当前专家/专家团"）
  React.useEffect(() => {
    api.getObject(objectId).then((o) => setObjectName(o?.name || '')).catch(() => {})
  }, [objectId])

  const generate = async () => {
    setConfirmOpen(false)
    setGenerating(true)
    setError('')
    try { await api.generateCases(objectId, genCount, genMode); await load() }
    catch (e) { setError(`生成失败：${e.message}`) }
    finally { setGenerating(false) }
  }

  const act = async (fn, msg) => {
    setError('')
    try { await fn(); await load() } catch (e) { setError(`${msg}：${e.message}`) }
  }

  if (loading) return <Empty text="加载中…" />
  const cases = data?.cases || []
  const counts = { pending: 0, approved: 0 }
  cases.forEach(c => { counts[c.status] = (counts[c.status] || 0) + 1 })
  const filtered = statusFilter === 'all' ? cases : cases.filter(c => c.status === statusFilter)

  return (
    <div>
      {/* 操作栏：左侧筛选 + 右侧操作 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1 border border-hairline rounded-default p-0.5">
          {[['all', '全部'], ['pending', '待审核'], ['approved', '已通过']].map(([k, label]) => (
            <button key={k} className={`px-2.5 py-1 text-xs rounded-default ${statusFilter === k ? 'bg-accent text-white font-medium' : 'text-muted hover:text-ink'}`}
              onClick={() => setStatusFilter(k)}>{label}</button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button className="btn !px-2 text-xs" onClick={() => setLogicOpen(true)} title="查看生成逻辑">
            <Lightbulb size={14} className="text-accent" />
          </button>
          <button className="btn btn-primary" disabled={generating} onClick={() => setConfirmOpen(true)}>
            {generating ? <Spinner light /> : <><Plus size={14} />生成用例</>}
          </button>
          <button className="btn" onClick={() => setImportOpen(true)} title="上传现成的用例文件，AI 自动转换为评测用例">
            <Upload size={14} />上传用例
          </button>
        </div>
      </div>
      {error && <div className="text-danger text-xs mb-3">{error}</div>}

      {/* 上传用例引导弹窗：给提示词模板，用户复制到对话框填文件路径 */}
      <Modal open={importOpen} title="上传用例" onClose={() => setImportOpen(false)}>
        <div className="grid gap-4 text-sm text-muted leading-relaxed">
          <div>在对话框中发送下面的提示词，AI 会自动读取并转换为评测用例。</div>
          <div className="relative card !p-3 pr-14 bg-page/60 text-xs font-mono leading-relaxed whitespace-pre-line">
            <button type="button"
              className={`absolute top-2 right-2 inline-flex items-center gap-1 text-xs rounded-default border px-2 py-0.5 transition-colors ${importCopied ? 'border-accent text-accent' : 'border-hairline text-muted hover:text-ink'}`}
              onClick={copyImportTemplate}>
              <Copy size={11} />{importCopied ? '已复制' : '复制'}
            </button>
            {importTemplate}
          </div>
        </div>
        <div className="flex justify-end mt-4">
          <button className="btn btn-primary" onClick={() => setImportOpen(false)}><Check size={13} />知道了</button>
        </div>
      </Modal>

      {/* 生成前确认弹窗 */}
      <Modal open={confirmOpen} title="生成用例" onClose={() => setConfirmOpen(false)}>
        <div className="space-y-4 text-sm">
          <div>
            <div className="font-medium mb-2">生成模式</div>
            <div className="space-y-2">
              <label className={`flex items-start gap-2 border border-hairline rounded-default p-3 cursor-pointer ${genMode === 'append' ? 'border-accent bg-accent/5' : ''}`}>
                <input type="radio" name="gen-mode" checked={genMode === 'append'} onChange={() => setGenMode('append')} />
                <span>
                  <span className="font-medium">追加</span>
                  <span className="block text-xs text-muted mt-0.5">保留全部旧用例，只新增一批</span>
                </span>
              </label>
              <label className={`flex items-start gap-2 border border-hairline rounded-default p-3 cursor-pointer ${genMode === 'replace' ? 'border-accent bg-accent/5' : ''}`}>
                <input type="radio" name="gen-mode" checked={genMode === 'replace'} onChange={() => setGenMode('replace')} />
                <span>
                  <span className="font-medium">覆盖未审核</span>
                  <span className="block text-xs text-muted mt-0.5">删除旧的待审核用例后重新生成，已通过的保留</span>
                </span>
              </label>
            </div>
          </div>
          <div>
            <div className="font-medium mb-2">数量（1-12）</div>
            <input type="number" min={1} max={12} className="input !w-28" value={genCount}
              onChange={(e) => setGenCount(Math.max(1, Math.min(12, Number(e.target.value) || 6)))} />
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-hairline">
            <button className="btn" onClick={() => setConfirmOpen(false)}><X size={13} />取消</button>
            <button className="btn btn-primary" disabled={generating} onClick={generate}>
              {generating ? <Spinner light /> : <><Plus size={13} />生成</>}
            </button>
          </div>
        </div>
      </Modal>

      {filtered.length === 0 ? (
        <Empty text={cases.length === 0 ? '暂无用例，点击「生成用例」' : '无匹配结果'} />
      ) : (
        <div className="border border-hairline rounded-default overflow-hidden bg-surface">
          <div className="divide-y divide-hairline">
            {filtered.map((c) => {
              const st = STATUS[c.status] || STATUS.pending
              const num = String(c.case_id || '').replace(/\D/g, '')
              return (
                <div key={c.id} className="flex items-center gap-4 px-4 py-3 hover:bg-page/60 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <code className="text-xs text-muted">{num ? `用例 ${num}` : c.case_id}</code>
                      <span className="font-medium truncate">{c.title}</span>
                      <span className={`badge ${st.cls}`}>{st.text}</span>
                    </div>
                    {c.prompt && (
                      <div className="text-xs text-muted mt-1 truncate">{c.prompt}</div>
                    )}
                  </div>
                  <div className="flex-none flex items-center gap-1.5">
                    {c.status !== 'approved' && (
                      <button className="btn btn-primary !px-2 text-xs"
                        onClick={() => act(() => api.approveCase(c.id), '操作失败')}><Check size={12} />通过</button>
                    )}
                    <Link to={`/objects/${objectId}/cases/${c.id}`} className="btn !px-2 text-xs"><Eye size={12} />详情</Link>
                    <button className="btn btn-danger !px-2 text-xs"
                      onClick={() => act(() => api.deleteCase(c.id), '删除失败')}><Trash2 size={12} />删除</button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {logicOpen && <CaseLogicModal onClose={() => setLogicOpen(false)} />}
    </div>
  )
}

/** Case 生成逻辑说明弹窗：从哪些方面生成 case、基于什么考虑。 */
function CaseLogicModal({ onClose }) {
  const rows = [
    {
      icon: FileInput,
      title: '生成依据（输入）',
      items: [
        '被测专家/专家团的定义：角色、权限、委派关系、工作流（读取 .opencode 配置）',
        '任务配置：任务名称与描述（来自 analyze_expert 分析结果）',
        '生成数量：默认 6 个，上限 12（超过 6 分批生成）',
      ],
    },
    {
      icon: Puzzle,
      title: '从哪些方面生成（场景覆盖）',
      items: [
        '结构化：精确产出 + 确定性断言 —— 产物可被程序自动校验（contains / regex / javascript）',
        '混合式：硬约束 + 专业判断 —— 产物正确性与专业质量并重',
        '开放式：高自主，只给目标与验收标准 —— 靠人工评审把关（断言可留空）',
        'case 之间按不同能力侧重分配，避免重复；任务性质明确时可侧重某类场景',
      ],
    },
    {
      icon: Brain,
      title: '基于什么考虑（设计原则）',
      items: [
        '匹配专家团编排：涉及团长的 case，prompt 要求委派对应团员、由团长验收汇总',
        '断言可自动化：使用 promptfoo 语法（contains/regex/javascript），javascript 用固定模板、禁止 require',
        '可评测性：产物位置一律用 {output_dir} 占位，严禁在 prompt 中写死文件路径',
        '规模可控：单个 case 须在 5 分钟内完成（opencode 运行窗口限制），聚焦 1 个明确功能、委派 ≤2 个团员',
      ],
    },
    {
      icon: CircleCheck,
      title: '审核闭环',
      items: [
        '生成模式可切换：「覆盖未审核」删除旧待审核用例再生成新一批；「追加」保留全部旧用例、只新增一批；两种模式都已审核通过的 case 保留、不重复生成',
        '人工审核：通过 → 供评测使用；编辑后保存 → 直接审核通过；删除 → 移除该 case',
        '评测只使用「已通过」的 case 集（评测引擎按 case.status=approved 过滤）',
      ],
    },
  ]
  return (
    <Modal open title="Case 生成逻辑" onClose={onClose} width="max-w-2xl">
      <div className="grid gap-4">
        {rows.map((r) => (
          <div key={r.title}>
            <div className="font-semibold text-sm flex items-center gap-1.5">
              <r.icon size={15} className="text-accent shrink-0" />{r.title}
            </div>
            <ul className="mt-1.5 space-y-1 text-sm text-muted">
              {r.items.map((it, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-accent shrink-0">·</span>
                  <span>{it}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="flex justify-end mt-5">
        <button className="btn btn-primary" onClick={onClose}><Check size={13} />知道了</button>
      </div>
    </Modal>
  )
}
