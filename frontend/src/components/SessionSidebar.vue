<template>
  <aside class="session-sidebar">
    <div class="sidebar-header">
      <h3>我的会话</h3>
      <button @click="handleCreateSession" class="new-session-btn">
        ➕ 新建会话
      </button>
    </div>
    
    <div class="session-list">
      <div 
        v-for="session in sessions" 
        :key="session.id"
        :class="['session-item', { active: currentSessionId === session.id }]"
        @click="handleSwitchSession(session.id)"
      >
        <span class="session-icon">💬</span>
        <span class="session-title">{{ session.title || '会话...' }}</span>
        <button 
          class="delete-btn" 
          @click.stop="handleDeleteSession(session.id)"
          title="删除会话"
        >
          ✕
        </button>
      </div>
      
      <div v-if="!isLoading && sessions.length === 0" class="empty-tip">
        暂无历史记录
      </div>
    </div>
  </aside>
</template>

<script setup>

const props = defineProps({
  sessions: {
    type: Array,
    required: true
  },
  currentSessionId: {
    type: String,
    default: ''
  },
  isLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['create', 'switch', 'delete'])

const handleCreateSession = () => emit('create')
const handleSwitchSession = (id) => emit('switch', id)
const handleDeleteSession = (id) => emit('delete', id)
</script>

<style scoped>
.session-sidebar {
  width: 260px;
  background-color: #ffffff;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #e5e7eb;
}

.sidebar-header h3 {
  margin: 0 0 15px 0;
  font-size: 16px;
  color: #374151;
}

.new-session-btn {
  width: 100%;
  padding: 10px;
  background-color: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.2s;
}

.new-session-btn:hover {
  background-color: #1d4ed8;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 12px;
  margin-bottom: 5px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  color: #4b5563;
  position: relative;
  padding-right: 40px;
}

.session-item:hover {
  background-color: #f3f4f6;
}

.session-item.active {
  background-color: #eff6ff;
  color: #2563eb;
  font-weight: 500;
}

.session-icon {
  margin-right: 10px;
  font-size: 16px;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-btn {
  opacity: 0.4;
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%) scale(0.9);
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: transparent;
  border: none;
  color: #9ca3af;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.delete-btn:hover {
  opacity: 1;
  transform: translateY(-50%) scale(1);
  background-color: #fee2e2;
  color: #ef4444;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.15);
}

.delete-btn:active {
  transform: translateY(-50%) scale(0.85);
}

.session-item.active .delete-btn {
  color: #93bbfc;
  opacity: 0.5;
}

.session-item.active .delete-btn:hover {
  background-color: #dbeafe;
  color: #2563eb;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.15);
}

.session-item:hover .delete-btn {
  opacity: 0.7;
}

.delete-btn:focus-visible {
  opacity: 1;
  outline: 2px solid #ef4444;
  outline-offset: 2px;
}

.empty-tip {
  text-align: center;
  color: #9ca3af;
  margin-top: 20px;
  font-size: 14px;
}

@media (max-width: 768px) {
  .session-sidebar { display: none; }
}
</style>