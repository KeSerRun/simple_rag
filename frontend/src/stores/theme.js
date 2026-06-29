// src/stores/theme.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useThemeStore = defineStore('theme', () => {
    // 默认明色
    const mode = ref(localStorage.getItem('theme-mode') || 'light')

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
