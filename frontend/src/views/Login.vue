<template>
  <div class="auth-page">
    <n-card class="auth-card" :bordered="false" size="huge">
      <div class="auth-header">
        <div class="brand">
          <img :src="logoSvg" :alt="app.alt" class="brand-logo" />
          <span class="brand-name">{{ app.brand }}</span>
        </div>
        <n-h2 class="auth-title">欢迎回来</n-h2>
        <n-text depth="3">登录以继续与你的知识库对话</n-text>
      </div>

      <n-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        label-placement="top"
        @submit.prevent="handleLogin"
      >
        <n-form-item label="用户名" path="username">
          <n-input
            v-model:value="form.username"
            placeholder="请输入用户名"
            :input-props="{ autocomplete: 'username' }"
          >
            <template #prefix>
              <n-icon :component="PersonOutline" />
            </template>
          </n-input>
        </n-form-item>

        <n-form-item label="密码" path="password">
          <n-input
            v-model:value="form.password"
            type="password"
            show-password-on="click"
            placeholder="请输入密码"
            :input-props="{ autocomplete: 'current-password' }"
            @keydown.enter="handleLogin"
          >
            <template #prefix>
              <n-icon :component="LockClosedOutline" />
            </template>
          </n-input>
        </n-form-item>

        <n-button
          type="primary"
          size="large"
          block
          :loading="isLoading"
          attr-type="submit"
          @click="handleLogin"
        >
          {{ isLoading ? '登录中...' : '登 录' }}
        </n-button>
      </n-form>

      <n-divider style="margin: 24px 0 16px" />

      <div class="auth-footer">
        <n-text depth="3">还没有账号?</n-text>
        <router-link to="/register" class="auth-link">立即注册</router-link>
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard,
  NForm,
  NFormItem,
  NInput,
  NButton,
  NIcon,
  NH2,
  NText,
  NDivider,
  useMessage,
} from 'naive-ui'
import {
  PersonOutline,
  LockClosedOutline,
} from '@vicons/ionicons5'
import { useUserStore } from '@/stores/user'
import axios from '@/http/interceptor'
import logoSvg from '@/assets/logo.svg'
import app from '@/config/app'

const router = useRouter()
const userStore = useUserStore()
const message = useMessage()

const formRef = ref(null)
const isLoading = ref(false)
const form = reactive({ username: '', password: '' })

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 6, message: '用户名长度至少为 6 位', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9]+$/,
      message: '用户名只能包含英文字母和数字',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少为 6 位', trigger: 'blur' },
    {
      pattern: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d]{6,}$/,
      message: '密码必须同时包含大写、小写字母和数字',
      trigger: 'blur',
    },
  ],
}

const handleLogin = (e) => {
  if (e) e.preventDefault?.()
  formRef.value?.validate(async (errors) => {
    if (errors) return
    isLoading.value = true
    try {
      const response = await axios.post('/api/login', {
        username: form.username,
        password: form.password,
      })
      if (response.status === 200) {
        const { token, user } = response.data
        userStore.token = token
        userStore.username = user.username
        userStore.role = user.role
        message.success('登录成功')
        router.push('/')
      }
    } catch (error) {
      const detail = error.response?.data?.detail || error.response?.data?.message || '网络错误'
      message.error(detail)
    } finally {
      isLoading.value = false
    }
  })
}
</script>

<style scoped>
.auth-page {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(ellipse at top, rgba(212, 115, 78, 0.08), transparent 60%),
    transparent;
  padding: 24px;
  box-sizing: border-box;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.04), 0 2px 8px rgba(0, 0, 0, 0.03);
}

.auth-header {
  text-align: center;
  margin-bottom: 28px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  color: var(--brand-color, #d4734e);
}

.brand-logo {
  height: 28px;
  width: auto;
}

.brand-name {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.auth-title {
  margin: 0 0 6px 0;
}

.auth-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.auth-link {
  color: #d4734e;
  text-decoration: none;
  font-weight: 500;
}

.auth-link:hover {
  text-decoration: underline;
}
</style>
