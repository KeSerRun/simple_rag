<template>
  <div class="chat-container">
    <SessionSidebar
      :sessions="sessionList"
      :current-session-id="currentSessionId"
      :is-loading="isLoadingHistory"
      :drawer-open="drawerOpen"
      @create="createNewSession"
      @switch="switchSession"
      @delete="confirmDeleteSession"
      @close="drawerOpen = false"
    />

    <main class="chat-main">
      <ChatHeader
        :title="currentSessionTitle"
        :document-count="documentList.length"
        @open-doc-manager="openDocManager"
        @logout="handleLogout"
        @toggle-sidebar="drawerOpen = !drawerOpen"
      />

      <MessageList
        ref="messageListRef"
        :messages="messages"
        :is-loading="isLoading"
        :current-session-id="currentSessionId"
        :status-text="agentStatus.visible ? agentStatus.text : ''"
      />

      <ChatInput
        :is-loading="isLoading"
        :is-uploading="isUploading"
        @send="sendQuestion"
        @stop="stopGeneration"
        @upload="handleFileUpload"
      />

      <!-- 上传进度条 -->
      <div v-if="uploadStatus.visible" class="upload-status-bar">
        <div class="upload-dot"></div>
        <span class="upload-label">{{ uploadStatus.text }}</span>
        <span v-if="uploadStatus.file" class="upload-file" :title="uploadStatus.file">{{ truncateFilename(uploadStatus.file) }}</span>
      </div>
    </main>

    <DocManagerModal
      :is-open="isDocModalOpen"
      :documents="documentList"
      :is-deleting="isDeleting"
      @close="closeDocManager"
      @delete="confirmDeleteDocs"
      @open="openDocument"
      @refresh="fetchDocuments"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { renderMarkdown } from '@/utils/markdown'
import { useMessage, useDialog, useLoadingBar } from 'naive-ui'

import { useUserStore } from '@/stores/user'
import { generateNewId } from '@/utils/uuid'
import axios from '@/http/interceptor'

import SessionSidebar from '@/components/SessionSidebar.vue'
import ChatHeader from '@/components/ChatHeader.vue'
import MessageList from '@/components/MessageList.vue'
import ChatInput from '@/components/ChatInput.vue'
import DocManagerModal from '@/components/DocManagerModal.vue'

const router = useRouter()
const userStore = useUserStore()
const message = useMessage()
const dialog = useDialog()
const loadingBar = useLoadingBar()

// --- 状态 ---
const messages = ref([])
const isLoading = ref(false)
const isUploading = ref(false)
const isLoadingHistory = ref(false)
const messageListRef = ref(null)
const sessionList = ref([])
const currentSessionId = ref('')

const ALLOWED_EXTENSIONS = ['pdf', 'txt', 'md']
const MAX_FILE_SIZE = 100 * 1024 * 1024

const documentList = ref([])
const isDocModalOpen = ref(false)
const isDeleting = ref(false)
const drawerOpen = ref(false)

// 格式化会话标题：首条消息摘要 + 相对时间
const formatSessionTitle = (firstMsg, createdAt) => {
  const msg = firstMsg ? (firstMsg.length > 20 ? firstMsg.slice(0, 20) + '...' : firstMsg) : ''
  const time = createdAt ? relativeTime(createdAt) : ''
  if (msg && time) return `${msg} · ${time}`
  if (msg) return msg
  return time ? `新会话 · ${time}` : '新会话'
}

const relativeTime = (isoStr) => {
  const now = Date.now()
  const then = new Date(isoStr).getTime()
  const diff = Math.floor((now - then) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 172800) return '昨天'
  return `${Math.floor(diff / 86400)}天前`
}

const currentSessionTitle = computed(() => {
  const session = sessionList.value.find((s) => s.id === currentSessionId.value)
  return session ? session.title || '新会话' : '新会话'
})

