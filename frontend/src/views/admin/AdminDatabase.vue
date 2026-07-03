<template>
  <div class="database-page">
    <n-h2>数据管理</n-h2>
    <n-tabs type="line" default-value="stats" @update:value="handleTabSwitch">
      <!-- 统计概览 -->
      <n-tab-pane name="stats" tab="统计概览">
        <div v-if="store.loading && !store.dbStats" class="loading-center">
          <n-spin size="large" />
        </div>

        <template v-else-if="store.dbStats?.available">
          <n-grid :cols="3" :x-gap="16" :y-gap="16">
            <n-gi>
              <n-card :bordered="true" size="small">
                <n-statistic label="切块总数">
                  <template #prefix>
                    <n-icon :component="CubeOutline" style="color:#d4734e" />
                  </template>
                  <span class="stat-value">{{ store.dbStats.total_chunks }}</span>
                </n-statistic>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card :bordered="true" size="small">
                <n-statistic label="向量总数">
                  <template #prefix>
                    <n-icon :component="GitBranchOutline" style="color:#d4734e" />
                  </template>
                  <span class="stat-value">{{ store.dbStats.total_vectors }}</span>
                </n-statistic>
              </n-card>
            </n-gi>
            <n-gi>
              <n-card :bordered="true" size="small">
                <n-statistic label="数据分区">
                  <template #prefix>
                    <n-icon :component="LayersOutline" style="color:#d4734e" />
                  </template>
                  <span class="stat-value">{{ store.dbStats.partitions_count || 0 }}</span>
                </n-statistic>
                <template #footer>
                  <n-text depth="3">来源文档: {{ store.dbStats.sources_count || 0 }}</n-text>
                </template>
              </n-card>
            </n-gi>
          </n-grid>

          <!-- 嵌入信息 -->
          <n-card title="模型信息" :bordered="true" size="small" style="margin-top: 16px">
            <n-descriptions label-placement="left" :column="2" size="small">
              <n-descriptions-item label="嵌入模型">
                {{ store.dbStats.embedding_model || '-' }}
              </n-descriptions-item>
              <n-descriptions-item label="嵌入维度">
                {{ store.dbStats.embedding_dimension || '-' }}
              </n-descriptions-item>
            </n-descriptions>
          </n-card>

          <!-- 按分区统计 -->
          <n-card title="按分区统计" :bordered="true" size="small" style="margin-top: 16px">
            <n-data-table
              v-if="partitionRows.length > 0"
              :columns="partitionColumns"
              :data="partitionRows"
              :bordered="false"
              :single-line="true"
              size="small"
            />
            <n-empty v-else description="暂无分区数据" style="padding: 20px 0" />
          </n-card>

          <n-card title="按来源统计" :bordered="true" size="small" style="margin-top: 16px">
            <n-data-table
              v-if="sourceRows.length > 0"
              :columns="sourceColumns"
              :data="sourceRows"
              :bordered="false"
              :single-line="true"
              size="small"
              :pagination="{ pageSize: 15 }"
            />
            <n-empty v-else description="暂无来源数据" style="padding: 20px 0" />
          </n-card>
        </template>

        <n-empty v-else-if="store.dbStats && !store.dbStats.available" description="向量存储未初始化" style="margin-top: 60px" />
        <n-empty v-else description="暂无数据" style="margin-top: 60px">
          <template #extra>
            <n-button type="primary" @click="loadStats">加载数据</n-button>
          </template>
        </n-empty>
      </n-tab-pane>

      <!-- 切块详情 -->
      <n-tab-pane name="chunks" tab="切块详情">
        <!-- 搜索过滤 -->
        <n-space style="margin-bottom: 16px" :wrap="true">
          <n-input
            v-model:value="chunkQuery"
            placeholder="搜索文本内容..."
            clearable
            style="width: 240px"
            @keydown.enter="searchChunks"
          />
          <n-select
            v-model:value="chunkPartition"
            :options="partitionOptions"
            placeholder="选择分区"
            clearable
            style="width: 160px"
            @update:value="searchChunks"
          />
          <n-select
            v-model:value="chunkType"
            :options="chunkTypeOptions"
            placeholder="选择类型"
            clearable
            style="width: 140px"
            @update:value="searchChunks"
          />
          <n-button type="primary" @click="searchChunks">搜索</n-button>
        </n-space>

        <n-data-table
          :columns="chunkColumns"
          :data="store.dbChunks?.items || []"
          :loading="store.loading"
          :bordered="true"
          :single-line="false"
          size="small"
          :max-height="500"
          :row-key="(row) => row.id"
        />
        <n-space justify="center" style="margin-top: 16px">
          <n-pagination
            v-model:page="chunkPage"
            :page-size="chunkPageSize"
            :item-count="store.dbChunks?.total || 0"
            :page-slot="7"
            @update:page="handleChunkPage"
          />
        </n-space>

        <!-- 父块详情弹窗 -->
        <n-modal
          v-model:show="showParentModal"
          title="父块切块详情"
          preset="card"
          style="width: 800px; max-width: 92vw"
          :segmented="{ content: true }"
        >
          <template v-if="parentInfo.source">
            <n-text depth="3" style="font-size: 12px; margin-bottom: 12px; display: block">
              来源: {{ parentInfo.source }} · 父块共切分为 {{ parentInfo.childCount }} 个子块
            </n-text>
            <n-data-table
              :columns="parentChildColumns"
              :data="parentChildren"
              :bordered="false"
              :single-line="true"
              size="small"
              :max-height="400"
            />
          </template>
        </n-modal>
      </n-tab-pane>

      <!-- 系统数据 -->
      <n-tab-pane name="system" tab="系统数据">
        <!-- 上传区域 -->
        <n-card title="上传系统数据" :bordered="true" size="small" style="margin-bottom: 16px">
          <n-space :size="12" style="margin-bottom: 8px">
            <n-button :disabled="store.isUploading" @click="triggerFilePicker">选择文件</n-button>
            <n-button :disabled="store.isUploading" @click="triggerFolderPicker">选择文件夹</n-button>
            <input
              ref="fileInputRef"
              type="file"
              multiple
              style="display: none"
              @change="handleFilesPicked"
            />
            <input
              ref="folderInputRef"
              type="file"
              webkitdirectory
              multiple
              style="display: none"
              @change="handleFilesPicked"
            />
          </n-space>
          <n-text depth="3" style="font-size: 12px">
            已选择 {{ uploadFiles.length }} 个文件
          </n-text>
          <n-list v-if="uploadFiles.length > 0" size="small" style="margin-top: 6px; max-height: 200px; overflow-y: auto">
            <n-list-item v-for="(f, i) in uploadFiles" :key="f._id">
              <n-text style="font-size: 12px">{{ i + 1 }}. {{ f.name }}</n-text>
              <template #suffix>
                <n-button size="tiny" quaternary circle type="error" @click="removeFile(f._id)">
                  <template #icon>
                    <n-icon :component="CloseOutline" />
                  </template>
                </n-button>
              </template>
            </n-list-item>
          </n-list>
          <n-space style="margin-top: 12px">
            <n-button
              type="primary"
              :loading="store.isUploading"
              :disabled="uploadFiles.length === 0 || store.isUploading"
              @click="handleUpload"
            >
              上传并向量化
            </n-button>
            <n-text v-if="store.uploadStatus.message" :type="store.uploadStatus.type" depth="3">
              {{ store.uploadStatus.message }}
            </n-text>
            <n-button v-if="store.isUploading" size="small" secondary @click="checkUploadStatus">
              刷新状态
            </n-button>
          </n-space>
        </n-card>

        <!-- 系统文档列表 -->
        <n-card title="系统文档列表" :bordered="true" size="small">
          <n-data-table
            v-if="store.systemDocs.length > 0"
            :columns="systemDocColumns"
            :data="store.systemDocs"
            :bordered="false"
            :single-line="true"
            size="small"
            :pagination="{ pageSize: 15 }"
          />
          <n-empty v-else description="暂无系统文档" style="padding: 20px 0" />
        </n-card>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, h } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { useAdminStore } from '@/stores/admin'
