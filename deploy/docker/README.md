# Docker 部署与运维指南

更新日期：2026-10-11，依据当前 Compose 与 Dockerfile。命令从项目根目录执行；本次文档更新未执行部署。

## 文件与配置

实际文件为根目录 `docker-compose.yml`、`docker-compose.dev.yml`、`Dockerfile`、`Dockerfile.dev`、`scripts/init_db.sql`，以及本目录[镜像源指南](MIRROR_GUIDE.md)和 `daemon.json.example`。当前没有 `nginx.conf`、`init-db.sh` 或 Kubernetes 配置。

使用 Docker Compose v2。仅在没有 `.env` 时复制[环境示例](../../.env.example)，保留已有配置。填写 `DASHSCOPE_API_KEY` 和 `SECRET_KEY`；生产还须设置 `POSTGRES_PASSWORD`、`REDIS_PASSWORD` 与明确的 `ALLOWED_HOSTS` 来源列表。`QWEN_API_KEY` 是兼容别名。

环境示例的聊天模型为 `deepseek-v3`，Compose 未设置 `CHAT_MODEL` 时回退到 `qwen3.8-flash`；向量/重排示例为 `qwen3.7-text-embedding-flash` / `qwen3.7-text-rerank`，维度为 1024。内部资料出网须获准的精确主机白名单，敏感与涉密不会因此放行。型号可用性需实际调用核验。

Compose 显式覆盖应用的数据库和 Redis 连接，容器使用 `postgres` / `redis` 主机名；宿主机应用使用[运行指南](../../docs/RUNNING.md)的本机连接。

## 开发环境

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec app python -m alembic upgrade head
docker compose -f docker-compose.dev.yml exec app python -m alembic current
docker compose -f docker-compose.dev.yml ps
```

应用热重载并挂载源码、测试、迁移、配置和脚本。数据库为 `party_agent_dev`，用户名 `party_user`、密码 `dev_password`；Redis 未设密码。pgAdmin 和 Redis Commander 是开发工具，不能直接用于公网。`/docs`、`/redoc` 仅在 `DEBUG=true` 时启用，开发 Compose 未显式设置 DEBUG，需另行配置。

## 生产环境

在已确认的目标环境配置密钥、来源及网络访问后执行：

```bash
docker compose build app
docker compose up -d postgres redis
docker compose run --rm app python -m alembic upgrade head
docker compose up -d app
docker compose exec app python -m alembic current
docker compose ps
```

应用以非 root `appuser` 运行，`ENV=production` 强制关闭 DEBUG。迁移不自动执行，当前唯一头为 `012_member_self`。[迁移指南](../../migrations/README.md)说明旧库接管；`init_db.sql` 只在空数据卷首次启动时运行，不能替代 Alembic。

正式前端执行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build`，托管 `frontend/dist/`，配置 SPA 路由回退及 `/api` 到后端 `/api/v1` 的代理。Dockerfile 只打包后端，Compose 没有前端、HTTPS 或反向代理服务。

## 服务与端口

| 服务 | 开发宿主端口 | 生产宿主端口 | 容器端口 |
| --- | --- | --- | --- |
| FastAPI | 8000 | 8000 | 8000 |
| PostgreSQL | `127.0.0.1:55432` | 5432 | 5432 |
| Redis | `127.0.0.1:56379` | 6379 | 6379 |
| pgAdmin | 5050 | 无 | 80 |
| Redis Commander | 8081 | 无 | 8081 |

只有开发数据库/Redis 宿主端口支持 `POSTGRES_PORT` / `REDIS_PORT`；应用没有 `APP_PORT` 配置。生产数据库和 Redis 目前仍发布宿主端口，正式部署需修改编排或通过适当网络控制收紧访问。

## 就绪与排障

```bash
curl http://127.0.0.1:8000/api/v1/health/live
curl http://127.0.0.1:8000/api/v1/health/ready
docker compose logs --tail=100 app
docker compose exec postgres pg_isready -U party_user -d party_agent
docker compose exec redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping'
```

开发 Docker 命令加 `-f docker-compose.dev.yml`，数据库名改为 `party_agent_dev`，Redis 使用 `redis-cli ping`。

`ready` 检查 Redis、数据库、六张核心表/全文检索和模型注册，不检查完整迁移链、学习/考核表或实际云调用。200 不能代替 `alembic current`、真实模型和业务验收。认证存储故障时不能绕过 Redis 登录。

云端接入不需要 `/models` 挂载。排障只检查必要项，避免输出完整环境变量中的密码、令牌和 API Key。镜像拉取问题见[镜像源指南](MIRROR_GUIDE.md)。

## 备份与升级

下面使用 Bash 重定向；恢复会写入数据库，执行前须确认目标、备份及维护窗口：

```bash
docker compose exec -T postgres pg_dump -U party_user -d party_agent > backup.sql
# 在已确认的恢复窗口执行
docker compose exec -T postgres psql -U party_user -d party_agent < backup.sql
```

同时记录部署代码和迁移版本。备份加密、位置、保留期及 Redis 恢复以实际运维方案为准。Redis 已启用 AOF，仓库没有已验证的自动备份恢复脚本。

升级先备份并核对兼容性，再构建、在维护窗口迁移、重启和核对核心业务。回滚须匹配代码和数据库结构，不能只切回代码就假定兼容。

```bash
docker compose logs -f app
docker stats
docker compose down
```

`down` 保留命名数据卷，`down -v` 会删除数据库/Redis 等数据，只能用于明确确认可丢弃的数据。`scripts/init_db.py` 会删表，不可用于升级。当前固定容器名和宿主端口不能直接 `--scale app=3`，多副本及后台提醒扫描协调需另行设计。

## 验证边界

本次仅核对文档与代码/配置，没有构建生产镜像、启动容器、迁移业务库或验证恢复。历史证据见[测试指南](../../docs/TESTING.md)，真实学校验收见[项目状态](../../docs/STATUS.md)。
