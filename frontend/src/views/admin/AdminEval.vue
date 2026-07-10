<template>
  <div class="eval-page">
    <n-h2>检索质量评估</n-h2>
    <n-text depth="3" style="display:block; margin-bottom: 20px">
      基于向量库实际数据，使用 LLM 评判器对每个检索结果打分 (0-4)，计算平均精确率 Precision@K。
    </n-text>

    <!-- 测试查询编辑 -->
    <n-card title="测试查询" :bordered="true" size="small" style="margin-bottom: 16px">
      <n-space vertical>
        <n-text depth="3">
          每行一个查询，共 {{ queriesList.length }} 个。修改后保存即写入外部文件，下次评估使用新查询。
        </n-text>
        <n-input
          type="textarea"
          :rows="8"
          :value="queriesText"
          @update:value="onQueriesChange"
          placeholder="每行输入一个测试查询..."
          style="font-family: monospace; font-size: 13px"
          :disabled="isEvalRunning"
        />
        <n-space>
          <n-button
            type="primary"
            size="small"
            @click="handleSaveQueries"
            :loading="store.loading"
            :disabled="isEvalRunning"
          >
            保存查询
          </n-button>
          <n-button
            size="small"
            @click="handleResetQueries"
            :disabled="isEvalRunning"
          >
            恢复
          </n-button>
          <n-text v-if="saveMsg" :type="saveMsgType" depth="3" style="font-size: 13px">
            {{ saveMsg }}
          </n-text>
        </n-space>
      </n-space>
    </n-card>

    <!-- 运行评估 -->
    <n-card title="运行评估" :bordered="true" size="small" style="margin-bottom: 16px">
      <n-text>
        <p>依次执行 {{ queryCount }} 个测试查询，对每个查询：</p>
        <ol style="padding-left: 20px; line-height: 1.8">
          <li>调用检索工具获取知识库结果</li>
          <li>使用 LLM 评判器对每条结果打分（0-4）</li>
          <li>评分 &ge; 3 视为相关，计算精确率</li>
        </ol>
        <p style="margin-top: 8px"><strong>注意：</strong>评估会调用 LLM 进行评分，耗时较长（约 5-10 分钟），请耐心等待。</p>
      </n-text>

      <!-- 运行中：进度展示 -->
      <template v-if="store.evalStatus && (store.evalStatus.status === 'running' || store.evalStatus.status === 'paused')">
        <n-divider />
        <n-space vertical>
          <n-progress
            type="line"
            :percentage="progressPercent"
            indicator-placement="inside"
            status="info"
            :height="24"
          />
          <n-text>
            当前查询：<n-tag>{{ currentQuery }}</n-tag>
          </n-text>
          <n-text depth="3">
            已完成 {{ completedCount }} / {{ totalCount }} 个查询
          </n-text>
          <n-space>
            <n-button size="small" @click="handlePause" :disabled="store.evalStatus?.status !== 'running'">暂停</n-button>
            <n-button size="small" @click="handleResume" :disabled="store.evalStatus?.status !== 'paused'">继续</n-button>
            <n-button size="small" @click="refreshStatus">刷新进度</n-button>
          </n-space>
        </n-space>
      </template>

      <template #action>
        <n-button
          type="primary"
          @click="handleRunEval"
          :loading="isEvalRunning"
          :disabled="isEvalRunning || queryCount === 0"
        >
          {{ isEvalRunning ? '评估中...' : (store.evalResults ? '重新评估' : '启动评估') }}
        </n-button>
      </template>
    </n-card>

    <!-- 完成：展示结果 -->
    <template v-if="store.evalResults">
      <n-card title="评估摘要" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-statistic label="平均精确率" :value="avgPrecisionText" />
      </n-card>

      <n-card title="各查询详情" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-table :single-line="false" size="small">
          <thead>
            <tr>
              <th style="width:30%">查询</th>
              <th style="width:80px">检索数</th>
              <th style="width:80px">相关数</th>
              <th style="width:80px">精确率</th>
              <th style="width:80px">均分</th>
              <th>评分明细</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in store.evalResults" :key="r.query">
              <td>
                <n-ellipsis :line-clamp="1" style="max-width: 200px">{{ r.query }}</n-ellipsis>
              </td>
              <td>{{ r.retrieved_count }}</td>
              <td>{{ r.relevant_count }}</td>
              <td>
                <n-tag :type="precisionColor(r.precision)" size="small">
                  {{ (r.precision * 100).toFixed(0) }}%
                </n-tag>
              </td>
              <td>{{ r.avg_score.toFixed(2) }}</td>
              <td>
                <n-space size="small">
                  <n-tag
                    v-for="(s, i) in r.scores.slice(0, 10)"
                    :key="i"
                    :type="scoreTagType(s)"
                    size="tiny"
                    style="margin: 1px"
                  >
                    {{ s }}
                  </n-tag>
                  <n-text v-if="r.scores.length > 10" depth="3" style="font-size:12px">
                    +{{ r.scores.length - 10 }}
                  </n-text>
                </n-space>
              </td>
            </tr>
          </tbody>
        </n-table>
      </n-card>
    </template>

    <!-- 失败状态 -->
    <template v-if="store.evalStatus && store.evalStatus.status === 'failed'">
      <n-result
        status="error"
        title="评估失败"
        :description="store.evalStatus.error || '未知错误'"
      >
        <template #footer>
          <n-button @click="handleRunEval">重试</n-button>
        </template>
      </n-result>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAdminStore } from '@/stores/admin'
