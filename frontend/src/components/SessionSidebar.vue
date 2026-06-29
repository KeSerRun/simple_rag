<template>
  <!-- 移动端 overlay 遮罩 -->
  <teleport to="body">
    <div
      v-if="drawerOpen"
      class="drawer-overlay"
      @click="$emit('close')"
    />
  </teleport>

  <aside :class="['session-sidebar', { 'drawer-open': drawerOpen }]">
    <div class="sidebar-header">
      <div class="brand">
        <n-icon :size="22" :component="ChatbubblesOutline" />
        <span class="brand-name">RAG 助手</span>
      </div>
      <n-button
        quaternary
        circle
        size="small"
        class="drawer-close-btn"
        @click="$emit('close')"
      >
        <template #icon>
          <n-icon :component="CloseOutline" />
        </template>
      </n-button>
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
          @click="selectSession(session.id)"
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

const props = defineProps({
  sessions: { type: Array, required: true },
  currentSessionId: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
  drawerOpen: { type: Boolean, default: true },
})

const emit = defineEmits(['create', 'switch', 'delete', 'close'])

// 选会话（不自动关闭，切换会话不应隐藏侧边栏）
const selectSession = (id) => {
  emit('switch', id)
}
</script>

<style scoped>
.session-sidebar {
  width: 280px;
  flex-shrink: 0;
  background-color: var(--n-card-color, #ffffff);
  border-right: 1px solid var(--n-divider-color, #d4cfc8);
  display: flex;
  flex-direction: column;
  height: 100%;
  z-index: 100;
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              transform 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

/* ─── 桌面端：折叠为 0 宽度 ─── */
@media (min-width: 769px) {
  .session-sidebar:not(.drawer-open) {
    width: 0;
    border-right: none;
  }
}

/* ─── overlay 遮罩（仅移动端生效） ─── */
.drawer-overlay {
  display: none;
}

/* ─── 移动端抽屉模式 ─── */
@media (max-width: 768px) {
  .drawer-overlay {
    display: block;
    position: fixed;
    inset: 0;
    background-color: rgba(0, 0, 0, 0.35);
    z-index: 200;
    animation: fadeIn 0.2s ease-out;
  }

  .session-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 210;
    width: 280px;
    transform: translateX(-100%);
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1),
                box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .session-sidebar.drawer-open {
    transform: translateX(0);
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.15);
  }

  /* 移动端不需要宽度过渡 */
  .session-sidebar:not(.drawer-open) {
    width: 280px;
  }
}

.sidebar-header {
  padding: 20px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #d4734c;
  padding: 0 4px;
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.drawer-close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
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
  color: var(--n-text-color-2, #4a4440);
  font-size: 14px;
  transition: background-color 0.15s ease, color 0.15s ease;
  position: relative;
  user-select: none;
}

.session-item:hover {
  background-color: rgba(120, 112, 104, 0.08);
}

.session-item.active {
  background-color: rgba(212, 115, 78, 0.12);
  color: #d4734e;
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

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