import {
  NCard, NGrid, NGi, NStatistic, NIcon, NText, NDescriptions,
  NDescriptionsItem, NDataTable, NTabPane, NTabs, NEmpty, NSpin,
  NButton, NInput, NSelect, NSpace, NPagination, NModal, NCode, NH2, NTag,
  NUpload, NList, NListItem,
} from 'naive-ui'
import axios from '@/http/interceptor'
import {
  CubeOutline, GitBranchOutline, LayersOutline, CloseOutline,
} from '@vicons/ionicons5'

const store = useAdminStore()
const message = useMessage()
const dialog = useDialog()

// ─── 统计概览 ────────────────────────────────────
const partitionRows = computed(() => {
  const bp = store.dbStats?.by_partition
  if (!bp) return []
  return Object.entries(bp).map(([name, info]) => ({
    partition: name,
    chunks: info.chunks,
    sources: Array.isArray(info.sources) ? info.sources.length : 0,
  }))
})

const partitionColumns = [
  {
    title: '分区',
    key: 'partition',
    width: 160,
    render(row) {
      return h(NTag, {
        type: partitionTagType(row.partition),
        size: 'small',
        bordered: false,
      }, { default: () => formatPartition(row.partition) })
    },
  },
  { title: '切块数', key: 'chunks', width: 100 },
  { title: '文档数', key: 'sources', width: 100 },
]

