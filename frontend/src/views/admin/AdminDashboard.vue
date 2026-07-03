<template>
  <div class="dashboard-page">
    <n-h2>系统总览</n-h2>

    <!-- Loading -->
    <div v-if="store.loading && !store.dashboardData" class="loading-center">
      <n-spin size="large" />
    </div>

    <template v-else-if="store.dashboardData">
      <!-- 统计卡片 -->
      <n-grid :cols="2" :x-gap="16" :y-gap="16" class="stat-grid">
        <n-gi>
          <n-card :bordered="true" size="small">
            <n-statistic label="用户总数">
              <template #prefix>
                <n-icon :component="PeopleOutline" style="color:#d4734e" />
              </template>
              <span class="stat-value">{{ store.dashboardData.user_count }}</span>
            </n-statistic>
            <template #footer>
              <n-text depth="3">管理员: {{ store.dashboardData.admin_count }}</n-text>
            </template>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card :bordered="true" size="small">
            <n-statistic label="会话总数">
              <template #prefix>
                <n-icon :component="ChatbubblesOutline" style="color:#d4734e" />
              </template>
              <span class="stat-value">{{ store.dashboardData.session_count }}</span>
            </n-statistic>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card :bordered="true" size="small">
            <n-statistic label="文档总数">
              <template #prefix>
                <n-icon :component="DocumentTextOutline" style="color:#d4734e" />
              </template>
              <span class="stat-value">{{ store.dashboardData.document_count }}</span>
            </n-statistic>
            <template #footer>
              <n-text depth="3">嵌入维度: {{ store.dashboardData.embedding_dim || '-' }}</n-text>
            </template>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card :bordered="true" size="small">
            <n-statistic label="切块总数">
              <template #prefix>
                <n-icon :component="CubeOutline" style="color:#d4734e" />
              </template>
              <span class="stat-value">{{ store.dashboardData.chunk_count }}</span>
            </n-statistic>
            <template #footer>
              <n-text depth="3">模型: {{ store.dashboardData.embedding_model || '-' }}</n-text>
            </template>
          </n-card>
        </n-gi>
      </n-grid>

      <!-- 请求统计 + 系统运行信息 -->
      <n-grid :cols="2" :x-gap="16" :y-gap="16" style="margin-top: 16px">
        <n-gi>
          <n-card title="请求统计" :bordered="true" size="small">
            <template v-if="store.dashboardData.request_stats">
              <n-descriptions label-placement="left" :column="1" size="small">
                <n-descriptions-item label="总请求数">
                  {{ store.dashboardData.request_stats.total_requests }}
                </n-descriptions-item>
                <n-descriptions-item label="错误数（4xx/5xx）">
                  <n-text :type="errorCount > 0 ? 'error' : 'default'">
                    {{ store.dashboardData.request_stats.total_errors }}
                  </n-text>
                </n-descriptions-item>
                <n-descriptions-item label="各方法分布">
                  <n-space :size="8">
                    <n-tag v-for="(c, m) in store.dashboardData.request_stats.by_method" :key="m" size="small" :bordered="false">
                      {{ m }}: {{ c }}
                    </n-tag>
                  </n-space>
                </n-descriptions-item>
              </n-descriptions>
            </template>
            <n-empty v-else description="暂无请求统计" />
          </n-card>
        </n-gi>
        <n-gi>
          <n-card title="运行状态" :bordered="true" size="small">
            <n-descriptions label-placement="left" :column="1" size="small">
              <n-descriptions-item label="健康状态">
                <n-tag :type="store.dashboardData.healthy ? 'success' : 'error'" size="small" :bordered="false">
                  {{ store.dashboardData.healthy ? '正常' : '异常' }}
                </n-tag>
              </n-descriptions-item>
              <n-descriptions-item label="运行时长">
                {{ uptimeText }}
              </n-descriptions-item>
              <n-descriptions-item label="数据分区">
                {{ partitionCount }} 个
              </n-descriptions-item>
            </n-descriptions>

            <n-divider />
            <n-text depth="3" style="font-size: 13px">
              分区详情
            </n-text>
            <n-data-table
              v-if="partitionRows.length > 0"
              :columns="partitionColumns"
              :data="partitionRows"
              :bordered="false"
              :single-line="true"
              size="small"
              style="margin-top: 8px"
            />
            <n-empty v-else description="暂无分区数据" style="padding: 12px 0" />
          </n-card>
        </n-gi>
      </n-grid>
    </template>

    <!-- 无数据 -->
    <n-empty v-else description="点击刷新加载数据" style="margin-top: 60px">
      <template #extra>
        <n-button type="primary" @click="loadData">刷新数据</n-button>
      </template>
    </n-empty>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAdminStore } from '@/stores/admin'
import {
  NButton, NCard, NStatistic, NIcon, NText, NGrid, NGi,
  NDescriptions, NDescriptionsItem, NDivider, NTag, NSpace,
  NList, NListItem, NDataTable, NEmpty, NSpin, NH2,
} from 'naive-ui'
import {
  PeopleOutline, ChatbubblesOutline, DocumentTextOutline, CubeOutline,
} from '@vicons/ionicons5'

const store = useAdminStore()

const errorCount = computed(() => store.dashboardData?.request_stats?.total_errors || 0)
const uptimeText = computed(() => {
  const sec = store.dashboardData?.request_stats?.uptime_seconds || 0
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const parts = []
  if (d > 0) parts.push(`${d}天`)
  if (h > 0) parts.push(`${h}小时`)
  if (m > 0) parts.push(`${m}分钟`)
  parts.push(`${s}秒`)
  return parts.join(' ')
})

const partitionCount = computed(() => {
  const p = store.dashboardData?.partitions
  return p ? Object.keys(p).length : 0
})

const partitionRows = computed(() => {
  const p = store.dashboardData?.partitions
  if (!p) return []
  return Object.entries(p).map(([name, info]) => ({
    name,
    chunks: info.chunks,
    sources: info.sources,
  }))
})

const partitionColumns = [
  { title: '分区', key: 'name', width: 120 },
  { title: '切块数', key: 'chunks', width: 80 },
  { title: '文档数', key: 'sources', width: 80 },
]

function loadData() {
  store.fetchDashboard()
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.dashboard-page {
  max-width: 1100px;
}

.loading-center {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}

.stat-grid {
  margin-bottom: 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1a1714;
}

.path-text {
  font-size: 13px;
  color: #4a4440;
}

.path-count {
  float: right;
  font-weight: 600;
  color: #d4734e;
}
</style>
