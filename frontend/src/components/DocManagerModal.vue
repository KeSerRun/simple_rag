<template>
  <n-modal
    :show="isOpen"
    preset="card"
    :bordered="false"
    title="知识库文档"
    style="max-width: 560px; width: 92vw"
    :mask-closable="true"
    :segmented="{ content: false, footer: 'soft' }"
    @update:show="(v) => !v && $emit('close')"
  >
    <template #header-extra>
      <n-text depth="3">{{ documents.length }} 个文档</n-text>
    </template>

    <div class="modal-body">
      <n-empty
        v-if="documents.length === 0"
        description="还没有上传任何文档"
        style="margin: 24px 0"
      >
        <template #extra>
          <n-text depth="3">在对话区底部使用上传按钮添加</n-text>
        </template>
      </n-empty>

      <n-scrollbar v-else style="max-height: 50vh">
        <n-checkbox-group v-model:value="selected">
          <div class="doc-list">
            <label
              v-for="docName in documents"
              :key="docName"
              class="doc-item"
              :class="{ checked: selected.includes(docName) }"
            >
              <n-checkbox :value="docName" />
              <n-icon
                :size="20"
                :component="DocumentTextOutline"
                style="color: #cc785c; margin-left: 4px"
              />
              <span class="doc-name">{{ docName }}</span>
            </label>
          </div>
        </n-checkbox-group>
      </n-scrollbar>
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
import { ref, watch } from 'vue'
import {
  NModal,
  NCheckbox,
  NCheckboxGroup,
  NButton,
  NIcon,
  NEmpty,
  NScrollbar,
  NSpace,
  NText,
} from 'naive-ui'
import { DocumentTextOutline, TrashOutline } from '@vicons/ionicons5'

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  documents: { type: Array, required: true },
  isDeleting: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'delete'])

const selected = ref([])

watch(
  () => props.isOpen,
  (open) => {
    if (open) selected.value = []
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
  border: 1px solid var(--n-divider-color, #e8e6e2);
  cursor: pointer;
  transition: all 0.15s ease;
  background-color: transparent;
}

.doc-item:hover {
  border-color: #cc785c;
  background-color: rgba(204, 120, 92, 0.04);
}

.doc-item.checked {
  border-color: #cc785c;
  background-color: rgba(204, 120, 92, 0.08);
}

.doc-name {
  flex: 1;
  font-size: 14px;
  color: var(--n-text-color-1, #2c2825);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
