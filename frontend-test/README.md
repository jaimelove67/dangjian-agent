# 党建工作智能体 - 前端测试平台

这是一个用于测试党建工作智能体后端API的前端测试平台。

## 🚀 快速开始

```bash
npm install
npm run dev
```

访问: http://localhost:5666

## 📋 功能特性

- ✅ 服务健康检查
- ✅ 用户登录测试
- ✅ Token 管理
- ✅ 用户信息展示
- ✅ 权限列表展示
- ✅ API 状态监控
- ✅ 错误信息提示

## 🔧 配置

### 后端地址
在 `vite.config.ts` 中配置：
```typescript
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, '/api/v1')
  }
}
```

### API 基础路径
在 `src/utils/request.ts` 中配置：
```typescript
baseURL: '/api'
```

## 📁 项目结构

```
src/
├── api/
│   └── auth.ts          # API 接口定义
├── utils/
│   └── request.ts       # Axios 封装
├── App.vue              # 主应用组件
└── main.ts              # 应用入口
```

## 🔗 接口列表

- POST /api/v1/auth/login - 用户登录
- GET /api/v1/user/info - 获取用户信息
- GET /api/v1/auth/codes - 获取权限码
- POST /api/v1/auth/logout - 退出登录
- GET /api/v1/health - 健康检查

## 💡 使用提示

1. 页面加载后会自动检查后端健康状态
2. 需要先在后端创建测试用户才能登录
3. 登录后 token 会自动保存到 localStorage
4. 所有 API 请求会自动添加 Authorization header

## 🛠️ 技术栈

- Vue 3
- TypeScript
- Vite
- Axios

## 📝 开发命令

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```
