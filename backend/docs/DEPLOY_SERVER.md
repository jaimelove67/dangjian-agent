# 上线部署手册（129.204.32.148）

编写日期：2026-10-17。目标：把党建工作智能体部署到腾讯云服务器 `129.204.32.148`，公网可访问。

**部署状态：已完成（2026-10-17 16:25）。** 实际部署记录见文末「九、实际部署记录」。

当前状态：服务器 22 端口通、80/443 未放行；无 SSH 密码，需先在腾讯云控制台放行端口并拿到 root 终端。

---

## 一、你需要做的三步

| 步骤 | 位置 | 说明 |
| --- | --- | --- |
| 1. 放行 TCP 80 | 腾讯云控制台 → 安全组 | 否则外网打不开页面 |
| 2. 打开网页终端 | 控制台 → 云服务器 → 实例 → 「登录」 | OrcaTerm 网页终端，root 身份，无需密码 |
| 3. 粘贴一条命令 | 网页终端 | 见下面方案 A 或 B |

安全组放行：控制台 → 云服务器 → 实例 → 点实例名 → 「安全组」页签 → 修改规则 → 入站规则添加 `TCP:80`，来源 `0.0.0.0/0`。后续要 HTTPS 再放行 `TCP:443`。

---

## 二、方案 A：授权本机 SSH，后续全自动（推荐）

网页终端粘贴这一行（把本机公钥写进服务器，之后我可直接 SSH 操作，你无需再手动粘贴）：

```bash
mkdir -p ~/.ssh && echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAZRg14sprd9+SPsEnJ+BYF+2XAZBGhmI0Gz6r+mVWbl dangjian-agent-deploy' >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys && (grep -q '^PubkeyAuthentication yes' /etc/ssh/sshd_config || sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config); systemctl restart sshd 2>/dev/null || service ssh restart; echo "AUTHKEY_OK"
```

看到 `AUTHKEY_OK` 后回复一声，剩下的我来完成：上传代码包（4.68 MB，本机已打包，不依赖 GitHub）→ 安装 Docker → 生成随机密钥 → 构建镜像 → 数据库迁移 → 启动 → 健康检查。

---

## 三、方案 B：自己全程在网页终端操作

服务器能访问 GitHub 时（国内机器可能慢，失败可重试 2-3 次）：

```bash
curl -fsSL https://raw.githubusercontent.com/jaimelove67/dangjian-agent/master/deploy/server/bootstrap.sh | bash
```

脚本依次完成：安装 Docker → clone 代码到 `/opt/dangjian-agent` → 生成随机密钥的 `.env` → 构建镜像 → 启动 PostgreSQL/Redis → Alembic 迁移 → 启动应用与前端 → 打印健康检查。

GitHub 拉不动时走方案 A，代码改由本机上传。

---

## 四、部署架构（单机简化版）

```
外网 :80  →  Nginx 容器（frontend，SPA 静态资源）
                └─ /api/* 反代 → app 容器 :8000（FastAPI）
                                    ├─ postgres 容器 :5432（pgvector）
                                    └─ redis 容器 :6379
```

编排文件 `docker-compose.server.yml`，服务名前缀 `party-agent-*`。内存小于 3G 时脚本自动加 2G swap，避免前端构建 OOM。

---

## 五、部署后验证

```bash
cd /opt/dangjian-agent
curl http://127.0.0.1/api/v1/health/live     # 存活检查
curl http://127.0.0.1/api/v1/health/ready    # 就绪检查（DB/Redis/表/模型注册）
docker compose -f docker-compose.server.yml ps
docker stats --no-stream
```

浏览器打开 `http://129.204.32.148`。管理员开户见 `docs/RUNNING.md`。

---

## 六、需要注意的点

