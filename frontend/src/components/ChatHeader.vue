<template>
  <header class="chat-header">
    <div class="header-left">
      <n-button
        class="menu-btn"
        quaternary
        circle
        size="small"
        @click="$emit('toggle-sidebar')"
      >
        <template #icon>
          <n-icon :component="MenuOutline" />
        </template>
      </n-button>
      <n-h3 class="title">{{ title }}</n-h3>
    </div>

    <n-space :size="6" align="center" class="header-actions">
      <n-button quaternary @click="$emit('open-doc-manager')">
        <template #icon>
          <n-icon :component="LibraryOutline" />
        </template>
        管理文档
        <n-tag
          v-if="documentCount > 0"
          round
          size="small"
          :bordered="false"
          style="margin-left: 6px"
        >
          {{ documentCount }}
        </n-tag>
      </n-button>

      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button quaternary circle @click="$emit('logout')">
            <template #icon>
              <n-icon :component="LogOutOutline" />
            </template>
          </n-button>
        </template>
        退出登录
      </n-tooltip>
    </n-space>
  </header>
</template>

<script setup>
import {
  NButton,
  NIcon,
  NSpace,
  NTag,
  NTooltip,
  NH3,
} from 'naive-ui'
import {
  LibraryOutline,
  LogOutOutline,
  MenuOutline,
} from '@vicons/ionicons5'

defineProps({
  title: { type: String, default: '新会话' },
  documentCount: { type: Number, default: 0 },
})

defineEmits(['open-doc-manager', 'logout', 'toggle-sidebar'])
</script>

<style scoped>
.chat-header {
  padding: 14px 24px;
  border-bottom: 1px solid var(--n-divider-color, #d4cfc8);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: var(--n-card-color, #ffffff);
  z-index: 10;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  min-width: 0;
  flex: 1 1 auto;
  gap: 6px;
}

/* 汉堡菜单按钮 */
.menu-btn {
  flex-shrink: 0;
}

.title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1 1 auto;
  min-width: 0;
}

/* 右侧操作区保持固定宽度 */
.header-actions {
  flex-shrink: 0;
}
</style>
