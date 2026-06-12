<template>
  <header class="chat-header">
    <div class="header-left">
      <h2>🤖 {{ title }}</h2>
    </div>
    <div class="header-actions">
      <button v-if="userStore.role === 'admin'" @click="handleOpenDocManager" class="manage-docs-btn">
        📚 管理文档 ({{ documentCount }})
      </button>
      <button @click="handleLogout" class="logout-btn">退出登录</button>
    </div>
  </header>
</template>

<script setup>

import { useUserStore } from '@/stores/user'
const userStore = useUserStore()

const props = defineProps({
  title: {
    type: String,
    default: '未命名'
  },
  documentCount: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['open-doc-manager', 'logout'])

const handleOpenDocManager = () => emit('open-doc-manager')
const handleLogout = () => emit('logout')
</script>

<style scoped>
.chat-header {
  padding: 15px 24px;
  background-color: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  z-index: 10;
}

.header-left h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(to right, #2563eb, #9333ea);
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.manage-docs-btn {
  padding: 6px 12px;
  font-size: 13px;
  background-color: #f3f4f6;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.manage-docs-btn:hover {
  background-color: #e5e7eb;
}

.logout-btn {
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  background: transparent;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  color: #6b7280;
  transition: all 0.2s;
}

.logout-btn:hover {
  background-color: #f3f4f6;
  color: #ef4444;
  border-color: #ef4444;
}
</style>