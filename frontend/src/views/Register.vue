<template>
  <div class="auth-page">
    <n-card class="auth-card" :bordered="false" size="huge">
      <div class="auth-header">
        <div class="brand">
          <n-icon :size="28" :component="ChatbubblesOutline" />
          <span class="brand-name">RAG 助手</span>
        </div>
        <n-h2 class="auth-title">创建账号</n-h2>
        <n-text depth="3">注册一个新账号开始使用</n-text>
      </div>

      <n-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        label-placement="top"
        @submit.prevent="handleRegister"
      >
        <n-form-item label="用户名" path="username">
          <n-input v-model:value="form.username" placeholder="6 位以上的英文字母或数字">
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
            placeholder="至少 6 位,含大小写字母与数字"
          >
            <template #prefix>
              <n-icon :component="LockClosedOutline" />
            </template>
          </n-input>
        </n-form-item>

        <n-form-item label="确认密码" path="confirmPassword">
          <n-input
            v-model:value="form.confirmPassword"
            type="password"
            show-password-on="click"
            placeholder="再次输入密码"
            @keydown.enter="handleRegister"
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
          @click="handleRegister"
        >
          {{ isLoading ? '注册中...' : '创建账号' }}
        </n-button>
      </n-form>

      <n-divider style="margin: 24px 0 16px" />

      <div class="auth-footer">
        <n-text depth="3">已有账号?</n-text>
        <router-link to="/login" class="auth-link">返回登录</router-link>
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
  ChatbubblesOutline,
  PersonOutline,
  LockClosedOutline,
} from '@vicons/ionicons5'
import axios from '@/http/interceptor'

const router = useRouter()
const message = useMessage()

const formRef = ref(null)
const isLoading = ref(false)
const form = reactive({ username: '', password: '', confirmPassword: '' })

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
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (rule, value) => value === form.password,
      message: '两次输入的密码不一致',
      trigger: 'blur',
    },
  ],
}

const handleRegister = (e) => {
  if (e) e.preventDefault?.()
  formRef.value?.validate(async (errors) => {
    if (errors) return
    isLoading.value = true
    try {
      const response = await axios.post('/api/register', {
        username: form.username,
        password: form.password,
      })
      if (response.status === 200 || response.status === 201) {
        message.success('注册成功,即将跳转登录')
        setTimeout(() => router.push('/login'), 800)
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
  background: radial-gradient(ellipse at top, rgba(204, 120, 92, 0.08), transparent 60%),
    var(--n-body-color, #faf9f7);
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
  gap: 8px;
  margin-bottom: 16px;
  color: #cc785c;
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
  color: #cc785c;
  text-decoration: none;
  font-weight: 500;
}

.auth-link:hover {
  text-decoration: underline;
}
</style>
