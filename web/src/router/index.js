import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue'
import Home from '@/views/Home.vue'

// admin 页面（懒加载）
const AdminLayout = () => import('@/views/admin/AdminLayout.vue')
const AdminDashboard = () => import('@/views/admin/AdminDashboard.vue')
const AdminSettings = () => import('@/views/admin/AdminSettings.vue')
const AdminUsers = () => import('@/views/admin/AdminUsers.vue')
const AdminLog = () => import('@/views/admin/AdminLog.vue')
const AdminDatabase = () => import('@/views/admin/AdminDatabase.vue')
const AdminEval = () => import('@/views/admin/AdminEval.vue')

// 定义路由
const routes = [
    { path: '/login', component: Login },
    { path: '/register', component: Register },
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: Home, meta: { requiresAuth: true } },
    // 管理后台
    {
        path: '/admin',
        component: AdminLayout,
        meta: { requiresAuth: true, requiresAdmin: true },
        redirect: '/admin/dashboard',
        children: [
            { path: 'dashboard', component: AdminDashboard, meta: { title: '仪表盘' } },
            { path: 'settings', component: AdminSettings, meta: { title: '系统设置' } },
            { path: 'users', component: AdminUsers, meta: { title: '用户管理' } },
            { path: 'logs', component: AdminLog, meta: { title: '日志查看' } },
            { path: 'database', component: AdminDatabase, meta: { title: '数据管理' } },
            { path: 'eval', component: AdminEval, meta: { title: '检索评估' } },
        ],
    },
]

// 创建路由实例
const router = createRouter({
    history: createWebHashHistory(),
    routes,
})

// 路由守卫
router.beforeEach((to) => {
    const userStore = useUserStore()

    if (to.meta.requiresAuth) {
        if (!userStore.isLoggedIn) {
            return '/login'
        }
        // admin 路由需要 admin 角色
        if (to.meta.requiresAdmin && userStore.role !== 'admin') {
            return '/chat'
        }
    } else {
        if ((to.path === '/login' || to.path === '/register') && userStore.isLoggedIn) {
            return '/chat'
        }
    }
})

export default router