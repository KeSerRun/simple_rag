import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue' // 1. 引入注册组件
import Home from '@/views/Home.vue'

// 定义路由
const routes = [
    { path: '/login', component: Login },
    { path: '/register', component: Register }, // 2. 添加注册路由
    { path: '/', component: Home, meta: { requiresAuth: true } },
]

// 创建路由实例
const router = createRouter({
    history: createWebHashHistory(),
    routes,
})

// 路由守卫
router.beforeEach((to, from) => {
    const userStore = useUserStore()

    if (to.meta.requiresAuth) {
        // 如果路由需要认证但用户未登录，重定向到登录页
        if (!userStore.isLoggedIn) {
            return '/login'
        }
    } else {
        // 如果已登录，访问登录/注册页时重定向回首页
        if ((to.path === '/login' || to.path === '/register') && userStore.isLoggedIn) {
            return '/'
        }
    }
})

export default router