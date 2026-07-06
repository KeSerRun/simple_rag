/**
 * 应用品牌配置 —— 统一管理所有展示名称，避免硬编码
 *
 * 修改后需重新 `npm run build` 生效
 */
const app = {
  // HTML 标题（来自 .env）
  title: import.meta.env.VITE_APP_TITLE || 'RAG Simple',
  // logo alt 文本
  alt: 'RAG Simple',
  // 登录/注册页品牌名（复用 VITE_APP_TITLE）
  brand: import.meta.env.VITE_APP_TITLE || 'RAG Simple',
  // 会话侧边栏标题
  sidebar: '会话管理',
  // 管理后台侧边栏标题
  admin: '管理后台',
}

export default app
