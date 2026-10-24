# 前后端分离与运行

当前项目以 React 为业务前端、FastAPI 为后端。两端通过 HTTP `/api/v1` 通信，分别管理依赖、配置和构建。目录结构如下：

```text
frontend/
  src/                 React 页面、状态、接口适配
  public/              静态资源
  tests/               前端契约与回归检查
  deploy/              Nginx HTTP / HTTPS 配置
  package.json         前端独立命令及依赖
  package-lock.json    独立安装锁
  .env.example         浏览器可公开配置
  Dockerfile*          仅使用本目录构建前端镜像
backend/
  app/                 FastAPI API、鉴权、业务、模型接入
  migrations/          原有数据库迁移
  config/              服务端规则及模型配置
  tests/               后端回归
  requirements*.lock   Python 依赖锁
  .env.example         数据库、Redis、密钥、来源配置
  frontend/            保留的上游 Vue 参考源码，不参与当前应用启动与部署
scripts/dev.mjs         跨平台开发入口
scripts/prepare-sites-build.mjs
worker/、.openai/       原有 Sites 打包兼容文件
tests/sites-worker.test.mjs
package.json           workspace 命令，不持有应用依赖
```

根目录安装使用 Node.js 22+ 和 `npm ci`。前端也可单独复制到其他目录，在其目录执行 `npm ci`，无需后端、根目录脚本或 Sites 文件。

## 开发命令

| 根目录命令 | 行为 |
| --- | --- |
| `npm run dev` / `npm run dev:frontend` | 单独启动当前 React，默认演示模式，可按前端配置切换真实接口 |
| `npm run dev:backend` | 只启动 FastAPI，读取 `backend/.env` |
| `npm run dev:all` | 启动 FastAPI，存活检查成功后启动 React；自动选择真实接口模式，并将代理指向实际后端端口 |
| `npm run build:frontend` | 只构建前端，输出 `frontend/dist/` |
| `npm run build` | 保留原 Sites 打包入口，输出根目录 `dist/client/`、`dist/server/`、`dist/.openai/` |
| `npm run preview` | 预览 `frontend/dist/`；需先运行 `npm run build:frontend` |
| `npm test` | 前端回归与开发启动配置检查 |
| `npm run test:sites` | 检查原有 Sites 兼容构建，需要先执行根目录构建 |

开发入口默认仅监听本机，React 为 `127.0.0.1:4173`，FastAPI 为 `127.0.0.1:8000`。可以向前端传入 Vite 参数，例如 `npm run dev -- --port 4174`。后端读取 `backend/.env` 的 `PORT`（优先）或 `APP_PORT`；已有环境变量优先于文件配置。端口占用时明确退出，不停止原进程，也不会连接一个不明后端。

`PARTY_PYTHON` 可指定解释器。未指定时依次使用后端 `.venv`、`.venv-runtime`，最后使用系统 Python。统一入口关闭时同时停止它创建的服务进程。原 `backend/scripts/start-all.bat` 和 `start-all.sh` 已转到同一个入口。

## 后端环境

后端可完全独立运行，不需要安装 Node.js。在 `backend/` 内准备 Python 3.11+、独立虚拟环境及已有依赖锁：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
# 在 backend/.env 填写自己的实际数据库、Redis、密钥和允许的前端来源。
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

测试环境安装 `requirements-dev.lock`。数据库结构、原件存储和权限逻辑沿用原后端；开发入口不创建账号、不执行迁移、不清理数据。新环境的迁移与已有数据库接管按 [迁移说明](../backend/migrations/README.md) 执行。`/api/v1/health/live` 只表示进程存活；`/api/v1/health/ready` 返回真实依赖状态，可能因模型未配置等返回 503。

2026-10-24 新增账号安全、校级业务、课程活动和维护任务，唯一迁移头为 `031_backup_jobs`。`028`–`031` 为增量建表，不重建或清空原有业务表，不回填虚构业务记录。现有数据库升级仍须确认目标及备份后执行，开发启动不会自动代办。受控备份默认关闭，配置与隔离恢复边界见 [备份与恢复](backup-operations.md)。

## 接口和跨域

前端配置位于 `frontend/.env.local`，从 `frontend/.env.example` 复制。后端配置只放在 `backend/.env` 或后端进程环境中。

| 前端变量 | 默认值 | 用途 |
| --- | --- | --- |
| `VITE_DATA_MODE` | `demo` | `demo` 为本地演示，`live` 调用真实接口且不回退演示数据 |
| `VITE_API_TARGET` | `http://127.0.0.1:8000` | Vite 开发 / 预览代理目标，保留 `/api/v1` 路径 |
| `VITE_API_BASE_URL` | `/api/v1` | 浏览器请求前缀；也可填写 `https://api.example.edu/api/v1` |

同源托管时使用 `/api/v1`，在 Web 服务器把 `/api/` 转发到 FastAPI。独立域名时配置完整 API 地址，并在后端 `ALLOWED_HOSTS` 中填写前端的精确 Origin，例如 `["https://portal.example.edu"]`。此后端沿用 `ALLOWED_HOSTS` 作为 CORS 允许来源，值需包含协议及非默认端口。前端使用已有 Bearer Token 与刷新令牌机制，角色、租户和原件访问控制继续由后端验证。

所有 `VITE_` 配置均为构建时公开值，修改后需重启开发服务或重新构建。后端密钥不会从 `backend/.env` 复制给前端进程，Vite 文件访问范围限定为前端及依赖目录。

## 容器与 Sites

后端两个现有 Compose 模板已改为从 `../frontend` 构建当前 React 镜像。后端镜像继续仅从 `backend/` 构建 Python，前端镜像仅从 `frontend/` 构建静态页面。原有服务名、端口、数据库卷、原件卷和审计卷名称保持原值。

HTTP 试用模板为 `backend/docker-compose.server.yml`；TLS 生产模板为 `backend/docker-compose.yml`，沿用其来源、密钥、证书及隔离要求。开发模板 `backend/docker-compose.dev.yml` 可继续仅启动 PostgreSQL / Redis 或后端，再单独运行 React。打包脚本现在包含相邻的 `frontend/` 与 `backend/`，不会包含本机密钥、依赖环境或业务数据。

Sites 兼容文件保留原内容。Sites 静态包需要额外配置 API 反向代理或完整 API 地址及后端 CORS；本次目录拆分不会自动发布或托管 Python 后端。
