# 前后端联调指南

> 更新日期：2026-10-09 ｜ 适用前端：`frontend/`（独立 **Vite + Vue 3 + TypeScript** 单页应用）
> ⚠️ 本文档已重写：早期版本描述的是 Vben Admin（`frontend/apps/web-antd` + pnpm），该结构**已不存在**。

---

## 1. 前端形态

| 项 | 说明 |
| --- | --- |
| 位置 | `frontend/`（独立工程，不依赖任何脚手架基座）|
| 技术栈 | Vite 8 + Vue 3.5 + TypeScript 6 + vue-router 4 + axios |
| 包管理 | **npm**（存在 `package-lock.json`；无需 pnpm）|
| 开发端口 | `5666` |
| 页面 | 登录 / 问答 / 知识库 / 党员发展 / 系统状态 / 404 |
| 接口层 | `src/api/`：`http.ts`（封装）、按模块拆分、`surface.ts`（能力矩阵）、`mock.ts`（示例数据）|

## 2. 启动

### 2.1 启动后端

```bash
# 依赖（Postgres 已在运行；启动 Redis）
docker start party-agent-redis-dev
# 数据库迁移（首次）
alembic upgrade head
# 启动后端（默认 8000；本机 8000 被占用时用其它端口，见 2.3）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端默认地址 `http://localhost:8000`，API 文档 `http://localhost:8000/docs`。

### 2.2 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5666
```

其它脚本：`npm run build`（`vue-tsc` 类型检查 + 生产构建）、`npm run typecheck`、`npm run preview`。

### 2.3 后端不在 8000 时（本机常见）

`vite.config.ts` 的开发代理把 `/api` 指向后端，**默认 `http://localhost:8000`**，可用环境变量 `VITE_API_TARGET` 覆盖：

```powershell
# 例：后端起在 18000（本机 8000 被其它项目 si-nginx 占用）
$env:VITE_API_TARGET='http://localhost:18000'
npm run dev
```

代理规则：`/api/*` → `${VITE_API_TARGET}/api/v1/*`（即把 `/api` 前缀重写为 `/api/v1`）。前端代码统一以 `/api` 为基准书写路径（见 `src/api/http.ts` 的 `baseURL: '/api'`）。

## 3. 接口契约

### 3.1 统一响应包裹体

所有接口返回：

```json
{ "code": 0, "message": "success", "data": { }, "trace_id": "..." }
```

- `src/api/http.ts` 响应拦截器：`code === 0` 时**只把 `data` 交给调用方**；否则抛 `ApiError`（携带 `code` 与 `trace_id`）。
- 认证：登录后 token 存 `localStorage`（键 `party.access_token` / `party.refresh_token`），请求自动带 `Authorization: Bearer <token>`。
- `401` / 权限失效会清除本地凭证，由路由守卫跳登录页；租户隔离错误码（`40302`）界面单独解释。

### 3.2 接口对接清单（以 `frontend/src/api/surface.ts` 为准）

**已提供 ✅**

| 前端调用 | 后端接口 | 方法 |
| --- | --- | --- |
| 登录 | `/api/v1/auth/login` | POST |
| 当前用户 | `/api/v1/auth/me` | GET |
| 刷新令牌 | `/api/v1/auth/refresh` | POST |
| 退出登录 | `/api/v1/auth/logout` | POST |
| 权限码 | `/api/v1/auth/codes` | GET |
| 制度问答 | `/api/v1/qa` | POST |
| 健康检查 | `/api/v1/health` | GET |
| 就绪检查 | `/api/v1/health/ready` | GET |
| 上传文件 | `/api/v1/knowledge-docs` | POST |
| 文件详情 | `/api/v1/knowledge-docs/{doc_id}` | GET |
| 变更文件状态 | `/api/v1/knowledge-docs/{doc_id}/status` | PATCH |
| 资格校验 | `/api/v1/member/qualification-check` | POST |
| 流转建议 | `/api/v1/member/transition-suggestion` | POST |
| 待办建议 | `/api/v1/member/todo-suggestions` | POST |
| 文字向量化 | `/api/v1/embeddings/embed` | POST |
| 批量向量化 | `/api/v1/embeddings/embed-all-pending` | POST |

