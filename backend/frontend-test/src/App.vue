<template>
  <div class="app-container">
    <header class="app-header">
      <h1>🎯 党建工作智能体</h1>
      <p class="subtitle">前后端联调测试平台</p>
    </header>

    <div class="main-content">
      <!-- 健康检查卡片 -->
      <div class="card">
        <h2>🏥 服务健康检查</h2>
        <div class="status-info">
          <div class="status-item">
            <span class="label">后端状态:</span>
            <span :class="['status-badge', healthStatus ? 'success' : 'error']">
              {{ healthStatus ? '🟢 正常' : '🔴 异常' }}
            </span>
          </div>
          <div v-if="healthData" class="health-details">
            <p><strong>服务:</strong> {{ healthData.service }}</p>
            <p><strong>版本:</strong> {{ healthData.version }}</p>
            <p><strong>环境:</strong> {{ healthData.environment }}</p>
          </div>
        </div>
        <button @click="checkHealth" class="btn btn-primary" :disabled="loading">
          {{ loading ? '检查中...' : '重新检查' }}
        </button>
      </div>

      <!-- 登录卡片 -->
      <div class="card">
        <h2>🔐 用户登录测试</h2>
        <div v-if="!userInfo">
          <form @submit.prevent="handleLogin" class="login-form">
            <div class="form-group">
              <label>用户名:</label>
              <input
                v-model="loginForm.username"
                type="text"
                placeholder="请输入用户名"
                required
              />
            </div>
            <div class="form-group">
              <label>密码:</label>
              <input
                v-model="loginForm.password"
                type="password"
                placeholder="请输入密码"
                required
              />
            </div>
            <button type="submit" class="btn btn-success" :disabled="loading">
              {{ loading ? '登录中...' : '登录' }}
            </button>
          </form>
          <div class="hint">
            <p>💡 测试提示：需要先在后端创建测试用户</p>
          </div>
        </div>
        <div v-else class="user-info">
          <h3>✅ 登录成功</h3>
          <div class="info-grid">
            <div class="info-item">
              <span class="label">用户ID:</span>
              <span>{{ userInfo.id }}</span>
            </div>
            <div class="info-item">
              <span class="label">用户名:</span>
              <span>{{ userInfo.username }}</span>
            </div>
            <div class="info-item">
              <span class="label">姓名:</span>
              <span>{{ userInfo.name }}</span>
            </div>
            <div class="info-item">
              <span class="label">角色:</span>
              <span>{{ userInfo.role }}</span>
            </div>
            <div class="info-item">
              <span class="label">租户ID:</span>
              <span>{{ userInfo.tenant_id }}</span>
            </div>
            <div v-if="userInfo.email" class="info-item">
              <span class="label">邮箱:</span>
              <span>{{ userInfo.email }}</span>
            </div>
          </div>
          <div class="permissions" v-if="permissions.length">
            <h4>权限列表:</h4>
            <div class="permission-tags">
              <span v-for="perm in permissions" :key="perm" class="tag">
                {{ perm }}
              </span>
            </div>
          </div>
          <button @click="handleLogout" class="btn btn-danger">退出登录</button>
        </div>
      </div>

      <!-- API测试卡片 -->
      <div class="card">
        <h2>🔗 API 接口测试</h2>
        <div class="api-list">
          <div class="api-item">
            <span class="api-method post">POST</span>
            <span class="api-path">/api/v1/auth/login</span>
            <span class="api-status">{{ apiStatus.login }}</span>
          </div>
          <div class="api-item">
            <span class="api-method get">GET</span>
            <span class="api-path">/api/v1/user/info</span>
            <span class="api-status">{{ apiStatus.userInfo }}</span>
          </div>
          <div class="api-item">
            <span class="api-method get">GET</span>
            <span class="api-path">/api/v1/auth/codes</span>
            <span class="api-status">{{ apiStatus.codes }}</span>
          </div>
          <div class="api-item">
            <span class="api-method get">GET</span>
            <span class="api-path">/api/v1/health</span>
            <span class="api-status">{{ apiStatus.health }}</span>
          </div>
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="errorMessage" class="card error-card">
        <h3>❌ 错误信息</h3>
        <pre>{{ errorMessage }}</pre>
        <button @click="errorMessage = ''" class="btn btn-secondary">清除</button>
      </div>
    </div>

    <footer class="app-footer">
      <p>前端地址: <a href="http://localhost:5666" target="_blank">http://localhost:5666</a></p>
      <p>后端地址: <a href="http://localhost:8000" target="_blank">http://localhost:8000</a></p>
      <p>API文档: <a href="http://localhost:8000/docs" target="_blank">http://localhost:8000/docs</a></p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { login, getUserInfo, getPermissions, logout, healthCheck } from './api/auth'
import type { UserInfo } from './api/auth'

const loading = ref(false)
const healthStatus = ref(false)
const healthData = ref<any>(null)
const userInfo = ref<UserInfo | null>(null)
const permissions = ref<string[]>([])
const errorMessage = ref('')

const loginForm = ref({
  username: 'admin',
  password: 'admin123'
})

const apiStatus = ref({
  login: '未测试',
  userInfo: '未测试',
  codes: '未测试',
  health: '未测试'
})