- **ENV 保持 development**：`ENV=production` 会强制 DB/Redis 走 TLS，当前单机编排未配 TLS，改了会启动失败。
- **DASHSCOPE_API_KEY 留空可启动**，但智能问答与向量化不可用。拿到 Key 后：
  ```bash
  sed -i 's|^DASHSCOPE_API_KEY=.*|DASHSCOPE_API_KEY=sk-你的Key|' /opt/dangjian-agent/.env
  cd /opt/dangjian-agent && docker compose -f docker-compose.server.yml up -d app
  ```
- **本地未提交改动不上线**：服务器用的是 GitHub `master`。本机工作区有未提交改动（党员发展名册筛选、`app/api/v1/admin.py`、`governance.py` 等），上线前需先提交并推送，或走方案 A 用本机代码包。
- **HTTP 明文仅用于验证**，正式对外应配 HTTPS（`config/nginx-production.conf`）。
- **镜像拉取失败**：改 `.env` 的 `DOCKERHUB_MIRROR`，先用 `scripts/check-docker-mirrors.sh` 自检，见 `deploy/docker/MIRROR_GUIDE.md`。
- **看日志**：`docker compose -f docker-compose.server.yml logs -f app`。

---

## 九、实际部署记录（2026-10-17）

- 机器：腾讯云**轻量应用服务器**，OpenCloudOS 9.6，4 核 / 3.6G 内存 / 40G 盘，代码在 `/opt/dangjian-agent`。
- 防火墙：轻量控制台已放行 22 / 80 / ICMP。
- Docker：docker-ce 29.9.1 + compose v5.6.0，repo 指向 `mirrors.cloud.tencent.com/docker-ce`（`/etc/yum.repos.d/docker-ce.repo` 手写，腾讯镜像站自带的 `.repo` 文件内容仍指向官方源，国内不可用）。
- **Docker Hub 镜像拉取**（重要）：直连超时；DaoCloud / 1ms 的 blob 层走海外 CDN 也超时；`dockerpull.cn` 返回 HTML 错误页。**可用方案 = 华为云公开同步库前缀**：
  `DOCKERHUB_MIRROR=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io`
  注意该库没同步 `python:3.11-slim-bookworm`，用 `python:3.11-slim` 代替（同为 bookworm）。
- 构建期 apt/pip/npm 源经 ARG 注入（`.env`）：`APT_MIRROR=mirrors.cloud.tencent.com`、`PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple`、`NPM_REGISTRY=https://registry.npmmirror.com`。`Dockerfile` / `Dockerfile.frontend.http` 已支持 `BASE_IMAGE` / `NODE_IMAGE` / `NGINX_IMAGE` / `APT_MIRROR` / `PIP_INDEX_URL` / `NPM_REGISTRY`，默认值等价官方地址。
  踩坑：ARG 在 `FROM` 前声明是全局，仅可用于 FROM 行；stage 内的 RUN 要用必须在 stage 内再 `ARG` 一次。
- 容器：`party-agent-postgres` / `party-agent-redis` / `party-agent-app` / `party-agent-frontend` 全部运行中；迁移到 head `022_member_vote_dedup_batch`；外网 `http://129.204.32.148` 首页 200。
- `/api/v1/health/ready` **已返回 200**。百炼 Key 已配置，`cloud-llm` / `cloud-embedding` / `cloud-reranker` 三个模型注册并实际调用校验通过（health 全 true）；database / redis / schema / encryption / audit_storage 均 healthy。更换 Key：
  ```bash
  cd /opt/dangjian-agent && sed -i 's|^DASHSCOPE_API_KEY=.*|DASHSCOPE_API_KEY=sk-你的Key|' .env \
    && docker compose -f docker-compose.server.yml up -d app
  ```
- **排障别踩的坑**：`docker compose exec app python` 起的是**新进程**，不会执行 FastAPI lifespan，因此直接调 `_readiness_details()` 会误报 `redis=unhealthy` 与 `models=missing`。判断是否真的有问题，一律以接口为准：`curl http://127.0.0.1/api/v1/health/ready`。
- 常用运维：
  ```bash
  cd /opt/dangjian-agent
  docker compose -f docker-compose.server.yml ps            # 状态
  docker compose -f docker-compose.server.yml logs -f app   # 日志
  docker stats --no-stream                                  # 资源
  docker compose -f docker-compose.server.yml down          # 停止（保留数据卷）
  ```

