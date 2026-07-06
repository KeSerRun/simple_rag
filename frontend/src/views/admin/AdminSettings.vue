<template>
  <div class="settings-page">
    <n-h2>系统设置</n-h2>
    <n-text depth="3" style="display:block; margin-bottom: 20px">
      修改系统配置文件 config.ini，保存后即时生效。敏感字段已脱敏显示。
    </n-text>

    <div v-if="store.loading && !store.configData" class="loading-center">
      <n-spin size="large" />
    </div>

    <template v-else-if="store.configData">
      <n-card title="LLM / API 配置" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="Chat 模型">
            <n-input v-model:value="form.chat_model" />
          </n-form-item>
          <n-form-item label="Chat Base URL">
            <n-input v-model:value="form.openai_base_url" placeholder="https://api.openai.com/v1" />
          </n-form-item>
          <n-form-item label="Chat API Key">
            <n-input v-model:value="form.openai_api_key" type="password" show-password-on="click" />
          </n-form-item>
          <n-form-item label="推理力度">
            <n-select v-model:value="form.chat_reasoning_effort" :options="reasoningOptions" style="width:140px" clearable />
          </n-form-item>
          <n-form-item label="Embedding 模型">
            <n-input v-model:value="form.openai_embedding_model" />
          </n-form-item>
          <n-form-item label="Embedding Base URL">
            <n-input v-model:value="form.embedding_base_url" placeholder="https://api.openai.com/v1" />
          </n-form-item>
          <n-form-item label="Embedding API Key">
            <n-input v-model:value="form.embedding_api_key" type="password" show-password-on="click" placeholder="留空则复用 Chat API Key" />
          </n-form-item>
          <n-form-item label="Embedding 维度">
            <n-input-number v-model:value="form.openai_embedding_dim" :min="64" :max="4096" style="width:140px" />
          </n-form-item>
          <n-form-item label="超时时间(秒)">
            <n-input-number v-model:value="form.openai_timeout" :min="5" :max="300" style="width:120px" />
          </n-form-item>
          <n-form-item label="最大重试次数">
            <n-input-number v-model:value="form.openai_max_retries" :min="0" :max="10" style="width:100px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="MinerU PDF 解析" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="API Base URL">
            <n-input v-model:value="form.mineru_base_url" />
          </n-form-item>
          <n-form-item label="API Key">
            <n-input v-model:value="form.mineru_api_key" type="password" show-password-on="click" />
          </n-form-item>
          <n-form-item label="Token 名称">
            <n-input v-model:value="form.mineru_token_name" />
          </n-form-item>
          <n-form-item label="模型版本">
            <n-select v-model:value="form.mineru_model_version" :options="mineruModelOptions" style="width:140px" />
          </n-form-item>
          <n-form-item label="语言">
            <n-input v-model:value="form.mineru_language" style="width:120px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="检索配置" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="父块大小(字符)">
            <n-input-number v-model:value="form.parent_chunk_size" :min="20" :max="2000" style="width:120px" />
          </n-form-item>
          <n-form-item label="子块大小(字符)">
            <n-input-number v-model:value="form.child_chunk_size" :min="10" :max="500" style="width:120px" />
          </n-form-item>
          <n-form-item label="块重叠(字符)">
            <n-input-number v-model:value="form.chunk_overlap" :min="0" :max="200" style="width:120px" />
          </n-form-item>
          <n-form-item label="检索 Top-K">
            <n-input-number v-model:value="form.retrieval_top_k" :min="1" :max="100" style="width:120px" />
          </n-form-item>
          <n-form-item label="候选 Top-K">
            <n-input-number v-model:value="form.candidate_top_k" :min="1" :max="50" style="width:120px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="Agent 配置" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="最大工具迭代次数">
            <n-input-number v-model:value="form.max_tool_iter" :min="1" :max="30" style="width:120px" />
          </n-form-item>
          <n-form-item label="单个工具最大调用次数">
            <n-input-number v-model:value="form.max_calls_per_tool" :min="1" :max="10" style="width:120px" />
          </n-form-item>
          <n-form-item label="最大输出 Token">
            <n-input-number v-model:value="form.max_output_tokens" :min="512" :max="65536" :step="1024" style="width:140px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="联网搜索配置" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="搜索后端">
            <n-select v-model:value="form.search_backend" :options="searchBackendOptions" style="width:160px" />
          </n-form-item>
          <n-form-item v-if="form.search_backend === 'searxng'" label="SearXNG 地址">
            <n-input v-model:value="form.searxng_url" placeholder="仅 backend=searxng 时使用" />
          </n-form-item>
          <n-form-item v-if="form.search_backend === 'bocha'" label="博查 API Key">
            <n-input v-model:value="form.bocha_api_key" type="password" show-password-on="click" placeholder="backend=bocha 时必填" />
          </n-form-item>
          <n-form-item v-if="form.search_backend === 'bing'" label="Bing API Key">
            <n-input v-model:value="form.bing_api_key" type="password" show-password-on="click" placeholder="backend=bing 时必填" />
          </n-form-item>
          <n-form-item label="搜索超时(秒)">
            <n-input-number v-model:value="form.search_timeout" :min="5" :max="60" style="width:120px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="对话历史配置" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="最大保留轮次">
            <n-input-number v-model:value="form.max_history_length" :min="10" :max="1000" style="width:120px" />
          </n-form-item>
          <n-form-item label="最大字符数">
            <n-input-number v-model:value="form.max_history_chars" :min="1000" :max="500000" style="width:140px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="日志配置" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="应用日志级别">
            <n-select v-model:value="form.app_log_level" :options="logLevelOptions" style="width:120px" />
          </n-form-item>
          <n-form-item label="HTTP 日志级别">
            <n-select v-model:value="form.http_log_level" :options="logLevelOptions" style="width:120px" />
          </n-form-item>
          <n-form-item label="用户日志级别">
            <n-select v-model:value="form.user_log_level" :options="logLevelOptions" style="width:120px" />
          </n-form-item>
          <n-form-item label="控制台日志级别">
            <n-select v-model:value="form.console_log_level" :options="logLevelOptions" style="width:120px" />
          </n-form-item>
        </n-form>
      </n-card>

      <n-card title="上传限制" :bordered="true" size="small" style="margin-bottom: 16px">
        <n-form label-placement="left" label-width="160" size="small">
          <n-form-item label="用户存储上限(MB)">
            <n-input-number v-model:value="form.max_user_storage_mb" :min="0" :max="10000" style="width:140px" />
          </n-form-item>
          <n-text depth="3" style="font-size: 12px">0 表示不限制，管理员不受此限制</n-text>
        </n-form>
      </n-card>

      <n-space style="margin-top: 20px">
        <n-button type="primary" :loading="store.loading" @click="handleSave">
          保存设置
        </n-button>
        <n-button @click="handleReset">重置</n-button>
      </n-space>
    </template>

    <n-empty v-else description="暂无配置数据" style="margin-top: 60px">
      <template #extra>
        <n-button type="primary" @click="loadData">加载配置</n-button>
      </template>
    </n-empty>
  </div>