// 检查健康状态
const checkHealth = async () => {
  loading.value = true
  try {
    const data = await healthCheck()
    healthData.value = data
    healthStatus.value = true
    apiStatus.value.health = '✅ 成功'
    errorMessage.value = ''
  } catch (error: any) {
    healthStatus.value = false
    apiStatus.value.health = '❌ 失败'
    errorMessage.value = error.message || '健康检查失败'
  } finally {
    loading.value = false
  }
}

// 登录
const handleLogin = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await login(loginForm.value)
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    apiStatus.value.login = '✅ 成功'

    // 获取用户信息
    await loadUserInfo()

    // 获取权限
    await loadPermissions()
  } catch (error: any) {
    apiStatus.value.login = '❌ 失败'
    errorMessage.value = error.response?.data?.message || error.message || '登录失败'
  } finally {
    loading.value = false
  }
}

// 加载用户信息
const loadUserInfo = async () => {
  try {
    const data = await getUserInfo()
    userInfo.value = data
    apiStatus.value.userInfo = '✅ 成功'
  } catch (error: any) {
    apiStatus.value.userInfo = '❌ 失败'
    errorMessage.value = error.message || '获取用户信息失败'
  }
}

// 加载权限
const loadPermissions = async () => {
  try {
    const data = await getPermissions()
    permissions.value = data
    apiStatus.value.codes = '✅ 成功'
  } catch (error: any) {
    apiStatus.value.codes = '❌ 失败'
  }
}

// 退出登录
const handleLogout = async () => {
  try {
    await logout()
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    userInfo.value = null
    permissions.value = []
    apiStatus.value.login = '未测试'
    apiStatus.value.userInfo = '未测试'
    apiStatus.value.codes = '未测试'
  } catch (error: any) {
    errorMessage.value = error.message || '退出失败'
  }
}

// 页面加载时检查健康状态
onMounted(() => {
  checkHealth()

  // 如果有token，尝试加载用户信息
  const token = localStorage.getItem('access_token')
  if (token) {
    loadUserInfo()
    loadPermissions()
  }
})
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}

.app-header {
  text-align: center;
  color: white;
  margin-bottom: 30px;
}

.app-header h1 {
  font-size: 2.5rem;
  margin: 0;
  text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
}

.subtitle {
  font-size: 1.2rem;
  opacity: 0.9;
  margin-top: 10px;
}

.main-content {
  max-width: 1200px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
  gap: 20px;
}

.card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}

.card h2 {
  margin-top: 0;
  color: #333;
  font-size: 1.5rem;
  border-bottom: 2px solid #667eea;
  padding-bottom: 10px;
}

.status-info {
  margin: 20px 0;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.label {
  font-weight: bold;
  color: #666;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.9rem;
  font-weight: bold;
}

.status-badge.success {
  background: #d4edda;
  color: #155724;
}

.status-badge.error {
  background: #f8d7da;
  color: #721c24;
}

.health-details {
  margin-top: 15px;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 8px;
}

.health-details p {
  margin: 8px 0;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 1rem;
  font-weight: bold;
  transition: all 0.3s;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background: #667eea;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #5568d3;
}

.btn-success {
  background: #28a745;
  color: white;
  width: 100%;
}

.btn-success:hover:not(:disabled) {
  background: #218838;
}

.btn-danger {
  background: #dc3545;
  color: white;
}

.btn-danger:hover {
  background: #c82333;
}

.btn-secondary {
  background: #6c757d;
  color: white;
}

.login-form {
  margin: 20px 0;
}

.form-group {
  margin-bottom: 15px;
}

.form-group label {
  display: block;
  margin-bottom: 5px;
  font-weight: bold;
  color: #333;
}

.form-group input {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 1rem;
  box-sizing: border-box;
}

.form-group input:focus {
  outline: none;
  border-color: #667eea;
}

.hint {
  margin-top: 15px;
  padding: 10px;
  background: #fff3cd;
  border-radius: 6px;
  color: #856404;
}

.user-info {
  margin-top: 15px;
}

.info-grid {
  display: grid;
  gap: 12px;
  margin: 20px 0;
}

.info-item {
  display: flex;
  justify-content: space-between;
  padding: 10px;
  background: #f8f9fa;
  border-radius: 6px;
}

.permissions {
  margin: 20px 0;
}

.permission-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.tag {
  padding: 4px 12px;
  background: #667eea;
  color: white;
  border-radius: 20px;
  font-size: 0.85rem;
}

.api-list {
  margin-top: 20px;
}

.api-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin-bottom: 10px;
  background: #f8f9fa;
  border-radius: 6px;
}

.api-method {
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: bold;
  font-size: 0.85rem;
  min-width: 50px;
  text-align: center;
}

.api-method.get {
  background: #28a745;
  color: white;
}

.api-method.post {
  background: #007bff;
  color: white;
}

.api-path {
  flex: 1;
  font-family: monospace;
  font-size: 0.9rem;
}

.api-status {
  font-size: 0.9rem;
}

.error-card {
  grid-column: 1 / -1;
  background: #f8d7da;
  border: 1px solid #f5c6cb;
}

.error-card pre {
  background: white;
  padding: 15px;
  border-radius: 6px;
  overflow-x: auto;
  color: #721c24;
}

.app-footer {
  text-align: center;
  color: white;
  margin-top: 30px;
  padding: 20px;
}

.app-footer a {
  color: white;
  text-decoration: underline;
}

.app-footer p {
  margin: 5px 0;
}
</style>
