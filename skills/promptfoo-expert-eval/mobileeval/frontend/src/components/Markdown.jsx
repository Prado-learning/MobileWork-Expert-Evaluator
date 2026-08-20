import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** AI 内容（优化建议/聊天回复）的 Markdown 渲染，样式对齐 MobileWork 设计系统。 */
export default function Markdown({ children }) {
  return (
    <div className="prose prose-sm prose-neutral max-w-none
                    prose-headings:font-semibold prose-h1:text-lg prose-h2:text-base prose-h3:text-sm
                    prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5
                    prose-table:text-xs prose-th:bg-page prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1
                    prose-pre:bg-page prose-pre:text-xs prose-code:before:content-none prose-code:after:content-none prose-code:text-accent prose-blockquote:border-accent/40 prose-blockquote:text-muted">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
