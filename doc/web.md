# 前端

> 位置：`web/` — Vue 3 + Vite + Naive UI

## 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | Vue 3 (Composition API) |
| 构建 | Vite |
| UI 库 | Naive UI |
| 状态管理 | Pinia |
| HTTP | Axios |
| 图标 | @vicons/ionicons5 |
| 路由 | vue-router |

## 目录结构

```
web/src/
├── main.js                 # 入口
├── App.vue                 # 根组件
├── router/                 # 路由配置
├── stores/                 # Pinia stores
│   ├── user.js             #   用户认证
│   └── admin.js            #   管理后台
├── http/
│   └── interceptor.js      # Axios 拦截器 (JWT 注入 + 401 处理)
├── components/             # 通用组件
│   ├── ChatHeader.vue
│   ├── ChatInput.vue
│   ├── DocManagerModal.vue
│   ├── MessageList.vue
│   └── SessionSidebar.vue
├── views/                  # 页面
│   ├── Home.vue            # 对话页
│   ├── Login.vue           # 登录
│   ├── Register.vue        # 注册
│   └── admin/              # 管理后台
│       ├── AdminLayout.vue
│       ├── AdminDashboard.vue
│       ├── AdminDatabase.vue
│       ├── AdminEval.vue
│       ├── AdminLog.vue
│       ├── AdminSettings.vue
│       └── AdminUsers.vue
└── config/                 # 项目配置
```

## 页面路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | Home | 对话主页 |
| `/login` | Login | 用户登录 |
| `/register` | Register | 用户注册 |
| `/admin` | AdminLayout | 管理后台（含子路由） |

## 管理后台页面

| 页面 | 功能 |
|------|------|
| 仪表盘 | 请求统计、工具调用概览 |
| 系统设置 | 配置热更新（LLM/检索/MinerU/Agent/日志） |
| 数据管理 | 向量库统计、切块详情、系统数据上传 |
| 检索评估 | 测试查询编辑 → 评估 → 精确率报告 |
| 日志 | 日志文件查看/下载 |
| 用户管理 | 用户 CRUD、角色切换、密码重置 |

## 构建

```bash
cd web
npm install
npm run build       # 输出到 dist/
npm run dev         # 开发服务器 localhost:5173
```
