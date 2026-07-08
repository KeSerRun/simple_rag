// src/stores/admin.js
// 管理后台 API 封装
import { ref } from 'vue'
import { defineStore } from 'pinia'
import axios from '@/http/interceptor'

export const useAdminStore = defineStore('admin', () => {
  const loading = ref(false)
  const error = ref(null)

  // ─── 仪表盘 ──────────────────────────────────────────
  const dashboardData = ref(null)

  async function fetchDashboard() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/dashboard')
      dashboardData.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // ─── 配置 ────────────────────────────────────────────
  const configData = ref(null)

  async function fetchConfig() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/config')
      configData.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function updateConfig(updates) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.put('/api/admin/config', updates)
      await fetchConfig() // 刷新
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // ─── 用户管理 ────────────────────────────────────────
  const usersData = ref({ total: 0, items: [] })

  async function fetchUsers(page = 1, pageSize = 20) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/users', { params: { page, page_size: pageSize } })
      usersData.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createUser(username, password, role = 'user') {
    loading.value = true
    error.value = null
    try {
      const res = await axios.post('/api/admin/users', { username, password, role })
      await fetchUsers()
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function deleteUser(username) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.delete(`/api/admin/users/${encodeURIComponent(username)}`)
      await fetchUsers()
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function changeUserRole(username, role) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.put(`/api/admin/users/${encodeURIComponent(username)}/role`, { role })
      await fetchUsers()
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function resetUserPassword(username, password) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.put(`/api/admin/users/${encodeURIComponent(username)}/password`, { password })
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // ─── 日志 ────────────────────────────────────────────
  const logsData = ref({ files: [] })
  const logContent = ref(null)

  async function fetchLogFiles() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/logs')
      logsData.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchLogContent(logFile, lines = 200, offset = 0, reverse = false) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get(`/api/admin/logs/${encodeURIComponent(logFile)}`, {
        params: { lines, offset, reverse: reverse ? '1' : '0' },
      })
      logContent.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function downloadLogFile(logFile) {
    error.value = null
    try {
      const res = await axios.get(`/api/admin/logs/${encodeURIComponent(logFile)}/download`, {
        responseType: 'blob',
      })
      // 触发浏览器下载
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

  // ─── 数据库 ──────────────────────────────────────────
  const dbStats = ref(null)
  const dbChunks = ref({ total: 0, items: [] })
  const dbPartitions = ref({ partitions: [] })
  const dbIntegrity = ref(null)

  async function fetchDatabaseStats() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/database')
      dbStats.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchChunks(page = 1, pageSize = 20, filters = {}) {
    loading.value = true
    error.value = null
    try {
      const params = { page, page_size: pageSize, ...filters }
      const res = await axios.get('/api/admin/database/chunks', { params })
      dbChunks.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchPartitions() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/database/partitions')
      dbPartitions.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchIntegrityCheck() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/database/check_integrity')
      dbIntegrity.value = res.data
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // ─── 系统数据 ──────────────────────────────────────────
  const systemDocs = ref([])
  const uploadStatus = ref({ message: '', type: 'info' })
  const isUploading = ref(false)

  function setUploadStatus(message, type = 'info') {
    uploadStatus.value = { message, type }
  }

  async function fetchSystemDocs() {
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/database/system_docs')
      systemDocs.value = res.data?.documents || []
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function uploadSystemData(files) {
    loading.value = true
    error.value = null
    try {
      const formData = new FormData()
      for (const file of files) {
        formData.append('files', file)
      }
      const res = await axios.post('/api/admin/database/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      await fetchSystemDocs()
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function deleteDocument(source, partition) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.delete('/api/admin/database/delete', {
        params: { source, partition },
      })
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function batchDeleteDocuments(sources, partition) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.post('/api/admin/database/batch_delete', { sources, partition })
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // ─── 评估 ──────────────────────────────────────────
  const evalStatus = ref(null)
  const evalResults = ref(null)
  const evalReport = ref(null)

  async function runEval() {
    loading.value = true
    error.value = null
    evalResults.value = null
    evalReport.value = null
    try {
      const res = await axios.post('/api/admin/eval/run')
      evalStatus.value = res.data
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
    loading.value = true
    error.value = null
    try {
      const res = await axios.get('/api/admin/eval/queries')
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function updateEvalQueries(queries) {
    loading.value = true
    error.value = null
    try {
      const res = await axios.put('/api/admin/eval/queries', { queries })
      return res.data
    } catch (e) {
      error.value = e.response?.data?.detail || e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  return {
    loading, error,
    // dashboard
    dashboardData, fetchDashboard,
    // config
    configData, fetchConfig, updateConfig,
    // users
    usersData, fetchUsers, createUser, deleteUser, changeUserRole, resetUserPassword,
    // logs
    logsData, logContent, fetchLogFiles, fetchLogContent, downloadLogFile,
    // database
    dbStats, dbChunks, dbPartitions, dbIntegrity, fetchDatabaseStats, fetchChunks, fetchPartitions, fetchIntegrityCheck,
    // system data
    systemDocs, fetchSystemDocs, uploadSystemData, deleteDocument, batchDeleteDocuments,
    uploadStatus, setUploadStatus, isUploading,
    // eval
    evalStatus, evalResults, evalReport, runEval, fetchEvalStatus, fetchEvalQueries, updateEvalQueries,
  }
})