// --- 文档管理 ---
const fetchDocuments = async () => {
  try {
    const response = await axios.get(`/api/documents/${userStore.username}`)
    if (response.status === 200) {
      documentList.value = response.data.documents || []
    }
  } catch (error) {
    console.error('获取文档列表失败:', error)
  }
}

const openDocManager = () => {
  isDocModalOpen.value = true
  fetchDocuments()
}

const closeDocManager = () => {
  isDocModalOpen.value = false
}

// 双击文档: 通过 axios 带 JWT 拿 blob, 浏览器新标签打开 (PDF 直接预览, 其它走下载)
const openDocument = async (docName) => {
  try {
    const response = await axios.get(
      `/api/documents/file/${encodeURIComponent(docName)}`,
      { responseType: 'blob' }
    )
    const url = URL.createObjectURL(response.data)
    const win = window.open(url, '_blank')
    if (!win) {
      // 弹窗被拦截时回退为下载
      const a = document.createElement('a')
      a.href = url
      a.download = docName
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    }
    // 留一点时间让新窗口加载完再释放
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    const detail = error.response?.status === 404 ? '原文件已不存在' : '打开失败'
    message.error(detail)
  }
}

const confirmDeleteDocs = (docsToDelete) => {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除选中的 ${docsToDelete.length} 个文档吗?该操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteSelectedDocs(docsToDelete),
  })
}

const deleteSelectedDocs = async (docsToDelete) => {
  isDeleting.value = true
  try {
    const response = await axios.post(
      '/api/clear_chosen_documents',
      { sources: docsToDelete },
      {
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': currentSessionId.value || '',
        },
      }
    )
    if (response.status === 200) {
      documentList.value = documentList.value.filter(
        (docName) => !docsToDelete.includes(docName)
      )
      message.success('文档删除成功')
    }
  } catch (error) {
    const detail = error.response?.data?.detail || '删除失败'
    message.error(detail)
  } finally {
    isDeleting.value = false
  }
}

// --- 文件验证 ---
const validateFile = (file) => {
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return { valid: false, msg: `不支持的文件类型: ${file.name}` }
  }
  if (file.size > MAX_FILE_SIZE) {
    return { valid: false, msg: `${file.name} 大小超过 100MB` }
  }
  return { valid: true }
}

// --- 会话管理 ---
const fetchUserSessions = async () => {
  isLoadingHistory.value = true
  try {
    if (!userStore.username) {
      console.error('未找到用户名')
      return
    }
    const response = await axios.get(`/api/sessions/${userStore.username}`)
    if (response.status === 200) {
      const backendSessions = response.data.sessions || []
      if (backendSessions.length > 0) {
        sessionList.value = backendSessions.map((s) => ({
          id: s.id,
          title: formatSessionTitle(s.first_msg, s.created_at),
        }))
        const latestId = sessionList.value[sessionList.value.length - 1].id
        if (
          !currentSessionId.value ||
          !sessionList.value.find((s) => s.id === currentSessionId.value)
        ) {
          switchSession(latestId)
        }
      } else {
        createNewSession()
      }
    }
  } catch (error) {
    console.error('获取会话列表失败:', error)
  } finally {
    isLoadingHistory.value = false
  }
}

const createNewSession = async () => {
  const newId = generateNewId()
  try {
    await axios.post(
      '/api/create_session',
      { session_id: newId },
      { headers: { 'Content-Type': 'application/json' } }
    )
  } catch (error) {
    console.error('创建会话失败:', error)
  }
  sessionList.value.unshift({ id: newId, title: '新会话' })
  switchSession(newId)
}

const confirmDeleteSession = (id) => {
  // SessionSidebar 已经用 Popconfirm 做了二次确认,这里直接执行
  deleteSession(id)
}

const deleteSession = async (id) => {
  try {
    const response = await axios.delete(`/api/sessions/${id}`)
    if (response.status === 200) {
      sessionList.value = sessionList.value.filter((s) => s.id !== id)
      if (currentSessionId.value === id) {
        if (sessionList.value.length > 0) {
          switchSession(sessionList.value[0].id)
        } else {
          await createNewSession()
        }
      }
      message.success('会话已删除')
    }
  } catch (error) {
    message.error('删除会话失败')
  }
}