import {
  NButton, NCard, NText, NTag, NTable, NProgress,
  NSpace, NResult, NH2, NStatistic, NEllipsis,
  NInput, NDivider,
} from 'naive-ui'

const store = useAdminStore()

const queryCount = ref(0)
const queriesList = ref([])
const queriesText = ref('')
const savedQueriesText = ref('')
const saveMsg = ref('')
const saveMsgType = ref('info')

const isEvalRunning = ref(false)

const progressPercent = computed(() => {
  if (!store.evalStatus?.progress) return 0
  const p = store.evalStatus.progress
  if (p.total === 0) return 0
  return Math.round((p.completed / p.total) * 100)
})

const totalCount = computed(() => store.evalStatus?.progress?.total || 0)
const completedCount = computed(() => store.evalStatus?.progress?.completed || 0)
const currentQuery = computed(() => store.evalStatus?.progress?.current || '')

const avgPrecisionText = computed(() => {
  if (!store.evalReport) return ''
  return store.evalReport.avg_precision_pct || ''
})

function scoreTagType(score) {
  if (score >= 3) return 'success'
  if (score >= 1) return 'warning'
  return 'error'
}

function precisionColor(precision) {
  if (precision >= 0.7) return 'success'
  if (precision >= 0.3) return 'warning'
  return 'error'
}

function onQueriesChange(value) {
  queriesText.value = value
  queriesList.value = value.split('\n').map(s => s.trim()).filter(Boolean)
  saveMsg.value = ''
}

async function loadQueries() {
  try {
    const data = await store.fetchEvalQueries()
    queriesList.value = data?.queries || []
    queriesText.value = queriesList.value.join('\n')
    savedQueriesText.value = queriesText.value
    queryCount.value = queriesList.value.length
  } catch {
    queriesList.value = []
    queriesText.value = ''
    queryCount.value = 0
  }
}

async function handleSaveQueries() {
  const list = queriesText.value.split('\n').map(s => s.trim()).filter(Boolean)
  if (list.length === 0) {
    saveMsg.value = '至少输入一个查询'
    saveMsgType.value = 'error'
    return
  }
  try {
    await store.updateEvalQueries(list)
    queriesList.value = list
    savedQueriesText.value = queriesText.value
    queryCount.value = list.length
    saveMsg.value = `已保存 ${list.length} 个查询`
    saveMsgType.value = 'success'
  } catch (e) {
    saveMsg.value = e.response?.data?.detail || '保存失败'
    saveMsgType.value = 'error'
  }
}

function handleResetQueries() {
  queriesText.value = savedQueriesText.value
  queriesList.value = savedQueriesText.value.split('\n').map(s => s.trim()).filter(Boolean)
  saveMsg.value = ''
}

async function handleRunEval() {
  if (isEvalRunning.value) return
  isEvalRunning.value = true
  try {
    const data = await store.runEval()
    if (data?.task_id) {
      // 启动评估成功，用户可手动点"刷新进度"查看状态
    }
  } catch (e) {
    isEvalRunning.value = false
  }
}

async function refreshStatus() {
  if (store.evalStatus?.task_id) {
    await store.fetchEvalStatus(store.evalStatus.task_id)
    if (store.evalStatus?.status === 'running' || store.evalStatus?.status === 'paused') {
      isEvalRunning.value = true
    } else {
      isEvalRunning.value = false
    }
  }
}

async function handlePause() {
  if (!store.evalStatus?.task_id) return
  try {
    await store.pauseEval(store.evalStatus.task_id)
    store.evalStatus.status = 'paused'
    message.success('评估已暂停，当前查询完成后将停止')
  } catch (e) {
    message.error('暂停失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function handleResume() {
  if (!store.evalStatus?.task_id) return
  try {
    await store.resumeEval(store.evalStatus.task_id)
    store.evalStatus.status = 'running'
    message.success('评估已继续')
  } catch (e) {
    message.error('继续失败: ' + (e.response?.data?.detail || e.message))
  }
}

function startPolling(taskId) {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      await store.fetchEvalStatus(taskId)
      if (store.evalStatus?.status === 'finished' || store.evalStatus?.status === 'failed') {
        isEvalRunning.value = false
        stopPolling()
      }
    } catch {
      isEvalRunning.value = false
      stopPolling()
    }
  }, 2000)
}


onMounted(async () => {
  await loadQueries()

  // 尝试加载持久化的评估结果
  await store.fetchLastEvalResult()
  if (store.evalStatus?.status === 'running') {
    isEvalRunning.value = true
  } else {
    isEvalRunning.value = false
  }
})

</script>

<style scoped>
.eval-page {
  max-width: 1200px;
}
</style>