## 2026-10-21 增量上线：问答附件 + 扫描件/图片 OCR

- 变更范围：`app/api/v1/qa.py`（新增 `POST /qa/attachments`、`attachment_ids`）、
  `app/services/qa_attachment_service.py`、`app/services/ocr_service.py`、
  `app/llm/providers/qwen_vision.py`、`app/chains/qa_chain.py`（仅材料作答）、
  `app/rag/rag_service.py`（材料块）、`app/models/qa_session.py` + 迁移 `023`、前端 `AskView.vue`。
- 上线步骤（已执行）：
  ```bash
  cd /opt/dangjian-agent
  tar czf /root/backups/code_$(date +%F_%H%M).tar.gz app frontend/src migrations
  docker exec party-agent-postgres pg_dump -U party_user -d party_agent -Fc > /root/backups/pg_$(date +%F_%H%M).dump
  # 传代码 → 重建镜像
  docker compose -f docker-compose.server.yml up -d --build app
  docker compose -f docker-compose.server.yml up -d --build frontend
  docker compose -f docker-compose.server.yml exec -T app python -m alembic upgrade head   # 022 → 023
  curl http://127.0.0.1/api/v1/health/ready
  ```
- **坑**：本目录下有多份 compose（`docker-compose.yml` 是生产模板，需要 TLS/密钥等一堆变量），
  `docker compose exec` 不带 `-f` 会读默认那份并报一堆 `required variable ... is missing`。
  所有运维命令都要写全 `-f docker-compose.server.yml`。
- 新增配置（可选）：`OCR_MODEL`（默认 `qwen-vl-ocr`，留空则关闭图片与扫描件）、`OCR_MAX_PAGES`（默认 5）。
  未显式配置时按默认值生效，本次无需改 `.env`。
- 验证：`/api/v1/qa/attachments` 无 token 返回 401（路由存在）；容器内实测 OCR
  （`store_attachment(..., cloud_ocr=True)`）识别中文条款正确；`qa_sessions.attachments` 列已存在。

## 2026-10-25 整体切换到 2.0.1 monorepo（目录结构变更）

**背景**：本地仓库在 2.0.0 起改为 monorepo（后端搬入 `backend/`，旧 Vue 前端降级到 `backend/frontend/`，
顶层 `frontend/` 换成 React 19 + Vite）。服务器上仍是旧布局（根目录 `app/`、`migrations/`、`frontend/`(Vue)），
**服务器没有 git**，无法 `git pull`，因此本次改为整包上传切换。

关键前提：**compose 的 `name: party-agent-server` 与数据卷名未变**（`postgres_data` / `redis_data` /
`originals` / `audit_spool`），所以数据全部保留；迁移从 `026` 顺利升到 `031`。

### 上线步骤（已执行，可复用）

