<template>
  <div class="chat-container">
    <!-- 左侧：会话列表 -->
    <SessionSidebar :sessions="sessionList" :current-session-id="currentSessionId" :is-loading="isLoadingHistory"
      @create="createNewSession" @switch="switchSession" @delete="deleteSession" />

    <!-- 右侧：聊天主区域 -->
    <main class="chat-main">
      <ChatHeader :title="currentSessionTitle" :document-count="documentList.length" @open-doc-manager="openDocManager"
        @logout="handleLogout" />

      <MessageList ref="messageListRef" :messages="messages" :is-loading="isLoading"
        :current-session-id="currentSessionId" />

      <ChatInput :is-loading="isLoading" :is-uploading="isUploading" @send="sendQuestion" @upload="handleFileUpload" />
    </main>

    <!-- 文档管理弹窗 -->
    <DocManagerModal v-if="isDocModalOpen" :is-open="isDocModalOpen" :documents="documentList" :is-deleting="isDeleting"
      @close="closeDocManager" @delete="deleteSelectedDocs" />

    <!-- 上传加载遮罩 -->
    <UploadLoadingMask v-if="isUploading" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { generateNewId } from '@/utils/uuid'
import { marked } from 'marked'

// --- 组件导入 ---
// 对话侧边栏
import SessionSidebar from '../components/SessionSidebar.vue'
// 聊天头部
import ChatHeader from '../components/ChatHeader.vue'
// 消息列表
import MessageList from '../components/MessageList.vue'
// 聊天输入框
import ChatInput from '../components/ChatInput.vue'
// 文档管理弹窗
import DocManagerModal from '../components/DocManagerModal.vue'
// 上传加载遮罩
import UploadLoadingMask from '../components/UploadLoadingMask.vue'
// HTTP 客户端（带拦截器）
import axios from '@/http/interceptor'

const router = useRouter()
const userStore = useUserStore()

// --- 状态定义 ---
const question = ref('')
const messages = ref([])
const isLoading = ref(false)
const isUploading = ref(false)
const isLoadingHistory = ref(false)
const messageListRef = ref(null)
const sessionList = ref([])
const currentSessionId = ref('')
const ALLOWED_EXTENSIONS = [
  'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'md',
  'png', 'jpg', 'jpeg'
]
const MAX_FILE_SIZE = 100 * 1024 * 1024
const documentList = ref([])
const isDocModalOpen = ref(false)
const isDeleting = ref(false)

// 配置 marked 解析器
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false
})

// 计算属性：当前会话标题
const currentSessionTitle = computed(() => {
  const session = sessionList.value.find(s => s.id === currentSessionId.value)
  return session ? (session.title || '新会话') : '未命名'
})

// 获取文档列表
const fetchDocuments = async () => {
  try {
    const response = await axios.get(`/api/documents/${userStore.username}`)
    if (response.status === 200) {
      const data = await response.data
      documentList.value = data.documents || []
    } else {
      console.error('获取文档列表失败:', response.status)
      documentList.value = []
    }
  } catch (error) {
    console.error('获取文档列表失败:', error)
  }
}

// 打开文档管理弹窗
const openDocManager = () => {
  isDocModalOpen.value = true
  fetchDocuments()
}

// 关闭文档管理弹窗
const closeDocManager = () => {
  isDocModalOpen.value = false
}

// 删除选中文档
const deleteSelectedDocs = async (docsToDelete) => {
  if (!confirm(`确定要删除选中的 ${docsToDelete.length} 个文档吗？`)) return

  isDeleting.value = true

  try {
    const username = userStore.username || userStore.userInfo?.username
    const response = await axios.post('/api/clear_chosed_documents', {
      username: username,
      sources: docsToDelete
    }, {
      headers: { 'Content-Type': 'application/json' },
    })
    if (response.status === 200) {
      documentList.value = documentList.value.filter(
        docName => !docsToDelete.includes(docName)
      )
      alert('文档删除成功')
    } else {
      let errorMsg = '删除失败'
      try {
        const errorData = response.data
        errorMsg = errorData.detail || errorMsg
      } catch (parseError) {
        errorMsg = `删除失败 (HTTP ${response.status})`
      }
      alert(`删除失败: ${errorMsg}`)
    }
  } catch (error) {
    console.error('删除错误:', error)
    alert('网络错误')
  } finally {
    isDeleting.value = false
  }
}

