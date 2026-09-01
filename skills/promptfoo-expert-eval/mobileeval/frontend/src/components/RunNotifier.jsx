import { useEffect, useRef, useState } from 'react'
import { Bell, BellOff } from 'lucide-react'

const POLL_MS = 5000
const LS_KEY = 'mobileeval.notify'
const BASE_TITLE = 'MobileEval 评测中心'
const ACTIVE = new Set(['running', 'pending'])
const STATUS_TEXT = { passed: '通过', failed: '未通过', error: '异常' }

/** 评测完成通知：轮询进行中的运行，结束后浏览器通知 + 页面标题闪烁。
 *  一轮评测约 10 分钟，用户通常切走干别的，完成时需要主动提醒。 */
export default function RunNotifier() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem(LS_KEY) === '1')
  const [denied, setDenied] = useState(false)
  const prevActive = useRef(null)   // 上一轮轮询的进行中运行 {id: run}，null=尚未初始化
  const flashTimer = useRef(null)

  // 标题闪烁：在「✅ 评测完成」与原标题间交替，用户回到页面即停止
  const startFlash = (run) => {
    if (flashTimer.current) return
    const label = `✅ 评测完成 #${run.id}${run.object_name ? `·${run.object_name}` : ''}`
    let on = true
    document.title = label
    flashTimer.current = setInterval(() => {
      on = !on
      document.title = on ? label : BASE_TITLE
    }, 1000)
  }
  useEffect(() => {
    const stop = () => {
      if (flashTimer.current) { clearInterval(flashTimer.current); flashTimer.current = null }
      document.title = BASE_TITLE
    }
    const onVisible = () => { if (!document.hidden) stop() }
    window.addEventListener('focus', stop)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stop()
      window.removeEventListener('focus', stop)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return undefined
    const timer = setInterval(async () => {
      let runs
      try {
        runs = await fetch('/api/runs').then((r) => r.json())
      } catch { return }
      if (!Array.isArray(runs)) return
      const active = {}
      runs.forEach((r) => { if (ACTIVE.has(r.status)) active[r.id] = r })
      if (prevActive.current) {
        for (const [id, run] of Object.entries(prevActive.current)) {
          const now = runs.find((r) => String(r.id) === id)
          // 上一轮还在跑、这轮已结束（且非用户主动中止）→ 提醒
          if (now && !ACTIVE.has(now.status) && now.status !== 'aborted') {
            const text = STATUS_TEXT[now.status] || now.status
            const body = `${now.object_name || ''} · 结果：${text}` +
              (now.score != null ? ` · 得分 ${Number(now.score).toFixed(2)}` : '')
            if ('Notification' in window && Notification.permission === 'granted') {
              try {
                new Notification(`评测完成：运行 #${now.id}`, { body, tag: `run-${now.id}` })
              } catch { /* 部分环境（如内嵌 WebView）不支持 Notification，忽略 */ }
            }
            startFlash(now)
          }
        }
      }
      prevActive.current = active
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [enabled])

  const toggle = async () => {
    if (enabled) {
      setEnabled(false)
      localStorage.setItem(LS_KEY, '0')
      return
    }
    if ('Notification' in window && Notification.permission === 'default') {
      const perm = await Notification.requestPermission()
      setDenied(perm === 'denied')
    } else if ('Notification' in window && Notification.permission === 'denied') {
      setDenied(true)
    }
    setEnabled(true)
    localStorage.setItem(LS_KEY, '1')
    prevActive.current = prevActive.current || {}
  }

  return (
    <button
      className={`fixed bottom-4 right-4 z-50 rounded-full border border-hairline shadow-md px-3 py-2 text-xs flex items-center gap-1.5 bg-surface hover:border-accent/50 ${enabled ? 'text-accent' : 'text-muted'}`}
      onClick={toggle}
      title={denied
        ? '浏览器已禁止通知（可在浏览器站点设置中开启），标题闪烁仍可用'
        : enabled ? '评测完成提醒：已开启（点击关闭）' : '评测完成提醒：已关闭（点击开启，浏览器通知 + 标题闪烁）'}
    >
      {enabled ? <Bell size={14} /> : <BellOff size={14} />}
      完成提醒
    </button>
  )
}
