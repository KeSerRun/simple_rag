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
      />

      <ChatInput
        :is-loading="isLoading"
        :is-uploading="isUploading"
        @send="sendQuestion"
        @upload="handleFileUpload"
      />
    </main>

    <DocManagerModal
      :is-open="isDocModalOpen"
      :documents="documentList"
      :is-deleting="isDeleting"
      @close="closeDocManager"
      @delete="confirmDeleteDocs"
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

const ALLOWED_EXTENSIONS = [
  'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'md', 'png', 'jpg', 'jpeg',
]
const MAX_FILE_SIZE = 100 * 1024 * 1024

const documentList = ref([])
const isDocModalOpen = ref(false)
const isDeleting = ref(false)
const drawerOpen = ref(true)

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
      '/api/clear_chosed_documents',
      { sources: docsToDelete },
      { headers: { 'Content-Type': 'application/json' } }
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
        newMessages.push(
          { role: 'user', content: msg.user },
          {
            role: 'ai',
            content: msg.assistant,
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

const sendQuestion = async (text) => {
  if (!text || isLoading.value) return

  messages.value.push({ role: 'user', content: text })
  isLoading.value = true
  throttleScroll()

  // 立即推入占位 AI 消息，后续通过索引替换来更新（触发 Vue 数组响应式）
  messages.value.push({ role: 'ai', content: '', renderedContent: '', _v: 0 })
  const aiIndex = messages.value.length - 1
  let aiContent = ''
  let aiVersion = 0
  sseBuffer = ''
  lastProcessedLength = 0

  try {
    await axios.post(
      '/api/query',
      { session_id: currentSessionId.value, question: text, stream: true },
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
              // 后端用 JSON 编码 token，这里解码（正确处理 \n、空格、特殊字符）
              let content
              try {
                content = JSON.parse(raw)
              } catch {
                // 兼容旧格式（如 [DONE] 等非 JSON）
                content = raw
              }
              if (!content) continue
              chunk += content
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
      _v: aiVersion,
    }
    message.error('请求失败，请重试')
  } finally {
    isLoading.value = false
    sseBuffer = ''
    nextTick(() => messageListRef.value?.scrollToBottom())
  }
}

// --- 文件上传 ---
const handleFileUpload = async (file) => {
  if (!file) return

  const v = validateFile(file)
  if (!v.valid) {
    message.error(v.msg)
    return
  }

  isUploading.value = true
  loadingBar.start()

  try {
    const formData = new FormData()
    formData.append('files', file)
    const sessionId = currentSessionId.value
    if (!sessionId) {
      message.error('会话 ID 缺失,请重新登录')
      return
    }
    const response = await axios.post('/api/upload_embeddings', formData, {
      headers: { 'X-Session-ID': sessionId },
    })
    if (response.status === 200) {
      message.success(`${file.name} 上传成功`)
      await fetchDocuments()
      loadingBar.finish()
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
</style>
