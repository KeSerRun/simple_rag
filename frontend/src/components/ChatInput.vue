<template>
  <div class="input-area">
    <input type="file" ref="fileInput" style="display: none;" @change="handleFileUpload" multiple>
    <button v-if="userStore.role === 'admin'" @click="$refs.fileInput.click()" :disabled="isUploading"
      class="upload-btn" title="上传文件">
      📎
    </button>
    <textarea v-model="inputValue" @keydown.enter.prevent="handleSend" placeholder="请输入你的问题..." rows="1"></textarea>
    <button @click="handleSend" :disabled="!inputValue.trim() || isLoading">
      {{ isLoading ? '思考中...' : '发送' }}
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useUserStore } from "@/stores/user";
const userStore = useUserStore()

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  },
  isUploading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['send', 'upload'])

const inputValue = ref('')
const fileInput = ref(null)

const handleSend = () => {
  const text = inputValue.value.trim()
  if (!text || props.isLoading) return

  emit('send', text)
  inputValue.value = ''
}

const handleFileUpload = (event) => {
  emit('upload', event)
  // 重置 input 以便可以重复选择同一文件
  event.target.value = ''
}
</script>

<style scoped>
.input-area {
  padding: 24px;
  background-color: #ffffff;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 12px;
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.03);
}

.upload-btn {
  padding: 0 12px;
  background-color: #f3f4f6;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  cursor: pointer;
  font-size: 20px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-btn:hover:not(:disabled) {
  background-color: #e5e7eb;
}

.upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

textarea {
  flex: 1;
  padding: 14px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  resize: none;
  outline: none;
  font-family: inherit;
  font-size: 15px;
  background-color: #f9fafb;
  transition: all 0.2s;
  min-height: 24px;
  max-height: 150px;
}

textarea:focus {
  background-color: #fff;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

button {
  padding: 0 24px;
  background-color: #2563eb;
  color: white;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-weight: 600;
  font-size: 15px;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
}

button:hover:not(:disabled) {
  background-color: #1d4ed8;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(37, 99, 235, 0.3);
}

button:disabled {
  background-color: #9ca3af;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

@media (max-width: 768px) {
  .input-area {
    padding: 16px;
  }
}
</style>