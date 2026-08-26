import React, { useEffect, useState, useRef } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Save, RotateCcw, Plus, Trash2, Eye, Pencil } from 'lucide-react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { api } from '../api'
import { Empty, Spinner } from '../components/ui'

const ASSERT_TYPES = [
  ['contains', 'contains（包含文本）'], ['regex', 'regex（正则匹配）'],
  ['javascript', 'javascript（产物文件断言）'], ['llm-rubric', 'llm-rubric（业务评分）'],
  ['delegation', 'delegation（委派断言）'], ['tool-call', 'tool-call（工具调用）'],
  ['kb-hit', 'kb-hit（知识命中）'],
]
const TYPE_LABEL = Object.fromEntries(ASSERT_TYPES)
// 断言值展示文本（对象序列化）
const assertText = (v) => typeof v === 'object' ? JSON.stringify(v, null, 1) : (v ?? '')

/** 用例详情页：查看与编辑单个评测用例（分组卡片布局，代码区深色高亮）。 */
export default function CaseDetailPage() {
  const { objectId, caseId } = useParams()
  const navigate = useNavigate()
  const [form, setForm] = useState(null)
  const initialRef = useRef(null)   // 初始快照（用于"恢复"）
  const [assertMode, setAssertMode] = useState('form')
  const [jsonEdit, setJsonEdit] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listCases(objectId)
      .then((r) => {
        const c = (r.cases || []).find(x => String(x.id) === String(caseId))
        if (!c) { setError('未找到该用例'); return }
        const init = {
          title: c.title, type: c.type, prompt: c.prompt, output_dir: c.output_dir,
          assertions: JSON.stringify(c.assertions || [], null, 2),
          case_id: c.case_id, status: c.status,
        }
        initialRef.current = init
        setForm(init)
      })
      .catch((e) => setError(e.message))
  }, [objectId, caseId])

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const restore = () => {
    if (initialRef.current) setForm({ ...initialRef.current })
  }

  const save = async () => {
    if (!form) return
    setSaving(true); setError('')
    try {
      await api.updateCase(caseId, { ...form, assertions: JSON.parse(form.assertions || '[]') })
      await api.approveCase(caseId)   // 编辑保存即通过
      alert('保存成功')
      navigate(`/objects/${objectId}?tab=cases`)
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  if (!form && !error) return <Empty text="加载中…" />
  if (!form && error) return <div className="card !border-danger/40 text-danger">{error}</div>

  const num = String(form.case_id || '').replace(/\D/g, '')
  // 表单视图用的断言列表
  let assertions = []
  try { assertions = JSON.parse(form.assertions || '[]') } catch { /* JSON 视图编辑中 */ }
  const setAssertions = (list) => setForm((f) => ({ ...f, assertions: JSON.stringify(list, null, 2) }))
  // 按内容行数自适应 textarea 高度（min 3 / max 20 行）
  const autoRows = (val = '') => {
    const n = String(val).split('\n').length
    return Math.max(3, Math.min(20, n + 1))
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link to={`/objects/${objectId}`} className="btn !px-2.5" aria-label="返回"><ArrowLeft size={14} /></Link>
        <h1 className="text-xl font-semibold truncate">{num ? `用例 ${num} 详情` : '用例详情'}</h1>
        <div className="ml-auto flex gap-2">
          <button className="btn" onClick={restore} title="恢复到编辑前的内容"><RotateCcw size={13} />恢复</button>
          <button className="btn btn-primary" disabled={saving} onClick={save}>
            {saving ? <Spinner light /> : <><Save size={13} />保存</>}
          </button>
        </div>
      </div>
      {error && <div className="card !border-danger/40 text-danger mb-4">{error}</div>}

      {/* 基本信息 */}
      <div className="card mb-4">
        <h3 className="font-semibold mb-3">基本信息</h3>
        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <label className="label">标题</label>
            <input className="input" value={form.title} onChange={set('title')} />
          </div>
          <div>
            <label className="label">类型</label>
            <select className="input" value={form.type} onChange={set('type')}>
              <option value="structured">结构化</option>
              <option value="hybrid">混合式</option>
              <option value="open_ended">开放式</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="label">产物目录</label>
            <input className="input font-mono text-xs" value={form.output_dir} onChange={set('output_dir')} />
          </div>
        </div>
      </div>

      {/* 任务提示词（灰色代码区） */}
      <div className="card mb-4">
        <h3 className="font-semibold mb-3">任务提示词</h3>
        <textarea
          className="w-full rounded-default border border-hairline bg-[#f0f2f5] text-ink font-mono text-xs leading-relaxed px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-accent/40 resize-y"
          rows={14} value={form.prompt} onChange={set('prompt')}
        />
      </div>

      {/* 断言 */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold">断言</h3>
          <div className="flex items-center gap-1 border border-hairline rounded-default p-0.5">
            <button className={`px-2.5 py-1 text-xs rounded-default ${assertMode === 'form' ? 'bg-accent text-white font-medium' : 'text-muted hover:text-ink'}`}
              onClick={() => setAssertMode('form')}>表单</button>
            <button className={`px-2.5 py-1 text-xs rounded-default ${assertMode === 'json' ? 'bg-accent text-white font-medium' : 'text-muted hover:text-ink'}`}
              onClick={() => setAssertMode('json')}>JSON</button>
          </div>
        </div>
        {assertMode === 'json' ? (
          jsonEdit ? (
            <>
              <textarea className="w-full rounded-default border border-hairline bg-[#f0f2f5] text-ink font-mono text-xs leading-relaxed px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-accent/40 resize-y"
                rows={autoRows(form.assertions)} value={form.assertions} onChange={set('assertions')} />
              <div className="flex justify-end mt-2">
                <button className="btn text-xs" onClick={() => setJsonEdit(false)}><Eye size={12} />预览</button>
              </div>
            </>
          ) : (
            <div className="rounded-default overflow-hidden border border-hairline">
              <div className="flex items-center justify-between px-3 py-1.5 bg-[#e8eaef]">
                <span className="text-[11px] text-muted font-mono">assertions.json</span>
                <button className="btn !px-2 !py-0.5 text-xs" onClick={() => setJsonEdit(true)}><Pencil size={12} />编辑</button>
              </div>
              <SyntaxHighlighter language="json" style={oneLight} customStyle={{ margin: 0, fontSize: 12, maxHeight: 420 }}>
                {form.assertions || '[]'}
              </SyntaxHighlighter>
            </div>
          )
        ) : (
          <div className="divide-y divide-hairline">
            {assertions.map((a, i) => (
              <div key={i} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-muted">{TYPE_LABEL[a.type] || a.type || 'contains'}</span>
                  {a.type === 'llm-rubric' && a.metric && (
                    <span className="text-xs text-muted">· {a.metric}</span>
                  )}
                  <button type="button" className="ml-auto text-xs text-danger hover:underline inline-flex items-center gap-0.5 cursor-pointer"
                    onClick={() => {
                      if (window.confirm(`确认删除这条「${TYPE_LABEL[a.type] || a.type}」断言？`)) {
                        setAssertions(assertions.filter((_, j) => j !== i))
                      }
                    }}>
                    <Trash2 size={12} />删除
                  </button>
                </div>
                <pre className="w-full rounded-default border border-hairline bg-[#f0f2f5] text-ink font-mono text-[11px] leading-relaxed px-2.5 py-2 whitespace-pre-wrap break-all">{assertText(a.value)}</pre>
              </div>
            ))}
            {assertions.length === 0 && <div className="text-xs text-muted text-center py-2">暂无断言</div>}
            <div className="pt-3">
              <button className="btn text-xs" onClick={() => setAssertions([...assertions, { type: 'contains', value: '' }])}><Plus size={12} />添加断言</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
