// src/stores/admin.js
// 管理后台 API 封装
import { ref } from 'vue'
import { defineStore } from 'pinia'
import axios from '@/http/interceptor'

export const useAdminStore = defineStore('admin', () => {
  const loading = ref(false)
  const error = ref(null)

  async function apiCall(fn) {
    loading.value = true
    error.value = null
    try {
      return await fn()
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // --- 仪表盘 ---
  const dashboardData = ref(null)

  async function fetchDashboard() {
    const res = await apiCall(() => axios.get('/api/admin/dashboard'))
    dashboardData.value = res.data
    return res.data
  }

  // --- 健康检查 ---
  const healthData = ref(null)
  const healthLoading = ref(false)

  async function fetchHealth() {
    healthLoading.value = true
    try {
      const res = await axios.get('/api/health/check')
      healthData.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      healthLoading.value = false
    }
  }

  // --- 配置 ---
  const configData = ref(null)

  async function fetchConfig() {
    const res = await apiCall(() => axios.get('/api/admin/config'))
    configData.value = res.data
    return res.data
  }

  const configSchema = ref([])

  async function fetchConfigSchema() {
    try {
      const res = await axios.get('/api/admin/config/schema')
      configSchema.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
    }
  }

  async function updateConfig(updates) {
    const res = await apiCall(() => axios.put('/api/admin/config', updates))
    await fetchConfig()
    return res.data
  }

  // --- 用户管理 ---
  const usersData = ref({ total: 0, items: [] })

  async function fetchUsers(page = 1, pageSize = 20) {
    const res = await apiCall(() => axios.get('/api/admin/users', { params: { page, page_size: pageSize } }))
    usersData.value = res.data
    return res.data
  }

  async function createUser(username, password, role = 'user') {
    const res = await apiCall(() => axios.post('/api/admin/users', { username, password, role }))
    await fetchUsers()
    return res.data
  }

  async function deleteUser(username) {
    const res = await apiCall(() => axios.delete(`/api/admin/users/${encodeURIComponent(username)}`))
    await fetchUsers()
    return res.data
  }

  async function changeUserRole(username, role) {
    const res = await apiCall(() => axios.put(`/api/admin/users/${encodeURIComponent(username)}/role`, { role }))
    await fetchUsers()
    return res.data
  }

  async function resetUserPassword(username, password) {
    return apiCall(() =>
      axios.put(`/api/admin/users/${encodeURIComponent(username)}/password`, { password })
    )
  }

  // --- 日志 ---
  const logsData = ref({ files: [] })
  const logContent = ref(null)

  async function fetchLogFiles() {
    const res = await apiCall(() => axios.get('/api/admin/logs'))
    logsData.value = res.data
    return res.data
  }

  async function fetchLogContent(logFile, lines = 200, offset = 0, reverse = false) {
    const res = await apiCall(() => axios.get(`/api/admin/logs/${encodeURIComponent(logFile)}`, {
      params: { lines, offset, reverse: reverse ? '1' : '0' },
    }))
    logContent.value = res.data
    return res.data
  }

  async function downloadLogFile(logFile) {
    error.value = null
    try {
      const res = await axios.get(`/api/admin/logs/${encodeURIComponent(logFile)}/download`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = logFile
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      return true
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  // --- 数据库 ---
  const dbStats = ref(null)
  const dbChunks = ref({ total: 0, items: [] })
  const dbPartitions = ref({ partitions: [] })
  const dbIntegrity = ref(null)

  async function fetchDatabaseStats() {
    const res = await apiCall(() => axios.get('/api/admin/database'))
    dbStats.value = res.data
    return res.data
  }

  async function fetchChunks(page = 1, pageSize = 20, filters = {}) {
    const params = { page, page_size: pageSize, ...filters }
    const res = await apiCall(() => axios.get('/api/admin/database/chunks', { params }))
    dbChunks.value = res.data
    return res.data
  }

  async function fetchPartitions() {
    const res = await apiCall(() => axios.get('/api/admin/database/partitions'))
    dbPartitions.value = res.data
    return res.data
  }

  async function fetchIntegrityCheck() {
    const res = await apiCall(() => axios.get('/api/admin/database/check_integrity'))
    dbIntegrity.value = res.data
    return res.data
  }

  // --- 系统数据 ---
  const systemDocs = ref([])
  const uploadStatus = ref({ message: '', type: 'info' })
  const isUploading = ref(false)

  function setUploadStatus(message, type = 'info') {
    uploadStatus.value = { message, type }
  }

  async function fetchSystemDocs() {
    const res = await apiCall(() => axios.get('/api/admin/database/system_docs'))
    systemDocs.value = res.data?.documents || []
    return res.data
  }

  async function uploadSystemData(files) {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    await apiCall(() => axios.post('/api/admin/database/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }))
    await fetchSystemDocs()
  }

  async function deleteDocument(source, partition) {
    await apiCall(() => axios.delete('/api/admin/database/delete', {
      params: { source, partition },
    }))
  }

  async function batchDeleteDocuments(sources, partition) {
    await apiCall(() => axios.post('/api/admin/database/batch_delete', { sources, partition }))
  }

  // --- 评估 ---
  const evalStatus = ref(null)
  const evalResults = ref(null)
  const evalReport = ref(null)
  const _EVAL_TASK_KEY = 'admin_eval_task_id'

  async function runEval() {
    loading.value = true
    error.value = null
    evalResults.value = null
    evalReport.value = null
    evalStatus.value = { status: 'running' }
    try {
      const res = await axios.post('/api/admin/eval/run')
      evalStatus.value = { ...res.data, status: 'running' }
      if (res.data?.task_id) {
        localStorage.setItem(_EVAL_TASK_KEY, res.data.task_id)
      }
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchEvalStatus(taskId) {
    error.value = null
    try {
      const res = await axios.get(`/api/admin/eval/status/${taskId}`)
      evalStatus.value = res.data
      if (res.data.status === 'finished' || res.data.status === 'failed' || res.data.status === 'no_results') {
        localStorage.removeItem(_EVAL_TASK_KEY)
      }
      if (res.data.status === 'finished') {
        evalResults.value = res.data.results
        evalReport.value = res.data.report
      }
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function fetchEvalQueries() {
    const res = await apiCall(() => axios.get('/api/admin/eval/queries'))
    return res.data
  }

  async function updateEvalQueries(queries) {
    const res = await apiCall(() => axios.put('/api/admin/eval/queries', { queries }))
    return res.data
  }

  async function pauseEval(taskId) {
    error.value = null
    try {
      await axios.post(`/api/admin/eval/pause/${taskId}`)
      evalStatus.value = { ...(evalStatus.value || {}), status: 'paused' }
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function resumeEval(taskId) {
    error.value = null
    try {
      await axios.post(`/api/admin/eval/resume/${taskId}`)
      evalStatus.value = { ...(evalStatus.value || {}), status: 'running' }
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    }
  }

  async function fetchLastEvalResult() {
    try {
      const res = await axios.get('/api/admin/eval/last')
      if (res.data.status === 'finished') {
        evalResults.value = res.data.results
        evalReport.value = res.data.report
        evalStatus.value = res.data
      }
      return res.data
    } catch (e) {
      return null
    }
  }

  async function loadRunningEval() {
    const taskId = localStorage.getItem(_EVAL_TASK_KEY)
    if (!taskId) return null
    try {
      const res = await axios.get(`/api/admin/eval/status/${taskId}`)
      evalStatus.value = res.data
      if (res.data.status === 'finished' || res.data.status === 'failed') {
        localStorage.removeItem(_EVAL_TASK_KEY)
        if (res.data.status === 'finished') {
          evalResults.value = res.data.results
          evalReport.value = res.data.report
        }
        return null
      }
      return taskId
    } catch {
      localStorage.removeItem(_EVAL_TASK_KEY)
      return null
    }
  }

  return {
    loading, error,
    dashboardData, fetchDashboard,
    healthData, healthLoading, fetchHealth,
    configData, configSchema, fetchConfig, fetchConfigSchema, updateConfig,
    usersData, fetchUsers, createUser, deleteUser, changeUserRole, resetUserPassword,
    logsData, logContent, fetchLogFiles, fetchLogContent, downloadLogFile,
    dbStats, dbChunks, dbPartitions, dbIntegrity, fetchDatabaseStats, fetchChunks, fetchPartitions, fetchIntegrityCheck,
    systemDocs, fetchSystemDocs, uploadSystemData, deleteDocument, batchDeleteDocuments,
    uploadStatus, setUploadStatus, isUploading,
    evalStatus, evalResults, evalReport, runEval, fetchEvalStatus, fetchEvalQueries, updateEvalQueries, pauseEval, resumeEval, fetchLastEvalResult, loadRunningEval,
  }
})
