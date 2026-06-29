<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="themeOverrides">
    <n-loading-bar-provider>
      <n-message-provider>
        <n-dialog-provider>
          <router-view />
        </n-dialog-provider>
      </n-message-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup>
import { computed } from 'vue'
import {
  NConfigProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NDialogProvider,
  darkTheme
} from 'naive-ui'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()

const naiveTheme = computed(() => (themeStore.isDark ? darkTheme : null))

// 集中色板:Claude/ChatGPT 风,主色棕橙 + 米白/深灰背景
const themeOverrides = computed(() => {
  const dark = themeStore.isDark
  const primary = '#cc785c'
  const primaryHover = '#d68872'
  const primaryPressed = '#b96a4f'
  return {
    common: {
      primaryColor: primary,
      primaryColorHover: primaryHover,
      primaryColorPressed: primaryPressed,
      primaryColorSuppl: primary,
      borderRadius: '8px',
      fontWeightStrong: '600',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif',
      bodyColor: dark ? '#1a1a1a' : '#faf9f7',
      cardColor: dark ? '#252525' : '#ffffff',
      modalColor: dark ? '#252525' : '#ffffff',
      popoverColor: dark ? '#2a2a2a' : '#ffffff',
      tableColor: dark ? '#252525' : '#ffffff',
      dividerColor: dark ? '#333333' : '#e8e6e2',
      borderColor: dark ? '#333333' : '#e8e6e2',
      textColor1: dark ? '#ededed' : '#2c2825',
      textColor2: dark ? '#bdbdbd' : '#5d5751',
      textColor3: dark ? '#9a9a9a' : '#787068',
    },
    Card: { borderRadius: '12px' },
    Button: { borderRadiusMedium: '8px' },
    Input: { borderRadius: '10px' },
    Modal: {},
  }
})
</script>

<style>
html,
body,
#app {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Microsoft YaHei', Roboto, sans-serif;
}

/* 让 Naive UI 的全局背景生效 */
body {
  background-color: transparent;
}

/* 全局滚动条 - 与主题协调 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
::-webkit-scrollbar-thumb {
  background-color: rgba(120, 112, 104, 0.25);
  border-radius: 6px;
}
::-webkit-scrollbar-thumb:hover {
  background-color: rgba(120, 112, 104, 0.5);
}
::-webkit-scrollbar-track {
  background: transparent;
}
</style>
