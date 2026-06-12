<template>
  <div class="register-container">
    <h2>用户注册</h2>
    <form @submit.prevent="handleRegister">
      <div class="form-item">
        <label for="reg-username">设置用户名:</label>
        <input type="text" id="reg-username" v-model="registerForm.username" placeholder="请输入用户名" required>
      </div>

      <div class="form-item">
        <label for="reg-password">设置密码:</label>
        <input type="password" id="reg-password" v-model="registerForm.password" placeholder="请输入密码" required>
      </div>

      <div class="form-item">
        <label for="confirm-password">确认密码:</label>
        <input type="password" id="confirm-password" v-model="registerForm.confirmPassword" placeholder="再次输入密码"
          required>
      </div>

      <button type="submit" :disabled="isLoading">
        {{ isLoading ? '注册中...' : '注册' }}
      </button>

      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

      <!-- 返回登录链接 -->
      <div class="login-link">
        <span>已有账号？</span>
        <router-link to="/login">返回登录</router-link>
      </div>
    </form>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from '@/http/interceptor'

const router = useRouter()

// 表单数据
const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: ''
})

const isLoading = ref(false)
const errorMessage = ref('')

const handleRegister = async () => {
  errorMessage.value = ''

  // 1. 前端简单校验：用户名和密码长度必须至少为6位
  if (registerForm.username.length < 6) {
    errorMessage.value = '用户名长度必须至少为6位'
    return
  } else if (!/^[a-zA-Z0-9]+$/.test(registerForm.username)) {
    errorMessage.value = '用户名只能包含英文字母和数字'
    return
  } else if (registerForm.password.length < 6) {
    errorMessage.value = '密码长度必须至少为6位'
    return
  } else if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[a-zA-Z\d]{6,}$/.test(registerForm.password)) {
    errorMessage.value = '密码必须同时包含英文大写、小写和数字'
    return
  }

  // 2. 前端简单校验：两次密码是否一致
  if (registerForm.password !== registerForm.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }

  isLoading.value = true

  try {
    // 3. 发送注册请求
    // 请将 '/api/register' 替换为你真实的后端注册接口
    const response = await axios.post('/api/register', {
      username: registerForm.username,
      password: registerForm.password
    })

    // 4. 处理成功响应
    if (response.status === 200 || response.status === 201) {
      alert('注册成功！即将跳转登录')
      // 注册成功后，自动跳转到登录页
      router.push('/login')
    } else {
      errorMessage.value = response.data.message || '注册失败'
    }
  } catch (error) {
    console.error('Register error:', error)
    // 根据后端返回的错误信息提示用户（例如：用户名已存在）
    errorMessage.value = error.response?.data?.message || '网络错误，请稍后重试'
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
/* 复用登录页的样式风格 */
.register-container {
  max-width: 400px;
  margin: 80px auto;
  /* 稍微调整上边距 */
  padding: 25px;
  border: 1px solid #ddd;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  font-family: sans-serif;
  background-color: #fff;
}

h2 {
  text-align: center;
  color: #333;
  margin-bottom: 20px;
}

.form-item {
  margin-bottom: 15px;
}

.form-item label {
  display: block;
  margin-bottom: 5px;
  color: #666;
  font-weight: bold;
}

.form-item input {
  width: 100%;
  padding: 10px;
  box-sizing: border-box;
  border: 1px solid #ccc;
  border-radius: 4px;
  outline: none;
}

.form-item input:focus {
  border-color: #007BFF;
  box-shadow: 0 0 5px rgba(0, 123, 255, 0.3);
}

button {
  width: 100%;
  padding: 12px;
  background-color: #28a745;
  /* 注册按钮用绿色区分 */
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
  transition: background 0.3s;
}

button:hover {
  background-color: #218838;
}

button:disabled {
  background-color: #cccccc;
  cursor: not-allowed;
}

.error-message {
  color: #dc3545;
  text-align: center;
  margin-top: 10px;
  font-size: 14px;
  background-color: #f8d7da;
  padding: 8px;
  border-radius: 4px;
}

.login-link {
  text-align: center;
  margin-top: 15px;
  font-size: 14px;
  color: #666;
}

.login-link a {
  color: #007BFF;
  text-decoration: none;
  margin-left: 5px;
}

.login-link a:hover {
  text-decoration: underline;
}
</style>