**尚未提供（前端用 `mock.ts` 示例数据并打「示例数据」徽标）⛔**

| 能力 | 期望接口 | 影响页面 |
| --- | --- | --- |
| 文件列表 | `GET /api/v1/knowledge-docs` | 知识库 |
| 删除文件 | `DELETE /api/v1/knowledge-docs/{doc_id}` | 知识库 |
| 问答历史 | `GET /api/v1/qa/sessions` | 问答 |
| 培养对象名册 | `GET /api/v1/member/roster` | 党员发展 |
| 阶段流转提交 | `POST /api/v1/member/transition` | 党员发展 |

> 维护约定：后端补齐接口后，把 `surface.ts` 里对应 `available` 改为 `true`，**并同步移除**界面上的示例数据来源与徽标——**不允许只改一边**。「系统状态」页直接读取该矩阵展示。

## 4. 连通性自测

```powershell
# 后端直连
curl http://localhost:8000/api/v1/health
# 经前端代理（等价于后端 /api/v1/health；注意本机后端可能是 18000，代理目标相应调整）
curl http://localhost:5666/api/health
```

预期返回：

```json
{ "status": "healthy", "service": "党建工作智能体", "version": "1.0.0", "environment": "development" }
```

浏览器中观察：前端请求 `/api/auth/login` → 被代理为 `http://<后端>/api/v1/auth/login`。

## 5. 测试账号

系统**没有内置默认账号**（`init_db.sql` 只建扩展、不种用户）。开发/联调账号由脚本创建：

```bash
# 在仓库根目录本机执行，或在已有依赖的容器内执行：
python scripts/create_test_user.py                       # 默认 admin / admin123
python scripts/create_test_user.py --username u1 --password p1 --role member
```

默认创建（幂等，用户名已存在则跳过）：**`admin` / `admin123`**，角色 `system_admin`，租户 `tenant-demo`。

登录请求体：

```json
{ "username": "admin", "password": "admin123" }
```

> ⚠️ 默认口令仅用于开发/联调，生产环境务必更换并收紧 `ALLOWED_HOSTS`。

## 6. 常见问题

| 现象 | 排查 |
| --- | --- |
| 前端 404 / 连不上后端 | 后端未启动、端口不符；确认 `VITE_API_TARGET` 指向正确后端 |
| CORS 报错 | 确认后端 `ALLOWED_HOSTS`（开发用 `*`）与 `main.py` CORS 中间件 |
| 登录后仍未授权 | 检查 `localStorage` 中 token、请求头 `Authorization`、后端校验 |
| 上传文件报 `python-multipart` | 后端依赖缺失（见主仓库已知问题），需安装该包 |
| 页面显示「示例数据」 | 正常：对应后端列表接口尚未提供（见 §3.2）|

## 7. 合规红线在界面的落点

- **问答页**：每条回答附「依据充分性」结论与免责声明，引用角标可回溯原文。
- **党员发展页**：常驻决策边界声明，结果一律表述为「待人工确认」，不提供流转操作入口。
- **登录页/侧栏**：声明「辅助不代决」的产品边界。

## 8. 后续工作

- [ ] 后端补齐 §3.2 的 5 个接口，前端同步移除示例数据与徽标
- [ ] 前端单元测试 / E2E（仓库已含 Playwright 截图脚本 `frontend/scripts/screenshot-*.mjs`）
- [ ] 生产环境：修改 `SECRET_KEY`/密码、收紧 `ALLOWED_HOSTS`、关闭 `DEBUG`、启用 HTTPS

## 9. 相关文档

- [前端 README](../frontend/README.md)
- [后端 API 文档](http://localhost:8000/docs)（按实际端口访问）
- [测试文档](./TEST_PLAN.md) ｜ [开发规范文档](../开发规范文档.md)