// 文件验证函数
const validateFile = (file) => {
  const fileNameParts = file.name.split('.')
  const extension = fileNameParts.length > 1 ? fileNameParts.pop().toLowerCase() : ''
  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return { valid: false, message: `不支持的文件类型: ${file.name}` }
  }
  if (file.size > MAX_FILE_SIZE) {
    return { valid: false, message: `文件过大 (${file.name})，大小不能超过 100MB` }
  }
  return { valid: true }
}

// 加载用户会话列表
const fetchUserSessions = async () => {
  isLoadingHistory.value = true
  try {
    const username = userStore.username || userStore.userInfo?.username
    if (!username) {
      console.error("未找到用户名，无法加载会话列表")
      return
    }

    const response = await axios.get(`/api/sessions/${username}`)

    if (response.status === 200) {
      const data = response.data
      const backendSessions = data.sessions || []

      if (backendSessions.length > 0) {
        sessionList.value = backendSessions.map(s => ({
          id: typeof s === 'string' ? s : s.id,
          title: typeof s === 'string' ? '历史会话' : (s.title || '历史会话')
        }))

        const latestId = sessionList.value[sessionList.value.length - 1].id
        if (!currentSessionId.value || !sessionList.value.find(s => s.id === currentSessionId.value)) {
          switchSession(latestId)
        }
      } else {
        createNewSession()
      }
    } else {
      console.error('获取会话列表失败')
    }
  } catch (error) {
    console.error('网络错误:', error)
  } finally {
    isLoadingHistory.value = false
  }
}

// 创建新会话
const createNewSession = async () => {
  const newId = generateNewId()
  let backendSuccess = false

  try {
    const response = await axios.post('/api/create_session', {
      session_id: newId,
      username: userStore.username
    }, {
      headers: { 'Content-Type': 'application/json' }
    })
    if (response.status === 200) {
      backendSuccess = true
    } else {
      console.error('后端创建会话失败:', response.status)
    }
  } catch (error) {
    console.error('创建会话失败:', error)
  }

  const newSession = { id: newId, title: '新会话' }
  sessionList.value.unshift(newSession)
  switchSession(newId)
}

// 删除会话
const deleteSession = async (id) => {
  if (!confirm('确定要删除这个会话吗？此操作无法撤销。')) {
    return
  }
  try {
    const response = await axios.delete(`/api/sessions/${id}`)
    if (response.status === 200) {
      sessionList.value = sessionList.value.filter(s => s.id !== id)
      if (currentSessionId.value === id) {
        if (sessionList.value.length > 0) {
          switchSession(sessionList.value[0].id)
        } else {
          createNewSession()
        }
      }
      console.log('会话删除成功')
    } else {
      console.error('删除会话失败')
      alert('删除失败，请稍后重试。')
    }
  } catch (error) {
    console.error('网络错误:', error)
    alert('网络错误，请检查后端服务。')
  }
}

// 切换会话
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

// 加载历史消息
const loadHistoryMessages = async (sessionId) => {
  try {
    const response = await axios.get(`/api/history/${sessionId}`)

    if (response.status === 200) {
      let data = response.data

      const newMessages = []
      for (const msg of data.history || []) {
        newMessages.push(
          {
            role: 'user',
            content: msg.user
          },
          {
            role: 'ai',
            content: msg.assistant,
            renderedContent: marked.parse(msg.assistant || '')
          }
        )
      }
      messages.value = newMessages
    } else {
      messages.value = []
    }
  } catch (e) {
    messages.value = []
    console.warn('未连接真实后端，使用模拟数据')
  }
}

// 发送用户问题并处理 AI 响应，支持流式更新
import { nextTick, reactive } from 'vue'

