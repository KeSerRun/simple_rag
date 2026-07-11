<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <div class="app-shell">
      <n-loading-bar-provider>
        <n-message-provider>
          <n-dialog-provider>
            <router-view />
          </n-dialog-provider>
        </n-message-provider>
      </n-loading-bar-provider>
    </div>
  </n-config-provider>
</template>

<script setup>
import {
  NConfigProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NDialogProvider,
} from 'naive-ui'

const themeOverrides = {
  common: {
    primaryColor: '#d4734e',
    primaryColorHover: '#e08a65',
    primaryColorPressed: '#c06542',
    primaryColorSuppl: '#d4734e',
    borderRadius: '8px',
    fontWeightStrong: '600',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif',
    bodyColor: '#f5f2ef',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    tableColor: '#ffffff',
    dividerColor: '#d4cfc8',
    borderColor: '#d4cfc8',
    textColor1: '#1a1714',
    textColor2: '#4a4440',
    textColor3: '#6e6760',
  },
  Input: {
    color: '#ffffff',
    border: '#d4cfc8',
    borderHover: '#d4734e',
    borderFocus: '#d4734e',
    textColor: '#1a1714',
    placeholderColor: '#6e6760',
    lineHeightTextarea: '1.6',
  },
  Card: { borderRadius: '12px' },
  Button: { borderRadiusMedium: '8px' },
}
</script>

<style>
html,
body,
#app {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
}

html {
  background-color: #f5f2ef;
}

body {
  background-color: transparent;
}

.app-shell {
  min-height: 100vh;
  background-color: #f5f2ef;
}

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
