import axios from 'axios'
import { useUserStore } from '@/stores/user'

// 创建实例
const instance = axios.create()

// 请求拦截器：自动附加 Authorization
instance.interceptors.request.use(
    (config) => {
        const userStore = useUserStore()
        const token = userStore.token || localStorage.getItem('token')
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`
        }
        return config
    },
    (error) => Promise.reject(error)
)

// 响应拦截器：401 时清空登录状态并跳转登录页
instance.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            try {
                const userStore = useUserStore()
                userStore.logout()
            } catch (e) {
                // 兜底:即便 store 不可用也清空 localStorage
                localStorage.removeItem('user')
                localStorage.removeItem('token')
            }
            // 避免重复跳转
            if (!location.hash.startsWith('#/login')) {
                location.hash = '#/login'
            }
        }
        return Promise.reject(error)
    }
)

export default instance
