# MEMORY.md — 党建工作智能体 项目长期约定

## 部署与镜像源

- **镜像源不进代码**：所有镜像地址通过环境变量注入，不在 Dockerfile / compose 里写死加速源。
  - `DOCKERHUB_MIRROR`（默认 `docker.io`）
  - `GHCR_MIRROR`（默认 `ghcr.io`）
- `Dockerfile` / `Dockerfile.dev` 基础镜像用 `ARG BASE_IMAGE` + `FROM ${BASE_IMAGE}`，单独构建时用 `--build-arg BASE_IMAGE=...` 覆盖。
- `docker-compose.yml` / `docker-compose.dev.yml` 的每个 `image` 与 `build.args.BASE_IMAGE` 都写成 `${DOCKERHUB_MIRROR:-docker.io}/<name>`；ghcr.io 镜像用 `${GHCR_MIRROR:-ghcr.io}/<name>`。
- 默认值必须等价于原始官方地址，保证网络正常的机器上行为完全不变。
- 排障入口：`deploy/docker/MIRROR_GUIDE.md`；源自检：`scripts/check-docker-mirrors.sh`；离线分发：`scripts/offline-images.sh`（`save` / `load`）。

## 脚本约定

- `scripts/*.sh` 一律使用 LF 换行（在 Windows 上写完后需 `sed -i 's/\r$//'`）。
- 文档中统一用 `bash scripts/xxx.sh` 调用，不依赖文件执行位。

## Docker 镜像清单

- Docker Hub：`python:3.11-slim`、`pgvector/pgvector:pg16`、`redis:7-alpine`、`dpage/pgadmin4:latest`、`rediscommander/redis-commander:latest`
- 非 Docker Hub：`ghcr.io/huggingface/text-embeddings-inference:cpu-1.2`（`registry-mirrors` 对其无效）

## 已知陷阱

- `mirror.ccs.tencentyun.com` 是腾讯云**内网**专用加速器，非腾讯云机器必然失败，禁止写入推荐配置。
- 镜像加速器返回 HTML 错误页时，Docker 直接报 `unexpected media type text/html`，且**不会自动回退**到列表中的下一个可用源——一个坏源即可拖垮整次拉取。
- 该报错**不是** Docker Hub 官方限流（限流返回 429 + `toomanyrequests` JSON）。

## 前端工程（frontend/，vue-vben-admin 5.7.0）

- 路线：**分层复用**。外壳框架层与通用业务层复用脚手架/组件库，核心差异化层（引用角标→溯源卡、五大核验项、拒答态、入库前置校验）自研。
- 基座：vben 5.7.0 pnpm monorepo + turbo，开发目标 `apps/web-ele`（Element Plus）。
- 主题：`theme.colorPrimary = 'hsl(0 57% 41%)'`（#A32D2D）、`theme.mode = 'light'`、`app.accessMode = 'frontend'`。
- 路由：`accessMode: 'frontend'` 下，`src/router/routes/modules/*.ts` 由 `import.meta.glob` 自动合并，按 `meta.order` 进菜单。业务路由见 `modules/party.ts`。
- 接口层：`src/api/party/`（types / mock / qa / knowledge）。Mock 总开关 `PARTY_USE_MOCK`，接口就绪后置 false，页面零改动。
- **Element Plus 按需样式**：vben 只引入了部分组件样式，**缺 table / table-column / pagination / tag / select / option / message**。用到时须在 SFC 顶部显式 `import 'element-plus/es/components/<name>/style/css'`；禁止全量引入 `element-plus/dist/index.css`。
- 后端响应体 `{code, message, data, trace_id}` 与 vben `request.ts` 的 `{codeField:'code', dataField:'data', successCode:0}` 已天然契合。

## 已知陷阱（工程环境）

- 根 `.gitignore` 是 Python 模板，`.env` / `.env.*` 会误伤 vben 的 env 配置；已在末尾加 `!frontend/apps/*/.env`、`!frontend/apps/*/.env.*` 反向放行。
- **本会话 node 无法创建任何子进程（EBUSY errno -4082）**，跑不了 vite / vue-tsc / pnpm run；`pnpm install` 会在 esbuild postinstall 中断。前端构建需在用户自己终端执行。
- 本仓库存在**并行工作流**，曾清空 `frontend/` 并回退记忆文件。**产出后立即提交**，不留未提交成果。
- 提交用平铺分支名（本机 git 无法保存嵌套引用，见用户级记忆）。
- **判定提交是否还在历史中，只信 `git rev-list HEAD | grep <sha>`**。本仓库 `git branch --contains` / `git merge-base --is-ancestor` 会给出错误答案（实测：`--contains` 声称包含某提交，而 `rev-list` 计数为 0）。

