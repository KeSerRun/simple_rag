<template>
  <header class="chat-header">
    <div class="header-left">
      <n-h3 class="title">{{ title }}</n-h3>
    </div>

    <n-space :size="6" align="center">
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
          <n-button quaternary circle @click="themeStore.toggle">
            <template #icon>
              <n-icon :component="themeStore.isDark ? SunnyOutline : MoonOutline" />
            </template>
          </n-button>
        </template>
        {{ themeStore.isDark ? '切换到亮色' : '切换到暗色' }}
      </n-tooltip>

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
  MoonOutline,
  SunnyOutline,
  LogOutOutline,
} from '@vicons/ionicons5'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()

defineProps({
  title: { type: String, default: '新会话' },
  documentCount: { type: Number, default: 0 },
})

defineEmits(['open-doc-manager', 'logout'])
</script>

<style scoped>
.chat-header {
  padding: 14px 24px;
  border-bottom: 1px solid var(--n-divider-color, #e8e6e2);
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
}

.title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60vw;
}
</style>
