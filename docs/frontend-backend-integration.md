# 前后端联调指南

## 📋 联调配置说明

本文档记录前后端联调的配置步骤和接口对接情况。

## 🔧 配置完成情况

### 后端配置

✅ **已完成：**
1. 创建 `.env` 文件（基于 `.env.example`）
2. 配置 CORS 允许跨域（`ALLOWED_HOSTS=*`）
3. 添加缺失的 API 接口：
   - `POST /api/v1/auth/refresh` - 刷新令牌
   - `POST /api/v1/auth/logout` - 退出登录
   - `GET /api/v1/auth/codes` - 获取权限码
   - `GET /api/v1/user/info` - 获取用户信息

### 前端配置

✅ **已完成：**
1. 修改 `frontend/apps/web-antd/vite.config.ts`：
   - 将 `/api` 代理到后端 `http://localhost:8000`
   - 路径重写：`/api` → `/api/v1`
2. 修改 `frontend/apps/web-antd/.env.development`：
   - 关闭 Mock 服务：`VITE_NITRO_MOCK=false`

## 🌐 API 接口对接清单

### 认证接口（Auth）

| 前端调用 | 后端接口 | 方法 | 状态 |
|---------|---------|------|------|
| `/auth/login` | `/api/v1/auth/login` | POST | ✅ 已对接 |
| `/auth/refresh` | `/api/v1/auth/refresh` | POST | ✅ 已对接 |
| `/auth/logout` | `/api/v1/auth/logout` | POST | ✅ 已对接 |
| `/auth/codes` | `/api/v1/auth/codes` | GET | ✅ 已对接 |

### 用户接口（User）

| 前端调用 | 后端接口 | 方法 | 状态 |
|---------|---------|------|------|
| `/user/info` | `/api/v1/user/info` | GET | ✅ 已对接 |

### 健康检查（Health）

| 前端调用 | 后端接口 | 方法 | 状态 |
|---------|---------|------|------|
| - | `/api/v1/health` | GET | ✅ 可用 |
| - | `/api/v1/health/ready` | GET | ✅ 可用 |
| - | `/api/v1/health/live` | GET | ✅ 可用 |

## 📊 数据格式说明

### 后端响应格式

所有接口统一返回以下格式：

```json
{
  "code": 0,           // 0 表示成功
  "message": "success",
  "data": {...},       // 实际数据
  "trace_id": "..."    // 请求追踪ID
}
```

### 前端处理

前端的 `request.ts` 已配置响应拦截器：
- `codeField: 'code'`
- `dataField: 'data'`
- `successCode: 0`

拦截器会自动提取 `data` 字段，因此前端 API 函数直接返回数据对象。

## 🚀 启动步骤

### 1. 启动后端服务

```bash
# 确保数据库和Redis已启动（如果需要）
# 或者使用 docker-compose 启动依赖服务
docker-compose -f docker-compose.dev.yml up -d postgres redis

# 运行数据库迁移
alembic upgrade head

# 启动后端服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端将运行在：`http://localhost:8000`
API 文档：`http://localhost:8000/docs`

### 2. 启动前端服务

```bash
cd frontend
pnpm install  # 如果还未安装依赖
cd apps/web-antd
pnpm dev
```

前端将运行在：`http://localhost:5666`

## 🧪 测试连通性

### 测试后端健康检查

```bash
curl http://localhost:8000/api/v1/health
```

预期返回：
```json
{
  "status": "healthy",
  "service": "党建工作智能体",
  "version": "1.0.0",
  "environment": "development"
}
```

### 测试前端代理

前端启动后，在浏览器开发者工具中观察网络请求：
- 前端请求 `/api/auth/login`
- 应该被代理到 `http://localhost:8000/api/v1/auth/login`

## 🔐 测试账号

根据数据库迁移脚本，可能已经创建了测试账号。如果需要创建测试用户，可以：

1. 使用 API 文档手动创建：访问 `http://localhost:8000/docs`
2. 或者运行数据库脚本插入测试用户

测试登录数据格式：
```json
{
  "username": "test_user",
  "password": "test_password"
}
```

## ⚠️ 注意事项

### 环境依赖

后端需要以下服务（可选，取决于功能模块）：
- PostgreSQL（用户认证、数据存储）
- Redis（缓存、会话管理）
- 如果只测试基本接口，可以暂时不启动这些服务，但部分功能会报错

### 开发模式

- 后端 `DEBUG=true`，启用 API 文档和详细错误信息
- 前端使用开发模式，启用热重载
- CORS 允许所有来源（`ALLOWED_HOSTS=*`）

### 生产环境注意

在生产环境部署时，需要修改：
1. `.env` 中的 `SECRET_KEY`、数据库密码等敏感信息
2. `ALLOWED_HOSTS` 设置为具体的前端域名
3. 关闭 `DEBUG` 模式
4. 使用 HTTPS

## 🐛 常见问题

### 1. CORS 错误

**症状：** 前端请求被浏览器拦截，提示跨域错误

**解决：**
- 检查后端 `.env` 中 `ALLOWED_HOSTS` 是否正确
- 确认后端 CORS 中间件已启用（在 `app/main.py` 中）

### 2. 代理失败

**症状：** 前端请求 404 或无法到达后端

**解决：**
- 确认后端已启动在 8000 端口
- 检查 `vite.config.ts` 中的代理配置
- 查看前端控制台和后端日志

### 3. 认证失败

**症状：** 登录后仍提示未授权

**解决：**
- 检查 JWT token 是否正确存储
- 查看前端请求头是否携带 `Authorization: Bearer <token>`
- 检查后端 token 验证逻辑

### 4. 数据库连接失败

**症状：** 后端启动时报数据库连接错误

**解决：**
- 确认 PostgreSQL 已启动
- 检查 `.env` 中的 `DATABASE_URL` 配置
- 运行 `alembic upgrade head` 初始化数据库

## 📝 后续工作

- [ ] 添加菜单接口（`/api/core/menu.ts` 调用的 `/menu/all`）
- [ ] 完善用户管理接口
- [ ] 添加知识库管理前端页面
- [ ] 完善错误处理和用户提示
- [ ] 添加前端单元测试
- [ ] 添加 E2E 测试

## 📚 相关文档

- [后端 API 文档](http://localhost:8000/docs) - FastAPI 自动生成
- [前端框架文档](https://doc.vben.pro/) - Vben Admin
- [项目开发规范](../开发规范文档.md)
