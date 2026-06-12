<template>
  <div class="messages-area" ref="messagesContainer">
    <!-- 欢迎提示 -->
    <div v-if="messages.length === 0" class="welcome-tip">
      <p class="welcome-greeting">你好！我是你的智能助手。</p>
      <p class="welcome-session">当前会话: <code>{{ sessionIdDisplay }}</code></p>
    </div>

    <!-- 消息循环 -->
    <div 
      v-for="(msg, index) in messages" 
      :key="index" 
      :class="['message', msg.role]"
    >
      <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
      
      <div class="content">
        <p v-if="msg.role === 'user'">{{ msg.content }}</p>
        <div 
          v-else 
          class="ai-content" 
          v-html="msg.renderedContent || parseMarkdown(msg.content)"
        ></div>
      </div>
    </div>
    
    <!-- 思考中消息框 -->
    <div v-if="isLoading" class="message ai loading">
      <div class="avatar">🤖</div>
      <div class="content thinking">
        <div class="thinking-indicator">
          <div class="thinking-dot"></div>
          <div class="thinking-dot"></div>
          <div class="thinking-dot"></div>
        </div>
        <span class="cursor">|</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  messages: {
    type: Array,
    required: true
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  currentSessionId: {
    type: String,
    default: ''
  }
})

const messagesContainer = ref(null)

const sessionIdDisplay = computed(() => {
  return props.currentSessionId ? `${props.currentSessionId.substring(0, 8)}...` : '...'
})

const parseMarkdown = (text) => {
  if (!text) return ''
  return marked.parse(text)
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// 监听消息变化自动滚动
watch(() => props.messages.length, () => {
  scrollToBottom()
}, { immediate: true })

watch(() => props.isLoading, () => {
  scrollToBottom()
})

defineExpose({
  scrollToBottom
})
</script>

<style scoped>
.messages-area {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
  scroll-behavior: smooth;
}

.welcome-tip {
  text-align: center;
  color: #9ca3af;
  margin-top: 80px;
  animation: fadeIn 0.5s ease-out;
}

.welcome-greeting {
  font-size: 24px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 12px 0;
}

.welcome-session {
  font-size: 13px;
  color: #9ca3af;
  margin: 0;
}

.welcome-session code {
  background-color: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Consolas', monospace;
  color: #6b7280;
}

.message { 
  display: flex; 
  align-items: flex-start; 
  max-width: 85%; 
  animation: popIn 0.3s ease-out; 
}
.message.user { 
  align-self: flex-end; 
  flex-direction: row-reverse; 
}
.message.ai { 
  align-self: flex-start; 
}

.message.ai.loading {
  opacity: 0.9;
}

.avatar { 
  width: 36px; 
  height: 36px; 
  border-radius: 50%; 
  display: flex; 
  align-items: center; 
  justify-content: center; 
  font-size: 18px; 
  flex-shrink: 0; 
}
.message.user .avatar { 
  background-color: #dbeafe; 
  margin-left: 12px; 
}
.message.ai .avatar { 
  background: linear-gradient(135deg, #60a5fa, #a78bfa); 
  margin-right: 12px; 
  color: white; 
  box-shadow: 0 2px 8px rgba(96, 165, 250, 0.3); 
}

.content { 
  padding: 12px 18px; 
  border-radius: 12px; 
  line-height: 1.6; 
  font-size: 15px; 
  word-break: break-word; 
  position: relative; 
  transition: height 0.2s ease, opacity 0.2s; 
  min-height: 20px; 
  opacity: 0.98; 
}

.content.thinking {
  min-height: 48px;
  min-width: 120px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.message.user .content { 
  background-color: #2563eb; 
  color: white; 
  border-bottom-right-radius: 4px; 
  box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2); 
}
.message.ai .content { 
  background-color: #ffffff; 
  border: 1px solid #e5e7eb; 
  color: #374151; 
  border-bottom-left-radius: 4px; 
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); 
}

.thinking-indicator {
  display: flex;
  gap: 4px;
  align-items: center;
}

.thinking-dot {
  width: 6px;
  height: 6px;
  background-color: #2563eb;
  border-radius: 50%;
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.thinking-dot:nth-child(1) {
  animation-delay: -0.32s;
}
.thinking-dot:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes thinkingBounce {
  0%, 80%, 100% { 
    transform: scale(0);
    opacity: 0.5;
  }
  40% { 
    transform: scale(1);
    opacity: 1;
  }
}

.cursor { 
  display: inline-block; 
  width: 2px; 
  height: 1em; 
  background-color: #2563eb; 
  margin-left: 2px; 
  vertical-align: text-bottom; 
  animation: blink 1s infinite; 
}

.ai-content {
  line-height: 1.6;
  color: #374151;
  font-size: 15px;
}

.ai-content h1, .ai-content h2, .ai-content h3 {
  margin-top: 24px;
  margin-bottom: 16px;
  font-weight: 600;
  line-height: 1.25;
  color: #1f2937;
}
.ai-content h1 { font-size: 24px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
.ai-content h2 { font-size: 20px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }
.ai-content h3 { font-size: 16px; }

.ai-content p { margin-top: 0; margin-bottom: 16px; }
.ai-content ul, .ai-content ol { padding-left: 2em; margin-bottom: 16px; }
.ai-content li { margin-bottom: 4px; }

.ai-content pre {
  background-color: #1f2937;
  color: #f3f4f6;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 16px 0;
}
.ai-content code {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.9em;
}
.ai-content :not(pre) > code {
  background-color: #f3f4f6;
  color: #ef4444;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em;
}

.ai-content blockquote {
  border-left: 4px solid #2563eb;
  padding-left: 16px;
  color: #6b7280;
  margin: 16px 0;
  font-style: italic;
}

.ai-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
}
.ai-content th, .ai-content td {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  text-align: left;
}
.ai-content th { background-color: #f9fafb; font-weight: 600; }

.ai-content { 
  white-space: pre-wrap; 
}

@keyframes popIn { 
  0% { opacity: 0; transform: scale(0.95) translateY(10px); } 
  100% { opacity: 1; transform: scale(1) translateY(0); } 
}
@keyframes fadeIn { 
  from { opacity: 0; } 
  to { opacity: 1; } 
}
@keyframes blink { 
  0%, 100% { opacity: 1; } 
  50% { opacity: 0; } 
}

@media (max-width: 768px) {
  .messages-area { padding: 16px; }
}
</style>