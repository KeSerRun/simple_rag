import axios from 'axios'
import { useUserStore } from '@/stores/user'

// 创建实例
const instance = axios.create()

// 请求拦截器
instance.interceptors.request.use(
    (config) => {
        const userStore = useUserStore()
        const token = userStore.token || localStorage.getItem('token')
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`
        }

        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

// 响应拦截器(可选，处理全局错误)
// instance.interceptors.response.use(
//     (response) => response,
//     (error) => {
//         if (error.response?.status === 401) {
//             // Token 过期或无效，跳转登录
//             localStorage.removeItem('token')
//             window.location.href = '/login'
//         }
//         return Promise.reject(error)
//     }
// )

export default instance