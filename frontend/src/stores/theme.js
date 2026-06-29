// src/stores/theme.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useThemeStore = defineStore('theme', () => {
    // 初始值由 persist 插件从 localStorage 恢复，这里仅作为兜底
    const mode = ref('light')

    const isDark = computed(() => mode.value === 'dark')

    const toggle = () => {
        mode.value = mode.value === 'dark' ? 'light' : 'dark'
    }

    const set = (m) => {
        if (m === 'light' || m === 'dark') mode.value = m
    }

    return { mode, isDark, toggle, set }
}, {
    persist: {
        key: 'theme-store',
        storage: localStorage,
    },
})
