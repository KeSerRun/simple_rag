<template>
  <div class="admin-layout">
    <!-- 侧边栏 -->
    <aside class="admin-sidebar">
      <div class="sidebar-brand">
        <n-icon :size="22" :component="TerminalOutline" />
        <span class="brand-text">RAG Admin</span>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <n-icon :size="18" :component="item.icon" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <router-link to="/" class="nav-item back-link">
          <n-icon :size="18" :component="ArrowBackOutline" />
          <span>返回主界面</span>
        </router-link>
        <a class="nav-item logout-link" @click="handleLogout">
          <n-icon :size="18" :component="LogOutOutline" />
          <span>退出登录</span>
        </a>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="admin-main">
      <header class="admin-header">
        <n-breadcrumb>
          <n-breadcrumb-item>管理后台</n-breadcrumb-item>
          <n-breadcrumb-item>{{ currentTitle }}</n-breadcrumb-item>
        </n-breadcrumb>
        <div class="header-right">
          <n-tag v-if="userStore.role === 'admin'" type="warning" size="small" :bordered="false">
            Admin
          </n-tag>
        </div>
      </header>
      <div class="admin-content">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import {
  NIcon, NBreadcrumb, NBreadcrumbItem, NTag,
} from 'naive-ui'
import {
  TerminalOutline,
  SpeedometerOutline,
  SettingsOutline,
  PeopleOutline,
  DocumentTextOutline,
  ServerOutline,
  ArrowBackOutline,
  LogOutOutline,
} from '@vicons/ionicons5'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const menuItems = [
  { path: '/admin/dashboard', label: '仪表盘', icon: SpeedometerOutline },
  { path: '/admin/settings', label: '系统设置', icon: SettingsOutline },
  { path: '/admin/users', label: '用户管理', icon: PeopleOutline },
  { path: '/admin/logs', label: '日志查看', icon: DocumentTextOutline },
  { path: '/admin/database', label: '数据管理', icon: ServerOutline },
]

const currentTitle = computed(() => {
  const item = menuItems.find(m => isActive(m.path))
  return item ? item.label : ''
})

function isActive(path) {
  return route.path === path
}

function handleLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  display: flex;
  height: 100vh;
  background-color: #f5f2ef;
}

/* 侧边栏 */
.admin-sidebar {
  width: 220px;
  min-width: 220px;
  background: #fff;
  border-right: 1px solid #d4cfc8;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 20px 18px;
  border-bottom: 1px solid #d4cfc8;
  color: #d4734e;
  font-size: 16px;
  font-weight: 600;
}

.brand-text {
  letter-spacing: 0.5px;
}

.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  color: #4a4440;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-item:hover {
  background: #f0edeb;
  color: #d4734e;
}

.nav-item.active {
  background: #fef3ef;
  color: #d4734e;
  font-weight: 500;
}

.sidebar-footer {
  padding: 12px 8px;
  border-top: 1px solid #d4cfc8;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.back-link {
  color: #6e6760;
}

.logout-link {
  color: #e74c3c;
}

.logout-link:hover {
  background: #fef0ef;
}

/* 主内容区 */
.admin-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px;
  background: #fff;
  border-bottom: 1px solid #d4cfc8;
  flex-shrink: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-content {
  flex: 1;
  padding: 24px 28px;
  overflow: auto; /* 允许横向和纵向滚动 */
  display: flex;
  flex-direction: column;
}

/* 确保内容区有一个最小的合适阅读宽度，如果窗口比这还窄，就会出横向滚动条而不是挤压内容 */
.admin-content > :first-child {
  min-width: 900px; /* 设为900px保证多列布局不会被挤扁 */
  flex: 1; /* 让子页面组件能伸展填满高度（如果需要） */
}
</style>