// 节流滚动
let scrollTimer = null
const throttleScroll = () => {
  if (scrollTimer) return
  scrollTimer = requestAnimationFrame(() => {
    messageListRef.value?.scrollToBottom()
    scrollTimer = null
  })
}

// 记录上次处理位置，避免重复解析
let lastProcessedLength = 0

const sendQuestion = async (text) => {
  if (!text || isLoading.value) return

  messages.value.push({ role: 'user', content: text })
  isLoading.value = true
  throttleScroll()

  const aiMessage = reactive({
    role: 'ai',
    content: '',
    // 用 computed 自动缓存，避免每次全量 parse
    renderedContent: computed(() => marked.parse(aiMessage.content))
  })
  messages.value.push(aiMessage)

  lastProcessedLength = 0

  try {
    await axios.post('/api/query', {
      session_id: currentSessionId.value,
      question: text,
      stream: true
    }, {
      headers: { 'Content-Type': 'application/json' },
      responseType: 'text',
      onDownloadProgress: (progressEvent) => {
        const fullText = progressEvent.event.target.responseText || ''
        const newText = fullText.slice(lastProcessedLength)
        if (!newText) return

        lastProcessedLength = fullText.length

        // 提取 SSE data: 行
        const lines = newText.split('\n')
        let buffer = ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue

          const content = trimmed.slice(5).trim()
          if (content === '[DONE]') continue
          if (content) buffer += content
        }

        if (buffer) {
          aiMessage.content += buffer
          throttleScroll()
        }
      }
    })
  } catch (error) {
    console.error('请求失败:', error)
    aiMessage.content += '\n\n*[系统错误，请重试]*'
  } finally {
    isLoading.value = false
    nextTick(() => messageListRef.value?.scrollToBottom())
  }
}

// 处理文件上传
const handleFileUpload = async (event) => {
  const files = event.target.files
  if (!files || files.length === 0) return

  isUploading.value = true
  const invalidFiles = []
  for (let i = 0; i < files.length; i++) {
    const validationResult = validateFile(files[i])
    if (!validationResult.valid) {
      invalidFiles.push(validationResult.message)
    }
  }

  if (invalidFiles.length > 0) {
    alert(invalidFiles.join('\n'))
    isUploading.value = false
    event.target.value = ''
    return
  }

  try {
    const formData = new FormData()
    for (let i = 0; i < files.length; i++) {
      formData.append('files', files[i])
    }

    const username = userStore.username || userStore.userInfo?.username
    const sessionId = currentSessionId.value

    if (!username || !sessionId) {
      alert("用户信息或会话ID缺失，请重新登录。")
      isUploading.value = false
      return
    }

    const response = await axios.post('/api/upload_embeddings', formData, {
      headers: {
        'X-Session-ID': sessionId,
        'Username': username
      }
    })

    if (response.status === 200) {
      let data = response.data

      console.log('文件上传成功:', data.files)
      alert(`成功上传 ${data.files.length} 个文件！`)
      await fetchDocuments()
    } else {
      let errorMsg = '上传失败'
      try {
        const errorData = response.data
        errorMsg = errorData.detail || errorMsg
      } catch (parseError) {
        errorMsg = `上传失败 (HTTP ${response.status})`
      }
      console.error('上传失败:', errorMsg)
      alert(`上传失败: ${errorMsg}`)
    }
  } catch (error) {
    console.error('网络错误:', error)
    alert('网络错误，请检查后端服务。')
  } finally {
    isUploading.value = false
    event.target.value = ''
  }
}

// 退出登录
const handleLogout = () => {
  userStore.logout()
  router.push('/login')
}

// 页面加载时同时获取会话列表和文档列表
onMounted(() => {
  fetchUserSessions()
  if (userStore.role === 'admin') {
    fetchDocuments()
  }
})
</script>

<style scoped>
.chat-container {
  display: flex;
  height: 100vh;
  background-color: #f9fafb;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: #1f2937;
  overflow: hidden;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  min-width: 0;
}

@media (max-width: 768px) {
  .chat-container {
    padding: 0;
  }
}
</style>