<template>
  <div class="login-container">
    <h2>欢迎登录</h2>
    <form @submit.prevent="handleLogin">
      <!-- ...原有的用户名和密码输入框代码不变... -->
      <div class="form-item">
        <label for="username">用户名:</label>
        <input type="text" id="username" v-model="loginForm.username" placeholder="请输入用户名" required>
      </div>
      <div class="form-item">
        <label for="password">密码:</label>
        <input type="password" id="password" v-model="loginForm.password" placeholder="请输入密码" required>
      </div>

      <button type="submit" :disabled="isLoading">
        {{ isLoading ? '登录中...' : '登录' }}
      </button>

      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

      <!-- 👇 跳转到注册页面的链接 -->
      <div class="register-link">
        <span>还没有账号？</span>
        <router-link to="/register">立即注册</router-link>
      </div>
    </form>
  </div>
</template>

<script setup>
// ...原有的 script 代码保持不变...
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import axios from '@/http/interceptor'

const router = useRouter()
const userStore = useUserStore()
const loginForm = reactive({ username: '', password: '' })
// 禁止重复提交
const isLoading = ref(false)
const errorMessage = ref('')

// 登录处理函数
const handleLogin = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    if (loginForm.username.length < 6) {
      errorMessage.value = '用户名长度必须至少为6位'
      return
    } else if (!/^[a-zA-Z0-9]+$/.test(loginForm.username)) {
      errorMessage.value = '用户名只能包含英文字母和数字'
      return
    } else if (loginForm.password.length < 6) {
      errorMessage.value = '密码长度必须至少为6位'
      return
    } else if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d]{6,}$/.test(loginForm.password)) {
      errorMessage.value = '密码必须同时包含英文大写、小写和数字'
      return
    }
    const response = await axios.post('/api/login', {
      username: loginForm.username,
      password: loginForm.password
    })
    if (response.status === 200) {
      const token = response.data.token
      const username = response.data.user.username
      const role = response.data.user.role
      // 将 token 和 username 存储在 Pinia 中
      userStore.token = token
      userStore.username = username
      userStore.role = role
      router.push('/')
    }
  } catch (error) {
    console.error('登录失败:', error)
    errorMessage.value = error.response?.data?.message || '网络错误'
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
h2 {
  text-align: center;
  color: #333;
}

.form-item {
  margin-bottom: 15px;
}

.form-item label {
  display: block;
  margin-bottom: 5px;
  color: #666;
}

.form-item input {
  width: 100%;
  padding: 10px;
  box-sizing: border-box;
  border: 1px solid #ccc;
  border-radius: 4px;
}

button {
  width: 100%;
  padding: 12px;
  background-color: #007BFF;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
}

button:hover {
  background-color: #0056b3;
}

button:disabled {
  background-color: #cccccc;
  cursor: not-allowed;
}

.error-message {
  color: red;
  text-align: center;
  margin-top: 10px;
  font-size: 14px;
}

.login-container {
  max-width: 400px;
  margin: 100px auto;
  padding: 20px;
  border: 1px solid #ddd;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  font-family: sans-serif;
}

.register-link {
  text-align: center;
  margin-top: 15px;
  font-size: 14px;
  color: #666;
}

.register-link a {
  color: #007BFF;
  text-decoration: none;
  margin-left: 5px;
}

.register-link a:hover {
  text-decoration: underline;
}
</style>