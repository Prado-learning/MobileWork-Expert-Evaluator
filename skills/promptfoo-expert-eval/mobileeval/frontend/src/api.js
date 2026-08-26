async function req(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `请求失败 ${res.status}`)
  return data
}

export const api = {
  // 专家/专家团（顶层）
  listObjects: () => req('/api/objects'),
  getObject: (id) => req(`/api/objects/${id}`),
  createObject: (body) => req('/api/objects', { method: 'POST', body: JSON.stringify(body) }),
  updateObject: (id, body) => req(`/api/objects/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteObject: (id) => req(`/api/objects/${id}`, { method: 'DELETE' }),
  listObjectAgents: (objectId) => req(`/api/objects/${objectId}/agents`),
  uploadObject: (formData) => req('/api/objects/upload', { method: 'POST', body: formData, headers: {} }),
  // 任务（挂在专家/专家团下）
  listTasks: (objectId) => req(`/api/objects/${objectId}/tasks`),
  getTask: (id) => req(`/api/tasks/${id}`),
  createTask: (objectId, body) => req(`/api/objects/${objectId}/tasks`, { method: 'POST', body: JSON.stringify(body) }),
  updateTask: (id, body) => req(`/api/tasks/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteTask: (id) => req(`/api/tasks/${id}`, { method: 'DELETE' }),
  // 运行（挂在任务下）
  listRuns: (params) => req(`/api/runs?${new URLSearchParams(params)}`),
  getRun: (id) => req(`/api/runs/${id}`),
  createRun: (taskId, body) => req(`/api/tasks/${taskId}/runs`, { method: 'POST', body: JSON.stringify(body) }),
  createObjectRun: (objectId, body) => req(`/api/objects/${objectId}/runs`, { method: 'POST', body: JSON.stringify(body) }),
  deleteRun: (id) => req(`/api/runs/${id}`, { method: 'DELETE' }),
  compareRuns: (ids) => req(`/api/runs/compare?ids=${ids.join(',')}`),
  // 报告 / 评审 / AI 工具（走插件脚本）
  getReport: (id) => req(`/api/runs/${id}/report`),
  getRunSession: (runId, sid) => req(`/api/runs/${runId}/session/${encodeURIComponent(sid)}`),
  listReviews: (runId) => req(`/api/runs/${runId}/reviews`),
  createReview: (runId, body) => req(`/api/runs/${runId}/reviews`, { method: 'POST', body: JSON.stringify(body) }),
  deleteReview: (id) => req(`/api/reviews/${id}`, { method: 'DELETE' }),
  invokeTool: (name, body) => req(`/api/assistant/tools/${name}`, { method: 'POST', body: JSON.stringify(body) }),
  listSuggestions: (runId) => req(`/api/runs/${runId}/suggestions`),
  // case 管理（对象导入后 AI 自动生成 + 人工审核）
  listCases: (objectId) => req(`/api/objects/${objectId}/cases`),
  generateCases: (objectId, count = 4, mode = 'replace') => req(`/api/objects/${objectId}/cases/generate`, { method: 'POST', body: JSON.stringify({ count, mode }) }),
  updateCase: (caseId, body) => req(`/api/cases/${caseId}`, { method: 'PUT', body: JSON.stringify(body) }),
  approveCase: (caseId) => req(`/api/cases/${caseId}/approve`, { method: 'POST' }),
  rejectCase: (caseId, note = '') => req(`/api/cases/${caseId}/reject`, { method: 'POST', body: JSON.stringify({ note }) }),
  deleteCase: (caseId) => req(`/api/cases/${caseId}`, { method: 'DELETE' }),
  // 专家导入 / 版本 / 优化 / 对比
  importExpert: (body) => req('/api/experts/import', { method: 'POST', body: JSON.stringify(body) }),
  listVersions: (objectId) => req(`/api/objects/${objectId}/versions`),
  restoreVersion: (objectId, version) => req(`/api/objects/${objectId}/versions/${version}/restore`, { method: 'POST' }),
  listOptimizations: (objectId) => req(`/api/objects/${objectId}/optimizations`),
  optimizeExpert: (objectId, body) => req(`/api/objects/${objectId}/optimize`, { method: 'POST', body: JSON.stringify(body) }),
  compareRunsPair: (base, opt) => req(`/api/compare?base=${base}&opt=${opt}`),
  // 对照实验
  listExperiments: (objectId) => req(`/api/experiments?object_id=${objectId || ''}`),
  createExperiment: (body) => req('/api/experiments', { method: 'POST', body: JSON.stringify(body) }),
  getExperiment: (id) => req(`/api/experiments/${id}`),
  // 全局评测模型
  listModels: () => req('/api/models'),
  createModel: (body) => req('/api/models', { method: 'POST', body: JSON.stringify(body) }),
  updateModel: (id, body) => req(`/api/models/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteModel: (id) => req(`/api/models/${id}`, { method: 'DELETE' }),
  browse: (path) => req(`/api/fs/browse?path=${encodeURIComponent(path || '')}`),
  // Expert Manager 桥接（AI 创建/编辑专家）
  expertManagerStatus: () => req('/api/expert-manager/status'),
  expertManagerGenerate: (body) => req('/api/expert-manager/generate', { method: 'POST', body: JSON.stringify(body) }),
}
