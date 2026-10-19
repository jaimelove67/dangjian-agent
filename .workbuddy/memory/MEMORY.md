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

## 运行与排障（本地开发）

- **后端端口 18000**（`.env: APP_PORT=18000`）。本机 8000 被别的项目占用，**不要拿 8000 当党建后端**（曾据此误判：8000 上服务的 JWT `userId` 是整数，本项目是 UUID）。
- 数据库：`postgresql://party_user:dev_password@127.0.0.1:55432/party_agent_dev`（容器 `party-agent-postgres-dev`）。查库用托管 Python + asyncpg 即可，无需进容器。
- 平台管理员：`admin` / `Test123456`（docs/PROJECT_OVERVIEW.md）。登录响应 `data.access_token`。
- **测试租户 TEST_TENANT（测试大学）可直接用于演示/讲解**：组织树 `TEST_ORG`(school 测试大学党委) → `TEST_DEP`(department 计算机学院党委) → `TEST_BRA`(branch 本科生第一党支部)；账号 `test-reviewer`(school_admin) / `test-dept`(department_admin) / `branch-secretary` / `test-organizer` / `test-member` / `test-applicant`，**口令统一 `Test123456`，实测全部可登录**；演示数据：知识文档 14、名册 6、投票 5、上报 7、选优 3、接转 2、问答 2。
- 数据库全表：public schema 共 35 张（含 `alembic_version`），按模块分 8 组（租户组织账号 3 / 知识库问答 3 / 党员发展 13 / 组织生活 2 / 中心组学习 2 / 年度考核 8 / 治理审计平台 7）。字段清单查 `information_schema.columns`，表用途看 `app/models/*.py` 的 docstring。共性字段 `id/tenant_id/created_at/updated_at/is_deleted`（软删除）。
- 租户：平台租户 `PLATFORM_TENANT`（党建平台）、`TEST_TENANT`（测试大学）、`a32a3207-9e53-4006-aae3-53208334aa88`（湖南科技职业技术学院，2026-10-17 建）。
- 组织树硬规则（`app/services/identity_service.py` `validate_tree`）：同租户只能一个 school 根组织；school 不能有父级；department 父级必须是 school；branch 父级是 school/department。
- 审计 `audit_logs` 对 422 只记 `{"route","method","status","duration_ms"}`，**不记错误正文**；定位要靠按参数复现调用。

## 本机环境：三个 Python，别搞混

- `.venv/Scripts/python.exe`（3.11.15）：**有 uvicorn，无 pytest** → 启后端用它。
- `venv-lock/Scripts/python.exe`：**有 pytest**（含 pytest_asyncio）→ 跑测试用它。
- `C:\Users\24746\AppData\Roaming\uv\python\...\python.exe`（进程列表里看到的那个）：**没有 uvicorn**，别拿它启服务。
- 后端启动（改动后**必须手动重启，没开 --reload**）：
  `cd E:/ali/dangjian-agent && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18000`
  临时验证可换 `--port 18001` 起第二实例，验完停掉。
- Bash 里 `timeout` 会命中 Windows 的 `timeout.exe`（语法不同），别用；`sleep` 也不存在，轮询用托管 Python 写。

## 前端工程（frontend/）

- **注意：当前实际前端是独立 Vite + Vue3 应用**（`frontend/vite.config.ts`，dev 端口 5666，代理目标 `VITE_API_TARGET`，默认 `http://localhost:8000` —— 与后端 18000 不一致，本地联调需显式设 `VITE_API_TARGET=http://localhost:18000`）。页面在 `frontend/src/views/*.vue`（GovernanceView 管组织/租户/账号）。下面 vben 5.7.0 的条目是更早的规划，已与现状不符。

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
- **本环境执行 `.py` 脚本文件会被静默拦截**：`python xxx.py args` 直接 exit 1，stdout/stderr 全空、连 traceback 都没有（换目录、换文件名、PowerShell、沙箱外都一样）。**必须用 `python -c '<代码>' args` 内联执行**。查库、md→docx 转换等都走内联；同样的代码内联跑完全正常。
- md→docx（python-docx 1.2.0 装在托管 Python 3.13.12）：只能内联；标题/正文/列表/表格/引用/代码块都支持，表格样式用 `Light Grid Accent 1`（默认模板存在），中文字体用 `微软雅黑` + `rFonts.set(qn('w:eastAsia'), ...)`。中文输出路径可能被 Bash 编码搞乱 → 先输出到 ASCII 路径再 `mv` 到中文名。
- 本仓库存在**并行工作流**，曾清空 `frontend/` 并回退记忆文件。**产出后立即提交**，不留未提交成果。
- 提交用平铺分支名（本机 git 无法保存嵌套引用，见用户级记忆）。
- **判定提交是否还在历史中，只信 `git rev-list HEAD | grep <sha>`**。本仓库 `git branch --contains` / `git merge-base --is-ancestor` 会给出错误答案（实测：`--contains` 声称包含某提交，而 `rev-list` 计数为 0）。


## 服务器部署（2026-10-17 上线）

