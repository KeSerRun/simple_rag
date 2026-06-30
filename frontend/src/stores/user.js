// src/stores/user.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useUserStore = defineStore('user', () => {
    // 从 localStorage 初始化 token 和 username
    const token = ref(localStorage.getItem('token') || '')
    const username = ref(localStorage.getItem('username') || '')
    const role = ref(localStorage.getItem('role') || '')
    // 回答风格偏好
    const answerStyle = ref(localStorage.getItem('answer_style') || 'style-default')

    // 计算属性：判断是否已登录，当 token 存在时认为已登录
    const isLoggedIn = computed(() => !!token.value)

    /**
     * 清除用户信息（登出）
     */
    const logout = () => {
        token.value = ''
        username.value = ''
        role.value = ''
    }

    return {
        token,
        username,
        role,
        answerStyle,
        isLoggedIn,
        logout
    }
}, {
    persist: {
        key: 'user',
        storage: localStorage,
        paths: ['token', 'username', 'role', 'answerStyle']
    }
})