</template>

<script setup>
import { reactive, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { useAdminStore } from '@/stores/admin'
import {
  NButton, NCard, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NText, NSpace, NEmpty, NSpin, NH2,
} from 'naive-ui'

const store = useAdminStore()
const message = useMessage()

const form = reactive({
  chat_model: '',
  openai_base_url: '',
  openai_api_key: '',
  chat_reasoning_effort: null,
  openai_embedding_model: '',
  embedding_base_url: '',
  embedding_api_key: '',
  openai_embedding_dim: 1024,
  openai_timeout: 60,
  openai_max_retries: 3,
  mineru_base_url: '',
  mineru_api_key: '',
  mineru_token_name: 'default',
  mineru_model_version: 'vlm',
  mineru_language: 'ch',
  parent_chunk_size: 200,
  child_chunk_size: 50,
  chunk_overlap: 20,
  retrieval_top_k: 20,
  candidate_top_k: 5,
  max_tool_iter: 8,
  max_calls_per_tool: 3,
  max_output_tokens: 8192,
  search_backend: 'duckduckgo',
  searxng_url: '',
  bocha_api_key: '',
  bing_api_key: '',
  search_timeout: 15,
  max_history_length: 200,
  max_history_chars: 100000,
  app_log_level: 'INFO',
  http_log_level: 'INFO',
  user_log_level: 'INFO',
  console_log_level: 'DEBUG',
  max_user_storage_mb: 10,
})

const logLevelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
]

const reasoningOptions = [
  { label: '不指定', value: null },
  { label: 'low', value: 'low' },
  { label: 'medium', value: 'medium' },
  { label: 'high', value: 'high' },
]

const mineruModelOptions = [
  { label: 'vlm', value: 'vlm' },
  { label: 'lite', value: 'lite' },
]

const searchBackendOptions = [
  { label: 'DuckDuckGo', value: 'duckduckgo' },
  { label: 'SearXNG', value: 'searxng' },
  { label: '博查 AI', value: 'bocha' },
  { label: 'Bing', value: 'bing' },
]

function applyConfig(data) {
  if (!data) return
  const fields = Object.keys(form)
  for (const key of fields) {
    if (key in data) {
      form[key] = data[key]
    }
  }
}

function loadData() {
  store.fetchConfig().then(data => applyConfig(data))
}

function handleSave() {
  const updates = { ...form }
  store.updateConfig(updates)
    .then(() => message.success('配置已更新'))
    .catch(e => message.error(e.response?.data?.detail || '保存失败'))
}

function handleReset() {
  applyConfig(store.configData)
  message.info('已重置为当前配置')
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.settings-page {
  max-width: 1200px;
}

.loading-center {
  display: flex;
  justify-content: center;
  padding: 80px 0;
}
</style>
