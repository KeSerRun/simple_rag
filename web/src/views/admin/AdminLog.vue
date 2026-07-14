<template>
  <div class="log-page">
    <n-h2>日志查看</n-h2>

    <n-grid cols="4" :x-gap="16" :y-gap="16">
        <!-- 左侧: 文件快捷入口 -->
        <n-grid-item span="1">
          <n-card title="日志文件" :bordered="true" size="small" style="height: 100%">
            <n-space vertical :size="6">
              <n-button
                v-for="item in quickLogs"
                :key="item.name"
                size="small"
                :type="selectedFile === item.name ? 'primary' : 'default'"
                secondary
                style="justify-content: flex-start"
                @click="selectFile(item.name)"
              >
                <template #icon>
                  <n-icon :component="item.icon" />
                </template>
                {{ item.label }}
              </n-button>
            </n-space>
          </n-card>
        </n-grid-item>

        <!-- 右侧: 日志内容 -->
        <n-grid-item span="3">
          <n-card :title="selectedFile || '选择日志文件'" :bordered="true" size="small">
            <!-- 控制栏 -->
            <template #header-extra>
              <n-space :size="8" v-if="selectedFile">
                <n-select
                  v-model:value="pageSize"
                  :options="pageSizeOptions"
                  size="small"
                  style="width: 90px"
                />
                <n-button size="small" @click="loadPrev">上一页</n-button>
                <n-button size="small" @click="loadNext">下一页</n-button>
                <n-button size="small" @click="loadLatest">最新</n-button>
                <n-button size="small" @click="refreshLog">刷新</n-button>
                <n-button size="small" type="primary" secondary @click="handleDownload">下载</n-button>
              </n-space>
            </template>

            <div v-if="!selectedFile" class="no-file-hint">
              <n-empty description="请从左侧选择一个日志文件" />
            </div>
            <div v-else-if="store.loading" class="loading-center">
              <n-spin size="large" />
            </div>
            <div v-else class="log-content" ref="logContainerRef">
              <div v-if="store.logContent">
                <div class="log-info">
                  <n-text depth="3" style="font-size: 12px">
                    共 {{ store.logContent.total }} 行 · 显示 {{ store.logContent.start + 1 }} ~ {{ store.logContent.end }} 行
                  </n-text>
                </div>
                <pre class="log-pre"><code>{{ logText }}</code></pre>
              </div>
            </div>
          </n-card>
        </n-grid-item>
      </n-grid>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { useAdminStore } from '@/stores/admin'
import {
  NCard, NGrid, NGridItem, NText, NEmpty, NSpin,
  NSpace, NSelect, NButton, NH2, NIcon,
} from 'naive-ui'
import {
  ServerOutline,
  ChatbubblesOutline,
  PeopleOutline,
  TerminalOutline,
} from '@vicons/ionicons5'

const store = useAdminStore()
const message = useMessage()

const quickLogs = [
  { name: 'app.log', label: '应用日志', icon: ServerOutline },
  { name: 'http.log', label: 'HTTP 日志', icon: ChatbubblesOutline },
  { name: 'user.log', label: '用户日志', icon: PeopleOutline },
  { name: 'input.log', label: 'LLM 输入日志', icon: TerminalOutline },
]

const selectedFile = ref('')
const currentOffset = ref(0)
const pageSize = ref(200)

const pageSizeOptions = [
  { label: '100 行', value: 100 },
  { label: '200 行', value: 200 },
  { label: '500 行', value: 500 },
  { label: '1000 行', value: 1000 },
]

const logText = computed(() => {
  if (!store.logContent?.lines) return ''
  return store.logContent.lines.join('\n')
})

function selectFile(name) {
  selectedFile.value = name
  currentOffset.value = 0
  loadLatest()
}

function loadLatest() {
  if (!selectedFile.value) return
  store.fetchLogContent(selectedFile.value, pageSize.value, 0, true)
}

function loadNext() {
  if (!store.logContent) return
  const total = store.logContent.total
  const end = store.logContent.end
  if (end >= total) {
    loadLatest()
    return
  }
  currentOffset.value = end
  store.fetchLogContent(selectedFile.value, pageSize.value, currentOffset.value, false)
}

function loadPrev() {
  if (!store.logContent) return
  const start = store.logContent.start
  if (start <= 0) return
  const newOffset = Math.max(0, start - pageSize.value)
  currentOffset.value = newOffset
  store.fetchLogContent(selectedFile.value, pageSize.value, currentOffset.value, false)
}

function refreshLog() {
  if (selectedFile.value) {
    store.fetchLogContent(selectedFile.value, pageSize.value, currentOffset.value, false)
  }
}

function handleDownload() {
  if (!selectedFile.value) return
  store.downloadLogFile(selectedFile.value)
    .catch(e => {
      message.error(e.response?.data?.detail || '下载失败')
    })
}

onMounted(() => {
  selectFile('app.log')
})
</script>

<style scoped>
.log-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.loading-center {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}

.no-file-hint {
  padding: 60px 0;
  display: flex;
  justify-content: center;
}

.active-file {
  background-color: var(--color-bg-active);
  border-radius: 6px;
}

.log-info {
  margin-bottom: 8px;
}

.log-pre {
  margin: 0;
  padding: 16px;
  background: var(--color-log-bg);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-log-text);
  font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', 'Consolas', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  word-wrap: break-word;
  overflow-wrap: break-word;
  max-width: 100%;
  box-sizing: border-box;
  overflow-x: auto;
}

.log-pre code {
  color: var(--color-log-text);
  font-family: inherit;
  background: transparent;
}

/* 日志内容容器约束宽度 */
.log-content {
  max-height: calc(100vh - 280px);
  overflow-y: auto;
  max-width: 100%;
}
</style>
