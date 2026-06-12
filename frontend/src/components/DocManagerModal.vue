<template>
  <div class="doc-modal-mask" @click.self="handleClose">
    <div class="doc-modal">
      <div class="doc-modal-header">
        <h3>用户文档库</h3>
        <button @click="handleClose" class="close-btn">✕</button>
      </div>

      <div class="doc-modal-body">
        <div v-if="documents.length === 0" class="empty-docs">
          暂无文档，请在下方上传文件。
        </div>
        <div v-else class="doc-list">
          <div v-for="(docName, index) in documents" :key="index" class="doc-item">
            <label class="doc-checkbox-label">
              <input type="checkbox" v-model="localSelectedDocs" :value="docName">
              <span class="doc-icon">📄</span>
              <div class="doc-info">
                <span class="doc-name">{{ docName }}</span>
              </div>
            </label>
          </div>
        </div>
      </div>

      <div class="doc-modal-footer">
        <div class="selection-info">
          已选择 <strong>{{ localSelectedDocs.length }}</strong> 个文档
        </div>
        <button @click="handleDelete" :disabled="localSelectedDocs.length === 0 || isDeleting"
          class="delete-selected-btn">
          {{ isDeleting ? '删除中...' : '删除选中' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  documents: {
    type: Array,
    required: true
  },
  isDeleting: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'delete'])

const localSelectedDocs = ref([])

// 打开时重置选择
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    localSelectedDocs.value = []
  }
})

const handleClose = () => emit('close')

const handleDelete = () => {
  if (localSelectedDocs.value.length === 0) return
  emit('delete', [...localSelectedDocs.value])
}
</script>

<style scoped>
.doc-modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  animation: fadeIn 0.2s ease-out;
}

.doc-modal {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
  overflow: hidden;
}

.doc-modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.doc-modal-header h3 {
  margin: 0;
  font-size: 18px;
  color: #1f2937;
}

.close-btn {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #9ca3af;
}

.close-btn:hover {
  color: #4b5563;
}

.doc-modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.empty-docs {
  text-align: center;
  color: #9ca3af;
  padding: 40px 0;
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.doc-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
  transition: all 0.2s;
}

.doc-item:hover {
  border-color: #2563eb;
  background-color: #eff6ff;
}

.doc-checkbox-label {
  display: flex;
  align-items: center;
  cursor: pointer;
  width: 100%;
}

.doc-checkbox-label input {
  margin-right: 12px;
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.doc-icon {
  font-size: 20px;
  margin-right: 10px;
}

.doc-info {
  display: flex;
  flex-direction: column;
}

.doc-name {
  font-weight: 500;
  color: #1f2937;
}

.doc-modal-footer {
  padding: 16px 20px;
  border-top: 1px solid #e5e7eb;
  background-color: #f9fafb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.selection-info {
  font-size: 14px;
  color: #4b5563;
}

.delete-selected-btn {
  padding: 8px 16px;
  background-color: #ef4444;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.2s;
}

.delete-selected-btn:hover:not(:disabled) {
  background-color: #dc2626;
}

.delete-selected-btn:disabled {
  background-color: #fca5a5;
  cursor: not-allowed;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}
</style>