```bash
# 0) 本机：先验证（构建 + 契约测试），产物不入服务器镜像
cd frontend && npx vite build                     # 19s，产出 frontend/dist
node --test tests/*.test.mjs                      # 86/86 通过

# 1) 打包（排除 node_modules/dist/tmp/__pycache__/*.audit，约 10.8MB）
tar czf tmp/deploy-<日期>.tar.gz \
  --exclude='backend/frontend' --exclude='backend/frontend-test' --exclude='backend/tmp' \
  --exclude='backend/audit-spool' --exclude='__pycache__' --exclude='*.pyc' --exclude='*.audit' \
  --exclude='frontend/node_modules' --exclude='frontend/dist' --exclude='frontend/tmp' \
  backend frontend package.json package-lock.json scripts

# 2) 服务器备份
docker exec party-agent-postgres pg_dump -U party_user -d party_agent -Fc > /root/backups/pg_<ts>_pre_v2.dump
tar czf /root/backups/code_<ts>_pre_v2.tar.gz app config deploy migrations scripts ... .env

# 3) 上传 + 解包（先在旁路目录，别直接覆盖线上）
scp tmp/deploy-<日期>.tar.gz root@129.204.32.148:/root/
mkdir -p /opt/dangjian-agent-new && tar xzf /root/deploy-<日期>.tar.gz -C /opt/dangjian-agent-new

# 4) ⚠️ 必做：用服务器原 .env 覆盖包里带来的本地开发 .env
cp /opt/dangjian-agent/.env /opt/dangjian-agent-new/backend/.env
#   （本地 .env 的 POSTGRES_PASSWORD 与线上已有数据卷里的库口令不一致，覆盖即失联）

# 5) 回滚保险：给旧镜像打标签
docker tag party-agent-server-app:latest      party-agent-app-bak-<日期>
docker tag party-agent-server-frontend:latest party-agent-frontend-bak-<日期>

# 6) 构建（不停止旧容器，零停机）
cd /opt/dangjian-agent-new/backend && docker compose -f docker-compose.server.yml build

# 7) 切换 + 迁移 + 验证
docker compose -f docker-compose.server.yml up -d
docker compose -f docker-compose.server.yml exec -T app python -m alembic upgrade head   # 026 → 031
curl http://127.0.0.1/api/v1/health/ready                                                # → 200 {"status":"ready"}

# 8) 目录规范化：新布局上位，旧代码留作回滚
mv /opt/dangjian-agent      /opt/dangjian-agent-old-<日期>
mv /opt/dangjian-agent-new  /opt/dangjian-agent
cd /opt/dangjian-agent/backend && docker compose -f docker-compose.server.yml up -d
```

### 结论与注意

- **compose 文件位置变了**：所有运维命令现在是
  `cd /opt/dangjian-agent/backend && docker compose -f docker-compose.server.yml <子命令>`。
  在 `/opt/dangjian-agent` 根目录直接跑 `-f docker-compose.server.yml` 会找不到文件。
  前端构建上下文是 `../frontend`（相对 compose 文件），两个目录必须同级存在。
- 前端镜像改为**容器内构建**（`frontend/Dockerfile`：node:24-alpine 构建 + nginx:1.28-alpine 托管），
  nginx 配置在 `frontend/deploy/nginx-http.conf`，不再用旧的 `Dockerfile.frontend.http`。
  服务器 3.6G 内存构建无 OOM（本次约 95 秒）。
- 新版 `.env` 无新增必填项：对比 `backend/.env.example`，服务器原有 21 个键足够，缺的都是有默认值的可选项。
- 验证结果：`/health/live` 200、`/health/ready` 200；`school_admin` / `admin` 登录 200 且拿到令牌；
  `/auth/me`、`/admin/org-units`、`/member-full/stats`、`/member-full/batches`、`/education/offerings` 均 200；
  SPA 深链 `/governance` 200；7 张新表全部建好；数据完好（8 用户 / 4 租户 / 6 档案 / 7909 审计）。
- 回滚路径：旧代码在 `/opt/dangjian-agent-old-<日期>`，旧镜像标签 `party-agent-app-bak-<日期>` /
  `party-agent-frontend-bak-<日期>`，数据库备份 `/root/backups/pg_<ts>_pre_v2.dump`。

---

## 2026-10-25（二）全库清空重建 + 重灌演示数据

需求：清掉服务器全部数据并从零重填一套完整演示数据。

### 步骤（顺序不能乱）

1. **全量备份**

   ```bash
   TS=$(date +%F_%H%M)
   docker exec party-agent-postgres pg_dump -U party_user -d party_agent -Fc \
     > /root/backups/pg_${TS}_pre_wipe_full.dump
   ```

