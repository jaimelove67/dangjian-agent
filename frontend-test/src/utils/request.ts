import axios from 'axios'

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 从 localStorage 获取 token
    const token = localStorage.getItem('access_token')
    if (token && !config.headers.has('Authorization')) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  (response) => {
    const res = response.data
    // 后端统一响应格式: {code, message, data, trace_id}
    if (res.code === 0) {
      return res.data
    } else {
      console.error('API Error:', res.message)
      return Promise.reject(new Error(res.message || 'Error'))
    }
  },
  (error) => {
    console.error('Request Error:', error.message)
    return Promise.reject(error)
  }
)

export default request