const switchSession = async (id) => {
  if (id === currentSessionId.value) return
  currentSessionId.value = id
  messages.value = []
  isLoading.value = true
  try {
    await loadHistoryMessages(id)
  } catch (error) {
    console.error('加载历史失败', error)
  } finally {
    isLoading.value = false
  }
}

const loadHistoryMessages = async (sessionId) => {
  try {
    const response = await axios.get(`/api/history/${sessionId}`)
    if (response.status === 200) {
      const data = response.data
      const newMessages = []
      for (const msg of data.history || []) {
        // 事件条目 (upload/delete) 不在聊天界面渲染, 仅供后端注入 LLM 上下文
        // 同时防御没有 user/assistant 字段的条目, 避免渲染出空白气泡
        if (msg.type === 'event') continue
        if (msg.user == null && msg.assistant == null) continue
        newMessages.push(
          { role: 'user', content: msg.user || '' },
          {
            role: 'ai',
            content: msg.assistant || '',
            renderedContent: renderMarkdown(msg.assistant || ''),
          }
        )
      }
      messages.value = newMessages
    } else {
      messages.value = []
    }
  } catch (e) {
    messages.value = []
  }
}

// --- 提问与流式 ---
let scrollTimer = null
const throttleScroll = () => {
  if (scrollTimer) return
  scrollTimer = requestAnimationFrame(() => {
    messageListRef.value?.scrollToBottom()
    scrollTimer = null
  })
}

let lastProcessedLength = 0
let sseBuffer = ''

// Agent 状态追踪
const agentStatus = ref({ visible: false, text: '' })

const statusLabels = {
  thinking: '深度思考中…',
  calling_tool: (info) => {
    const prefix = info.total ? `[${info.total}个工具] ` : ''
    if (info.tool === 'search_knowledge_base' && info.query) {
      const q = Array.isArray(info.query) ? info.query.join(', ') : info.query
      return `${prefix}正在检索知识库: ${q}…`
    }
    if (info.tool === 'read_full_document' && info.filename) {
      return `${prefix}正在阅读: ${info.filename}…`
    }
    if (info.tool === 'web_search' && info.query) {
      const q = Array.isArray(info.query) ? info.query[0] : info.query
      return `${prefix}正在联网搜索: ${q}…`
    }
    const toolNames = {
      search_knowledge_base: `${prefix}正在检索知识库…`,
      read_full_document: `${prefix}正在阅读文档全文…`,
      web_search: `${prefix}正在联网搜索…`,
    }
    return toolNames[info.tool] || `${prefix}正在调用工具: ${info.tool}…`
  },
  tool_result: (info) => {
    if (info.chunks !== undefined) {
      return `✅ 检索完成，找到 ${info.chunks} 条结果`
    }
    if (info.tool === 'web_search') {
      return `✅ 联网搜索完成`
    }
    if (info.tool === 'read_full_document') {
      return `✅ 文档阅读完成`
    }
    if (info.tool === 'ask_user_for_clarification') {
      return '❓ 需要向您提问'
    }
    return ''
  },
}

