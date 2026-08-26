import { useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import ObjectTree from './components/ObjectTree'
import ObjectsPage from './pages/ObjectsPage'
import ObjectDetailPage from './pages/ObjectDetailPage'
import RunReportPage from './pages/RunReportPage'
import VersionsPage from './pages/VersionsPage'
import OptimizePage from './pages/OptimizePage'
import ComparePage from './pages/ComparePage'
import ExperimentsPage from './pages/ExperimentsPage'
import ModelsPage from './pages/ModelsPage'
import CaseDetailPage from './pages/CaseDetailPage'

export default function App() {
  // AI 对话由 OpenWork 完成；本应用只负责评测数据的管理与可视化。
  const [navCollapsed, setNavCollapsed] = useState(true)

  return (
    <div className="h-screen flex overflow-hidden">
      <aside className={`flex-none border-r border-hairline transition-all duration-200 ${navCollapsed ? 'w-12' : 'w-64'}`}>
        <ObjectTree collapsed={navCollapsed} onToggleCollapse={() => setNavCollapsed((v) => !v)} />
      </aside>
      <main className="flex-1 overflow-y-auto bg-page/40">
        <div className="p-6 max-w-5xl">
          <Routes>
            <Route path="/" element={<Navigate to="/objects" replace />} />
            <Route path="/objects" element={<ObjectsPage />} />
            <Route path="/objects/:objectId" element={<ObjectDetailPage />} />
            <Route path="/objects/:objectId/cases/:caseId" element={<CaseDetailPage />} />
            <Route path="/objects/:objectId/versions" element={<VersionsPage />} />
            <Route path="/objects/:objectId/optimize" element={<OptimizePage />} />
            <Route path="/objects/:objectId/experiments" element={<ExperimentsPage />} />
            <Route path="/compare/:objectId" element={<ComparePage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/runs/:runId" element={<RunReportPage />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}
