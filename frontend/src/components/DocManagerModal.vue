<template>
  <n-modal
    :show="isOpen"
    preset="card"
    :bordered="false"
    title="知识库文档"
    style="max-width: 600px; width: 94vw"
    :mask-closable="true"
    :segmented="{ content: false, footer: 'soft' }"
    @update:show="(v) => !v && $emit('close')"
  >
    <template #header-extra>
      <n-text depth="3">{{ filteredDocs.length }} 个文档</n-text>
    </template>

    <div class="modal-body">
      <!-- 搜索栏 -->
      <div class="search-row">
        <n-input
          v-model:value="searchQuery"
          placeholder="搜索文档…"
          clearable
          round
          size="small"
        >
          <template #prefix>
            <n-icon :component="SearchOutline" />
          </template>
        </n-input>
      </div>

      <n-empty
        v-if="filteredDocs.length === 0"
        :description="documents.length === 0 ? '还没有上传任何文档' : '没有匹配的文档'"
        style="margin: 24px 0"
      >
        <template #extra>
          <n-text depth="3" v-if="documents.length === 0">在对话区底部使用上传按钮添加</n-text>
        </template>
      </n-empty>

      <n-scrollbar v-else style="max-height: 44vh">
        <n-checkbox-group v-model:value="selected">
          <div class="doc-list">
            <label
              v-for="docName in pagedDocs"
              :key="docName"
              class="doc-item"
              :class="{ checked: selected.includes(docName) }"
            >
              <n-checkbox :value="docName" />
              <n-icon
                :size="20"
                :component="DocumentTextOutline"
                style="color: #d4734e; margin-left: 4px"
              />
              <span class="doc-name">{{ docName }}</span>
            </label>
          </div>
        </n-checkbox-group>
      </n-scrollbar>

      <!-- 分页器 -->
      <div v-if="totalPages > 1" class="pagination-row">
        <n-pagination
          :page="currentPage"
          :page-count="totalPages"
          :page-size="pageSize"
          size="small"
          @update:page="currentPage = $event"
        />
      </div>
    </div>

    <template #footer>
      <div class="footer">
        <n-text depth="3">已选择 <b>{{ selected.length }}</b> 个</n-text>
        <n-space>
          <n-button @click="$emit('close')">取消</n-button>
          <n-button
            type="error"
            :disabled="selected.length === 0 || isDeleting"
            :loading="isDeleting"
            @click="handleDelete"
          >
            <template #icon>
              <n-icon :component="TrashOutline" />
            </template>
            删除选中
          </n-button>
        </n-space>
      </div>
    </template>
  </n-modal>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import {
  NModal,
  NCheckbox,
  NCheckboxGroup,
  NButton,
  NIcon,
  NInput,
  NEmpty,
  NScrollbar,
  NSpace,
  NText,
  NPagination,
} from 'naive-ui'
import { DocumentTextOutline, TrashOutline, SearchOutline } from '@vicons/ionicons5'

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  documents: { type: Array, required: true },
  isDeleting: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'delete'])

const selected = ref([])
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 10

// 搜索过滤
const filteredDocs = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return props.documents
  return props.documents.filter((name) => name.toLowerCase().includes(q))
})

// 分页
const totalPages = computed(() => Math.ceil(filteredDocs.value.length / pageSize) || 0)

const pagedDocs = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredDocs.value.slice(start, start + pageSize)
})

// 搜索或文档变化时回到第一页
watch([searchQuery, () => props.documents], () => {
  currentPage.value = 1
})

// 弹窗打开时重置
watch(
  () => props.isOpen,
  (open) => {
    if (open) {
      selected.value = []
      searchQuery.value = ''
      currentPage.value = 1
    }
  }
)

const handleDelete = () => {
  if (selected.value.length === 0) return
  emit('delete', [...selected.value])
}
</script>

<style scoped>
.modal-body {
  min-height: 100px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-row {
  padding: 0 2px;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--n-divider-color, #d4cfc8);
  cursor: pointer;
  transition: all 0.15s ease;
  background-color: transparent;
}

.doc-item:hover {
  border-color: #d4734e;
  background-color: rgba(212, 115, 78, 0.04);
}

.doc-item.checked {
  border-color: #d4734e;
  background-color: rgba(212, 115, 78, 0.08);
}

.doc-name {
  flex: 1;
  font-size: 14px;
  color: var(--n-text-color-1, #1a1714);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pagination-row {
  display: flex;
  justify-content: center;
  padding-top: 4px;
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
