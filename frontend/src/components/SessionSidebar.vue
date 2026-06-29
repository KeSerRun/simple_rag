<template>
  <aside class="session-sidebar">
    <div class="sidebar-header">
      <div class="brand">
        <n-icon :size="22" :component="ChatbubblesOutline" />
        <span class="brand-name">RAG 助手</span>
      </div>
      <n-button
        block
        type="primary"
        secondary
        @click="$emit('create')"
        class="new-session-btn"
      >
        <template #icon>
          <n-icon :component="AddOutline" />
        </template>
        新建会话
      </n-button>
    </div>

    <n-scrollbar class="session-scroll">
      <div class="session-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          :class="['session-item', { active: currentSessionId === session.id }]"
          @click="$emit('switch', session.id)"
        >
          <n-icon :size="16" class="session-icon" :component="ChatbubbleEllipsesOutline" />
          <span class="session-title">{{ session.title || '新会话' }}</span>

          <n-popconfirm
            placement="right"
            :show-icon="false"
            @positive-click="$emit('delete', session.id)"
          >
            <template #trigger>
              <n-button
                quaternary
                circle
                size="tiny"
                class="delete-btn"
                @click.stop
                aria-label="删除会话"
              >
                <template #icon>
                  <n-icon :component="CloseOutline" />
                </template>
              </n-button>
            </template>
            <span>确定删除该会话吗?</span>
          </n-popconfirm>
        </div>

        <n-empty
          v-if="!isLoading && sessions.length === 0"
          description="暂无会话"
          size="small"
          class="empty"
        />
      </div>
    </n-scrollbar>
  </aside>
</template>

<script setup>
import {
  NButton,
  NIcon,
  NScrollbar,
  NPopconfirm,
  NEmpty,
} from 'naive-ui'
import {
  ChatbubblesOutline,
  ChatbubbleEllipsesOutline,
  AddOutline,
  CloseOutline,
} from '@vicons/ionicons5'

defineProps({
  sessions: { type: Array, required: true },
  currentSessionId: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
})

defineEmits(['create', 'switch', 'delete'])
</script>

<style scoped>
.session-sidebar {
  width: 280px;
  flex-shrink: 0;
  background-color: var(--n-card-color, #ffffff);
  border-right: 1px solid var(--n-divider-color, #e8e6e2);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sidebar-header {
  padding: 20px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #cc785c;
  padding: 0 4px;
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.new-session-btn {
  font-weight: 500;
}

.session-scroll {
  flex: 1;
  min-height: 0;
}

.session-list {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--n-text-color-2, #5d5751);
  font-size: 14px;
  transition: background-color 0.15s ease, color 0.15s ease;
  position: relative;
  user-select: none;
}

.session-item:hover {
  background-color: rgba(120, 112, 104, 0.08);
}

.session-item.active {
  background-color: rgba(204, 120, 92, 0.12);
  color: #cc785c;
  font-weight: 500;
}

.session-icon {
  margin-right: 10px;
  flex-shrink: 0;
  opacity: 0.7;
}

.session-item.active .session-icon {
  opacity: 1;
}

.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.15s ease;
}

.session-item:hover .delete-btn,
.session-item.active .delete-btn {
  opacity: 0.7;
}

.session-item .delete-btn:hover {
  opacity: 1;
}

.empty {
  margin: 32px 0;
}

@media (max-width: 768px) {
  .session-sidebar {
    display: none;
  }
}
</style>
