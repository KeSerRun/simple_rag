<template>
  <div class="messages-area" ref="messagesContainer">
    <!-- 欢迎屏 -->
    <div v-if="messages.length === 0" class="welcome">
      <div class="welcome-icon">
        <n-icon :size="40" :component="SparklesOutline" />
      </div>
      <n-h2 class="welcome-title">你好,我能帮你做什么?</n-h2>
      <n-text depth="3" class="welcome-sub">
        基于你上传的知识库,我可以回答相关问题。先上传文档,或直接开始提问。
      </n-text>
      <n-text depth="3" class="welcome-session" v-if="sessionIdDisplay">
        当前会话:&nbsp;<code>{{ sessionIdDisplay }}</code>
      </n-text>
    </div>

    <!-- 消息流 -->
    <div
      v-for="(msg, index) in messages"
      :key="index"
      :class="['message', msg.role]"
    >
      <div class="avatar-wrap">
        <n-avatar
          v-if="msg.role === 'user'"
          round
          size="small"
          :style="{ backgroundColor: '#dbeafe', color: '#1d4ed8' }"
        >
          <n-icon :component="PersonOutline" />
        </n-avatar>
        <n-avatar
          v-else
          round
          size="small"
          :style="{ backgroundColor: 'rgba(204, 120, 92, 0.15)', color: '#cc785c' }"
        >
          <n-icon :component="SparklesOutline" />
        </n-avatar>
      </div>

      <div class="bubble">
        <div v-if="msg.role === 'user'" class="user-content">{{ msg.content }}</div>
        <div
          v-else
          class="ai-content"
          v-html="msg.renderedContent || parseMarkdown(msg.content)"
        ></div>
      </div>
    </div>

    <!-- 思考中 -->
    <div v-if="isLoading" class="message ai">
      <div class="avatar-wrap">
        <n-avatar
          round
          size="small"
          :style="{ backgroundColor: 'rgba(204, 120, 92, 0.15)', color: '#cc785c' }"
        >
          <n-icon :component="SparklesOutline" />
        </n-avatar>
      </div>
      <div class="bubble thinking">
        <div class="thinking-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { marked } from 'marked'
import { NAvatar, NIcon, NH2, NText } from 'naive-ui'
import { PersonOutline, SparklesOutline } from '@vicons/ionicons5'

const props = defineProps({
  messages: { type: Array, required: true },
  isLoading: { type: Boolean, default: false },
  currentSessionId: { type: String, default: '' },
})

const messagesContainer = ref(null)

const sessionIdDisplay = computed(() =>
  props.currentSessionId ? `${props.currentSessionId.substring(0, 8)}...` : ''
)

const parseMarkdown = (text) => (text ? marked.parse(text) : '')

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

watch(() => props.messages.length, scrollToBottom, { immediate: true })
watch(() => props.isLoading, scrollToBottom)

defineExpose({ scrollToBottom })
</script>

<style scoped>
.messages-area {
  flex: 1;
  padding: 32px 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
  scroll-behavior: smooth;
}

.welcome {
  margin: 80px auto 0;
  max-width: 520px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  animation: fadeIn 0.4s ease-out;
}

.welcome-icon {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(204, 120, 92, 0.2), rgba(204, 120, 92, 0.05));
  color: #cc785c;
  margin-bottom: 8px;
}

.welcome-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
}

.welcome-sub {
  font-size: 14px;
  line-height: 1.6;
  max-width: 400px;
}

.welcome-session {
  margin-top: 8px;
  font-size: 12px;
}

.welcome-session code {
  font-family: 'Fira Code', Consolas, monospace;
  padding: 2px 6px;
  border-radius: 4px;
  background-color: rgba(120, 112, 104, 0.1);
  font-size: 11px;
}

.message {
  display: flex;
  gap: 12px;
  max-width: 100%;
  animation: messageIn 0.25s ease-out;
}

.message.user {
  flex-direction: row-reverse;
}

.avatar-wrap {
  flex-shrink: 0;
  padding-top: 2px;
}

.bubble {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 15px;
  line-height: 1.65;
  word-break: break-word;
  max-width: min(720px, 80%);
}

.message.user .bubble {
  background-color: rgba(204, 120, 92, 0.12);
  border-bottom-right-radius: 4px;
}

.message.ai .bubble {
  background-color: var(--n-card-color, #ffffff);
  border: 1px solid var(--n-divider-color, #e8e6e2);
  border-bottom-left-radius: 4px;
}

.user-content {
  white-space: pre-wrap;
  color: var(--n-text-color-1, #2c2825);
}

.bubble.thinking {
  padding: 14px 18px;
  display: flex;
  align-items: center;
  min-height: 24px;
}

.thinking-dots {
  display: flex;
  gap: 4px;
  align-items: center;
}

.thinking-dots span {
  width: 6px;
  height: 6px;
  background-color: #cc785c;
  border-radius: 50%;
  display: inline-block;
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.thinking-dots span:nth-child(1) {
  animation-delay: -0.32s;
}
.thinking-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes thinkingBounce {
  0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

@keyframes messageIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* AI 内容的 markdown 样式 */
.ai-content {
  color: var(--n-text-color-1, #2c2825);
}

.ai-content :deep(h1),
.ai-content :deep(h2),
.ai-content :deep(h3),
.ai-content :deep(h4) {
  margin-top: 18px;
  margin-bottom: 10px;
  font-weight: 600;
  line-height: 1.3;
}

.ai-content :deep(h1) {
  font-size: 22px;
}
.ai-content :deep(h2) {
  font-size: 18px;
}
.ai-content :deep(h3) {
  font-size: 16px;
}
.ai-content :deep(h4) {
  font-size: 15px;
}

.ai-content :deep(p) {
  margin: 8px 0;
}

.ai-content :deep(ul),
.ai-content :deep(ol) {
  padding-left: 1.5em;
  margin: 8px 0;
}

.ai-content :deep(li) {
  margin: 4px 0;
}

.ai-content :deep(pre) {
  background-color: rgba(40, 40, 40, 0.96);
  color: #e4e4e7;
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
  font-family: 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}

.ai-content :deep(code) {
  font-family: 'Fira Code', Consolas, monospace;
  font-size: 0.92em;
}

.ai-content :deep(:not(pre) > code) {
  background-color: rgba(120, 112, 104, 0.15);
  color: #cc785c;
  padding: 2px 6px;
  border-radius: 4px;
}

.ai-content :deep(blockquote) {
  border-left: 3px solid #cc785c;
  padding: 4px 14px;
  margin: 12px 0;
  color: var(--n-text-color-2, #5d5751);
  background-color: rgba(204, 120, 92, 0.05);
  border-radius: 0 6px 6px 0;
}

.ai-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 14px;
}

.ai-content :deep(th),
.ai-content :deep(td) {
  border: 1px solid var(--n-divider-color, #e8e6e2);
  padding: 8px 12px;
  text-align: left;
}

.ai-content :deep(th) {
  background-color: rgba(120, 112, 104, 0.06);
  font-weight: 600;
}

.ai-content :deep(a) {
  color: #cc785c;
  text-decoration: none;
}

.ai-content :deep(a):hover {
  text-decoration: underline;
}

.ai-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--n-divider-color, #e8e6e2);
  margin: 16px 0;
}

@media (max-width: 768px) {
  .messages-area {
    padding: 20px 16px;
  }
  .bubble {
    max-width: 100%;
  }
}
</style>
