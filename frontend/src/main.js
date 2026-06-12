import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router' // 引入路由配置
import http from './http/interceptor'   // 引入http拦截器
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate' // 引入 Pinia 持久化插件

// 创建 Vue 应用
const app = createApp(App)

// 创建 Pinia 实例
const pinia = createPinia()
// 注册持久化插件
pinia.use(piniaPluginPersistedstate)

// 使用插件
app.use(pinia)
app.use(router)
app.config.globalProperties.$http = http

// 挂载到 DOM
app.mount('#app')