const sendQuestion = async (text) => {
  if (!text || isLoading.value) return

  messages.value.push({ role: 'user', content: text })
  isLoading.value = true
  throttleScroll()

  // 立即推入占位 AI 消息，后续通过索引替换来更新（触发 Vue 数组响应式）
  messages.value.push({ role: 'ai', content: '', renderedContent: '', reasoning: '', reasoningRendered: '', _v: 0 })
  const aiIndex = messages.value.length - 1
  let aiContent = ''
  let aiReasoning = ''
  let aiVersion = 0
  sseBuffer = ''
  lastProcessedLength = 0

  try {
    await axios.post(
      '/api/query',
      { session_id: currentSessionId.value, question: text, stream: true, style: userStore.answerStyle },
      {
        headers: { 'Content-Type': 'application/json' },
        responseType: 'text',
        onDownloadProgress: (progressEvent) => {
          const fullText = progressEvent.event.target.responseText || ''
          const newText = fullText.slice(lastProcessedLength)
          if (!newText) return
          lastProcessedLength = fullText.length

          // SSE buffer：只处理以 \n\n 结尾的完整事件，碎片留到下次
          sseBuffer += newText
          const events = sseBuffer.split('\n\n')
          sseBuffer = events.pop() || ''

          let chunk = ''
          for (const event of events) {
            const lines = event.split('\n')
            for (const line of lines) {
              const trimmed = line.trim()
              if (!trimmed.startsWith('data:')) continue
              const raw = trimmed.slice(5)
              if (!raw || raw === '[DONE]') continue
              // 后端用 JSON 编码事件，这里解码
              let content
              try {
                content = JSON.parse(raw)
              } catch {
                // 兼容旧格式（如 [DONE] 等非 JSON）
                content = raw
              }
              if (!content) continue

              // 处理状态事件（tool call / thinking）
              if (typeof content === 'object') {
                if (content.type === 'status') {
                  const label = statusLabels[content.status]
                  if (content.status === 'thinking' || content.status === 'calling_tool') {
                    agentStatus.value = {
                      visible: true,
                      text: typeof label === 'function' ? label(content) : (label || '处理中…'),
                    }
                  } else if (content.status === 'tool_result') {
                    // 显示结果摘要（如 "检索完成，找到 5 条结果"），下次 thinking/calling_tool 会覆盖
                    const summary = typeof label === 'function' ? label(content) : ''
                    if (summary) {
                      agentStatus.value = { visible: true, text: summary }
                    } else {
                      agentStatus.value = { visible: false, text: '' }
                    }
                  } else if (content.status === 'cancelled') {
                    // 中断事件：在消息列表中插入中断提示
                    const cancelMsg = {
                      role: 'ai',
                      content: '',
                      renderedContent: '',
                      isCancelled: true,
                    }
                    messages.value[aiIndex] ?
                      Object.assign(messages.value[aiIndex], cancelMsg) :
                      messages.value.push(cancelMsg)
                    agentStatus.value = { visible: false, text: '' }
                  }
                  continue
                }
                if (content.type === 'token') {
                  // 首个 token 到达时清除状态
                  agentStatus.value = { visible: false, text: '' }
                  chunk += content.text || ''
                  continue
                }
                if (content.type === 'reasoning') {
                  // 推理过程（思考链），单独累积，不混入主回答
                  aiReasoning += (content.text || '')
                  messages.value[aiIndex] = {
                    role: 'ai',
                    content: aiContent,
                    renderedContent: renderMarkdown(aiContent),
                    reasoning: aiReasoning,
                    reasoningRendered: renderMarkdown(aiReasoning),
                    _v: aiVersion,
                  }
                  throttleScroll()
                  continue
                }
              }

              // 旧格式（纯字符串 token）
              if (typeof content === 'string') {
                chunk += content
              }
            }
          }

          if (chunk) {
            aiContent += chunk
            aiVersion++
            // 索引替换触发 Vue 数组响应式
            messages.value[aiIndex] = {
              role: 'ai',
              content: aiContent,
              renderedContent: renderMarkdown(aiContent),
              reasoning: aiReasoning,
              reasoningRendered: aiReasoning ? renderMarkdown(aiReasoning) : '',
              _v: aiVersion,
            }
            throttleScroll()
          }
        },
      }
    )
  } catch (error) {
    aiContent += '\n\n*[系统错误，请重试]*'
    aiVersion++
    messages.value[aiIndex] = {
      role: 'ai',
      content: aiContent,
      renderedContent: renderMarkdown(aiContent),
      reasoning: aiReasoning,
      reasoningRendered: aiReasoning ? renderMarkdown(aiReasoning) : '',
      _v: aiVersion,
    }
    message.error('请求失败，请重试')
  } finally {
    isLoading.value = false
    sseBuffer = ''
    nextTick(() => messageListRef.value?.scrollToBottom())
  }
}