const sourceRows = computed(() => {
  const bs = store.dbStats?.by_source
  if (!bs) return []
  return Object.entries(bs)
    .sort((a, b) => b[1].chunks - a[1].chunks)
    .map(([name, info]) => ({
      source: name,
      chunks: info.chunks,
      partition: Array.isArray(info.partitions) ? info.partitions.join(', ') : '',
    }))
})

const sourceColumns = [
  { title: '来源', key: 'source', ellipsis: { tooltip: true } },
  { title: '切块数', key: 'chunks', width: 100 },
  {
    title: '所属分区',
    key: 'partition',
    ellipsis: { tooltip: true },
    render(row) {
      if (!row.partition) return '-'
      const partitions = row.partition.split(', ')
      return h(NSpace, { size: 4 }, {
        default: () => partitions.map(p => h(NTag, {
          type: isSystemPartition(p) ? 'success' : 'info',
          size: 'tiny',
          bordered: false,
        }, { default: () => formatPartition(p) }))
      })
    },
  },
]

function loadStats() {
  store.fetchDatabaseStats()
  store.fetchPartitions()
}

// ─── 切块详情 ────────────────────────────────────
const SYSTEM_PARTITION = '__system__'

function isSystemPartition(partition) {
  return partition === SYSTEM_PARTITION
}

function formatPartition(partition) {
  if (!partition) return '-'
  if (isSystemPartition(partition)) return '系统'
  return `用户: ${partition}`
}

function partitionTagType(partition) {
  return isSystemPartition(partition) ? 'success' : 'info'
}

const chunkQuery = ref('')
const chunkPartition = ref(null)
const chunkType = ref(null)
const chunkPage = ref(1)
const chunkPageSize = ref(20)

const partitionOptions = computed(() => {
  const p = store.dbPartitions?.partitions || []
  const opts = p.map(item => ({
    label: formatPartition(item.partition),
    value: item.partition,
  }))
  // 在最前面加一个"系统数据"快速筛选
  opts.unshift({ label: '--- 快速筛选 ---', value: null, disabled: true })
  opts.unshift({ label: '所有系统数据', value: SYSTEM_PARTITION })
  return opts
})

const chunkTypeOptions = computed(() => {
  const types = store.dbStats?.chunk_types || []
  return types.map(t => ({ label: t || '(空)', value: t }))
})

const chunkColumns = [
  { title: 'ID', key: 'id', width: 100, ellipsis: { tooltip: true } },
  {
    title: '内容',
    key: 'text',
    ellipsis: { tooltip: true },
    width: 300,
  },
  { title: '来源', key: 'source', width: 120, ellipsis: { tooltip: true } },
  {
    title: '分区',
    key: 'partition',
    width: 120,
    render(row) {
      if (!row.partition) return '-'
      return h(NTag, {
        type: partitionTagType(row.partition),
        size: 'tiny',
        bordered: false,
      }, { default: () => formatPartition(row.partition) })
    },
  },
  { title: '类型', key: 'chunk_type', width: 80 },
  { title: '页面', key: 'page', width: 60 },
  { title: '父块长度', key: 'parent_chunk_size', width: 90 },
  {
    title: '操作',
    key: 'actions',
    width: 160,
    render(row) {
      const buttons = []
      if (row.parent_id) {
        buttons.push(h(NButton, {
          size: 'tiny',
          type: 'primary',
          secondary: true,
          style: 'margin-right: 4px',
          onClick: () => openParentDetail(row),
        }, { default: () => '父块' }))
      }
      if (row.source && row.partition) {
        buttons.push(h(NButton, {
          size: 'tiny',
          type: 'error',
          secondary: true,
          onClick: () => confirmDeleteDoc(row.source, row.partition),
        }, { default: () => '删除' }))
      }
      return h(NSpace, { size: 4 }, { default: () => buttons })
    },
  },
]

// 父块详情
const showParentModal = ref(false)
const parentInfo = ref({ parent_id: '', source: '', childCount: 0 })
const parentChildren = ref([])
const parentChildColumns = [
  { title: '内容', key: 'text', ellipsis: { tooltip: true }, width: 350 },
  { title: '类型', key: 'chunk_type', width: 70 },
  { title: '页面', key: 'page', width: 60 },
]

async function openParentDetail(row) {
  parentInfo.value = {
    parent_id: row.parent_id || '',
    source: row.source || '',
    childCount: 0,
  }
  showParentModal.value = true
  try {
    const res = await axios.get('/api/admin/database/chunks', {
      params: { parent_id: row.parent_id, page_size: 200 },
    })
    if (res.data?.items) {
      parentChildren.value = res.data.items.map(item => ({
        ...item,
        text: (item.text || '').substring(0, 200),
      }))
      parentInfo.value.childCount = res.data.total
    }
  } catch (e) {
    parentChildren.value = []
  }
}

