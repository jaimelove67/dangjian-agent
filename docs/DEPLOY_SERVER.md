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