const stopGeneration = async () => {
  try {
    await axios.post('/api/query/cancel', { session_id: currentSessionId.value })
  } catch {
    // 忽略取消请求的异常
  }
}

// --- 文件上传 ---
const uploadStatus = ref({ visible: false, text: '', file: '' })

const truncateFilename = (name) => {
  if (!name || name.length <= 40) return name
  const ext = name.lastIndexOf('.')
  if (ext > 0) {
    const stem = name.slice(0, 20) + '…' + name.slice(ext)
    return stem
  }
  return name.slice(0, 40) + '…'
}

const handleFileUpload = async (file) => {
  if (!file) return

  const v = validateFile(file)
  if (!v.valid) {
    message.error(v.msg)
    return
  }

  isUploading.value = true
  uploadStatus.value = { visible: true, text: '准备上传…' }
  loadingBar.start()

  try {
    const formData = new FormData()
    formData.append('files', file)
    const sessionId = currentSessionId.value
    if (!sessionId) {
      message.error('会话 ID 缺失,请重新登录')
      return
    }

    // SSE 流式上传: 实时接收处理进度
    let sseBuf = ''
    let uploadDone = false
    let fileResult = null

    await axios.post('/api/upload_embeddings?stream=true', formData, {
      headers: { 'X-Session-ID': sessionId },
      responseType: 'text',
      onDownloadProgress: (progressEvent) => {
        const fullText = progressEvent.event.target.responseText || ''
        const newText = fullText.slice(sseBuf ? fullText.indexOf(sseBuf.slice(-20)) + 20 : 0)
        if (!newText) return
        sseBuf = fullText

        const events = fullText.split('\n\n')
        for (const raw of events) {
          const match = raw.match(/^data:\s*(.+)$/m)
          if (!match) continue
          try {
            const data = JSON.parse(match[1])
            if (data.status === 'done') {
              uploadDone = true
              fileResult = data.files
              uploadStatus.value = { visible: true, text: data.text || '上传完成' }
              continue
            }
            if (data.text) {
              uploadStatus.value = {
                visible: true,
                text: data.text,
                file: data.file || uploadStatus.value.file || '',
              }
            }
          } catch { /* skip parse errors */ }
        }
      },
    })

    // 等待 done 事件或直接完成
    if (fileResult && fileResult.length > 0) {
      message.success(`${file.name} 上传成功`)
      await fetchDocuments()
      loadingBar.finish()
    } else if (uploadDone) {
      message.warning('文件处理失败，请检查 MinerU 服务是否正常')
      loadingBar.error()
    } else {
      loadingBar.error()
      message.error('上传失败')
    }
  } catch (error) {
    loadingBar.error()
    const detail = error.response?.data?.detail || '上传失败'
    message.error(detail)
  } finally {
    isUploading.value = false
    uploadStatus.value = { visible: false, text: '' }
  }
}

const handleLogout = () => {
  dialog.warning({
    title: '退出登录',
    content: '确定要退出当前账号吗?',
    positiveText: '退出',
    negativeText: '取消',
    onPositiveClick: () => {
      userStore.logout()
      router.push('/login')
    },
  })
}

onMounted(() => {
  fetchUserSessions()
  fetchDocuments()
})
</script>

<style scoped>
.chat-container {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
  background-color: transparent;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background-color: transparent;
}

.upload-status-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid var(--n-divider-color, #d4cfc8);
  background-color: var(--n-card-color, #ffffff);
  animation: fadeIn 0.2s ease-out;
}

.upload-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #d4734e;
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.upload-label {
  font-size: 13px;
  color: var(--n-text-color-3, #6e6760);
  flex-shrink: 0;
}

.upload-file {
  font-size: 12px;
  color: var(--n-text-color-2, #4a4440);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
  direction: rtl;
  text-align: left;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