function searchChunks() {
  chunkPage.value = 1
  store.fetchPartitions()
  store.fetchChunks(1, chunkPageSize.value, {
    partition: chunkPartition.value || undefined,
    chunk_type: chunkType.value || undefined,
    query_text: chunkQuery.value || undefined,
  })
}

function handleChunkPage(page) {
  chunkPage.value = page
  store.fetchChunks(page, chunkPageSize.value, {
    partition: chunkPartition.value || undefined,
    chunk_type: chunkType.value || undefined,
    query_text: chunkQuery.value || undefined,
  })
}

onMounted(() => {
  loadStats()
  store.fetchPartitions()
  store.fetchChunks()
  store.fetchSystemDocs()
})

// ─── 系统数据上传 ────────────────────────────────────
function handleTabSwitch(tabName) {
  if (tabName === 'system' && store.isUploading) {
    checkUploadStatus()
  }
}
const uploadFiles = ref([])  // { _id: number, name: string, file: File }[]
const fileInputRef = ref(null)
const folderInputRef = ref(null)
let uploadIdCounter = 0

function triggerFilePicker() {
  fileInputRef.value?.click()
}

function triggerFolderPicker() {
  folderInputRef.value?.click()
}

function handleFilesPicked(e) {
  const files = e.target.files
  if (!files || files.length === 0) return
  const existing = new Set(uploadFiles.value.map(f => f.name))
  for (const file of files) {
    // 直接使用文件的基础名称，忽略相对路径层级
    const name = file.name
    if (!existing.has(name)) {
      uploadFiles.value.push({
        _id: ++uploadIdCounter,
        name,
        file,
      })
    }
  }
  store.setUploadStatus('')
  // 重置 input 以便重复选择同一组文件
  e.target.value = ''
}

function removeFile(id) {
  uploadFiles.value = uploadFiles.value.filter(f => f._id !== id)
}

function handleRemove({ file }) {
  uploadFiles.value = uploadFiles.value.filter(f => f._id !== file.id)
}

async function handleUpload() {
  if (uploadFiles.value.length === 0) return
  const files = uploadFiles.value.slice()
  const totalFiles = files.length

  store.setUploadStatus('正在发送 ' + totalFiles + ' 个文件...', 'info')
  store.isUploading = true
  try {
    const formData = new FormData()
    for (const f of files) {
      formData.append('files', f.file)
    }
    await axios.post('/api/admin/database/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    store.setUploadStatus('已接收 ' + totalFiles + ' 个文件，后台向量化处理中，可点击「刷新状态」查看进度', 'success')
    uploadFiles.value = []
    // 立即查一次系统文档列表
    store.fetchSystemDocs()
  } catch (e) {
    store.setUploadStatus('上传失败: ' + (e.response?.data?.detail || e.message), 'error')
    store.isUploading = false
  }
}

async function checkUploadStatus() {
  try {
    const res = await axios.get('/api/admin/database/upload/status')
    const data = res.data
    if (data.status === 'finished') {
      store.setUploadStatus('向量化完成，共处理 ' + data.task.success + ' 个文件', 'success')
      store.isUploading = false
      store.fetchSystemDocs()
      store.fetchDatabaseStats()
    } else if (data.status === 'processing') {
      store.setUploadStatus('向量化处理中 (' + (data.task.success + data.task.fail) + '/' + data.task.total + ')...', 'info')
    } else {
      store.setUploadStatus('暂无进行中的上传任务', 'info')
      store.isUploading = false
    }
  } catch {
    store.setUploadStatus('查询状态失败', 'error')
  }
}

const systemDocColumns = [
  { title: '文件名', key: 'name', ellipsis: { tooltip: true } },
  { title: '切块数', key: 'chunks', width: 100 },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render(row) {
      return h(NButton, {
        size: 'tiny',
        type: 'error',
        secondary: true,
        onClick: () => confirmDeleteDoc(row.name, SYSTEM_PARTITION),
      }, { default: () => '删除' })
    },
  },
]

async function confirmDeleteDoc(source, partition) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除「${source}」（${formatPartition(partition)}）吗？此操作不可撤销。`,
    positiveText: '确认删除',
    negativeText: '取消',
    async onPositiveClick() {
      try {
        await store.deleteDocument(source, partition)
        message.success(`已删除: ${source}`)
        // 刷新当前数据
        store.fetchSystemDocs()
        searchChunks()
      } catch (e) {
        message.error(e.response?.data?.detail || '删除失败')
      }
    },
  })
}
</script>

<style scoped>
.database-page {
  max-width: 1200px;
}

.loading-center {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1a1714;
}
</style>