2. **停业务容器并清库**（不动 postgres/redis 容器，数据卷保留）

   ```bash
   cd /opt/dangjian-agent/backend
   docker compose -f docker-compose.server.yml stop app frontend
   docker exec party-agent-postgres psql -U party_user -d party_agent -c \
     'DROP SCHEMA public CASCADE; CREATE SCHEMA public;
      GRANT ALL ON SCHEMA public TO party_user; GRANT ALL ON SCHEMA public TO public;'
   ```

3. **从零跑全部迁移**

   ```bash
   docker compose -f docker-compose.server.yml run --rm app python -m alembic upgrade head
   ```

4. **启容器 → 建平台管理员 → 建学校租户与账号 → 灌名册 → 灌业务**

   ```bash
   docker compose -f docker-compose.server.yml up -d app frontend
   docker compose -f docker-compose.server.yml exec -T app \
     python scripts/server_init_admin.py --username admin --password '<口令>'
   docker compose -f docker-compose.server.yml exec -T app \
     python scripts/seed_demo_school.py --admin-password '<口令>' --base-url http://127.0.0.1:8000/api/v1
   ```

   开户第二个学校管理员（审核流程要求「录入人不能自审」，脚本里 `school_admin2` 是审核人）：

   ```bash
   POST /api/v1/admin/users?tenant_id=<学校租户ID>
   {"username":"school_admin2","name":"周敏","password":"<口令>",
    "role":"school_admin","org_unit_id":"<学校党委 org id>"}
   ```

5. **知识库 → 业务 → 学习收尾 → 名册**（知识库必须先灌，学习计划要引用有效资料）

   ```bash
   python scripts/seed_knowledge_docs.py  --username school_admin --password '<口令>' --base-url http://127.0.0.1:8000/api/v1
   python scripts/seed_demo_business.py   --base-url ... --tenant <租户> --school-org <党委> --dept-org <院系>
   python scripts/seed_demo_study_finish.py --base-url ... --school-org <党委> --tenant <租户>
   python scripts/seed_member_profiles.py --tenant <租户> --org-unit-id <支部>
   ```

### 踩坑与修复

- **三个种子脚本硬编码了旧租户/组织 UUID**（`d5584666…`、`c24117e8…`），重建后 ID 全变，脚本必然失败。
  已改为命令行参数：`--tenant` / `--school-org` / `--dept-org`，重建时传入新 ID 即可复用。
- **`seed_demo_study_finish.py` 的 `expected_revision` 写死为 1/2**，重跑时 409。
  已改为每次写操作前重新读取当前 revision。
- **`seed_demo_business.py` 调用了不存在的 `GET /assessment/tasks`**（405），
  导致任务审核整段被跳过 → 归集判定「来源记录含未审核内容」，最终审核必然 409。
  已改为直接审核 `POST /assessment/tasks` 返回的 id；并对归集审核加了「有缺项就跳过并告警」的保护。
- 考核模块**没有任务列表接口**，只有 `GET /assessment/workspace?org_unit_id=&year=`
  （缺参数返回 422，不是故障）。审核路由是 `POST /assessment/{tasks|evidence|runs|plans}/{id}/review`，
  请求体字段是 `status`（不是 `decision`）。
- `AssessmentTask` / `AssessmentRun` 的状态列叫 `review_status`，没有 `status` 列。

### 重建后数据核对（本次结果）

| 表 | 行数 |
|---|---|
| users | 8（8 类角色各一，其中 2 个 school_admin）|
| tenants | 2（平台 + 湖南科技职业技术学院）|
| org_units | 6（1 school / 2 department / 3 branch）|
| member_profiles | 6 |
| knowledge_docs | 7（embedding_chunks 40）|
| study_plans | 1（已审核）+ 3 items |
| assessment_indicators / tasks / runs | 1 / 1（approved）/ 2（1 approved + 1 草稿）|
| audit_logs | 518 |

8 个账号全部登录 200；`/health/live`、`/health/ready` 200；公网首页 200。