- 目标机 129.204.32.148：腾讯云轻量服务器，OpenCloudOS 9.6（dnf），4核/3.6G/40G，本机 SSH 免密 root 可直连。代码在 `/opt/dangjian-agent`（离线包解压），编排 `docker-compose.server.yml`，容器 `party-agent-*`。
- **国内镜像拉取可靠方案**：`DOCKERHUB_MIRROR=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io`（华为云公开同步库）。DaoCloud/1ms 的 blob 走海外 CDN 会超时；dockerpull.cn 返回 HTML 错误页。该库缺 `python:3.11-slim-bookworm` 长 tag，用 `3.11-slim`。
- 构建期源全部 ARG 注入（默认值等价官方）：Dockerfile `BASE_IMAGE/APT_MIRROR/PIP_INDEX_URL`，frontend.http `NODE_IMAGE/NGINX_IMAGE/NPM_REGISTRY`（用 registry.npmmirror.com，腾讯 npm 路径 404）。**ARG 坑：stage 内 RUN 要用某 ARG，必须在 stage 内（FROM 之后）再声明一次，否则 shell 展开为空。**
- OpenCloudOS 装 Docker：腾讯镜像站的 docker-ce.repo 内容仍指官方源，须手写 repo 指向 `mirrors.cloud.tencent.com/docker-ce/linux/centos`。改 daemon.json 禁用 sed 替换含引号的值（会打碎 JSON），用 python/base64；docker 起不来先 `systemctl reset-failed`。
- `ENV` 必须保持 `development`（production 强制 DB/Redis TLS，单机编排无 TLS）。**排障：ready 状态一律以接口为准 `curl http://127.0.0.1/api/v1/health/ready`**；`docker compose exec app python` 起的新进程不跑 FastAPI lifespan，直接调 `_readiness_details()` 会误报 `redis=unhealthy` + `models=missing`（曾据此误判）。详情接口 `/api/v1/admin/health/ready` 需 system_admin。
- 百炼 Key 已配（不记明文，在服务器 `.env`），ready 200。模型名 `qwen3.8-flash` / `qwen3.7-text-embedding-flash` / `qwen3.7-text-rerank` 实测在百炼可用。
- 容器内跑脚本：`docker exec -w /app` 也找不到 `app` 模块（sys.path[0]=脚本目录），脚本内 `sys.path.insert(0,"/app")`；`ModelRegistry` 无 `list_providers`，用 `list_models(model_type=...)`。
- 部署实录：`docs/DEPLOY_SERVER.md`；**上线操作手册**：`docs/线上操作手册.md` + `docs/党建工作智能体上线操作手册.docx`（运维+使用合一）。
- **备份（实测可用）**：app 容器内**没有 pg_dump/pg_restore**，postgres 容器自带（16.3）→
  `docker exec party-agent-postgres pg_dump -U party_user -d party_agent -Fc > /root/backups/pg_$(date +%F).dump`；
  文件卷：`docker run --rm -v party-agent-server_originals:/data -v /root/backups:/out alpine tar czf /out/uploads_$(date +%F).tar.gz -C /data .`；
  应用内加密备份：`scripts/module6_backup.py backup --output <zip>`（恢复需同一套密钥，须连同 `.env` 一起保管）。
- 数据卷：`party-agent-server_{postgres_data,redis_data,originals,audit_spool}`；库 `party_agent` / 用户 `party_user`；磁盘 40G。
- 服务器开户后仍有待办：存在两条同名学校租户（有效 `d5584666…`，孤立 `e410e3b3…` 待清理）、演示数据待替换、初始口令待改。
- md→docx 的 bash 坑：把长内联 Python 直接塞进 Bash 命令行会因引号/中文触发 `unexpected EOF`；写 `tmp/xxx.sh`（heredoc 包 `python - <<'PYEOF'`）再 `bash tmp/xxx.sh` 才稳。

## 演示数据（2026-10-17 铺满，见 docs/DEMO_DATA.md）

- 种子脚本：`scripts/seed_demo_school.py`（租户/组织树/账号）、`seed_demo_business.py`（学习依据+考核指标/任务/归集）、`seed_demo_study_finish.py`（计划审核→活动→纪要→审核）。均走真实 HTTP API、幂等，容器内 `docker cp` 到 `/app/` 再 `docker compose exec -T app python /app/xxx.py`（容器内**没有 scripts 目录**）。
- 造业务数据的硬约束（踩过的坑）：① 学习只认 `effective` 资料，seed 文档默认 `expired`，先 `PATCH /knowledge-docs/{doc_id}/status`；② 依据要**计划级 + 条目级**两级 `source_doc_ids`；③ 写操作带 `expected_revision`，每次写完重新读再写下一步；④ 纪要三栏目须走 `generate-minutes`；⑤ 考核 `formula=sum` 只能配 `source=manual` + `source_options.measure=sum`；⑥ 任务须逐条审核，否则归集记「未审核内容」、run 审核 409；⑦ `POST /admin/users` 密码 ≥12 位；⑧ 审核不能自审，需第二个管理员账号（`school_admin2`）。
