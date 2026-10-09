# 部署指南（Docker Compose 版）

> 面向 M1 基础设施验收的部署说明。通用命令与排障详见 [`deploy/docker/README.md`](docker/README.md)。

## 1. 前置条件

- Docker 20.10+ / Docker Compose 2.0+
- （可选）Docker 镜像加速源，受限网络下参 [`deploy/docker/MIRROR_GUIDE.md`](docker/MIRROR_GUIDE.md)

## 2. 开发环境

```bash
cp .env.example .env      # 至少填写 DASHSCOPE_API_KEY；生产务必改 SECRET_KEY / 密码
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec app alembic upgrade head
```

访问：

- API: http://localhost:8000 ，文档: http://localhost:8000/docs
- pgAdmin: http://localhost:5050 ，Redis Commander: http://localhost:8081

## 3. 生产环境

```bash
# 1) 配置 .env（SECRET_KEY / POSTGRES_PASSWORD / REDIS_PASSWORD 必须修改）
# 2) 启动
docker compose up -d
# 3) 迁移
docker compose exec app alembic upgrade head
# 4) 状态
docker compose ps
```

## 4. 数据库迁移（Alembic）

- 迁移脚本位于 `migrations/versions/`，当前 head 为 **002**（001 核心表 + 002 中文全文检索）。
- 首次启动容器时 `scripts/init_db.sql` 会启用扩展：`vector`、`uuid-ossp`、`pg_trgm`，并创建 `chinese_zh` 检索配置。
- 迁移命令（容器内，Linux UTF-8 环境）：

```bash
docker compose exec app alembic upgrade head
docker compose exec app alembic current     # 查看当前版本
```

> 注意：`alembic.ini` 已改为纯 ASCII 注释，以兼容 Windows GBK locale 下的本地执行。

## 5. 服务与端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| app | 8000 | FastAPI；`/api/v1/health`、`/health/ready`、`/health/live` |
| postgres | 5432 | `pgvector/pgvector:pg16` |
| redis | 6379 | 会话与缓存 |
| pgadmin | 5050 | 仅开发环境 |
| redis-commander | 8081 | 仅开发环境 |

端口占用时可通过 `.env` 覆盖：`POSTGRES_PORT` / `REDIS_PORT` / `APP_PORT` 等。

## 6. 部署后自检

```bash
# 健康检查
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/ready     # 检查 DB / Redis

# 数据库表与迁移版本
docker compose exec postgres psql -U party_user -d party_agent -c "\dt"
docker compose exec postgres psql -U party_user -d party_agent -c "select version_num from alembic_version;"
```

## 7. 安全基线（生产）

- 修改 `SECRET_KEY` / `POSTGRES_PASSWORD` / `REDIS_PASSWORD`；JWT 复用 `SECRET_KEY`。
- 数据库、Redis 端口不对外暴露（仅容器网络内访问）。
- 反向代理启用 HTTPS，限制上传体积（`client_max_body_size`）。
- 审计日志只追加：应用层已拦截 UPDATE/DELETE，生产建议再以数据库权限收紧（`GRANT INSERT / REVOKE UPDATE, DELETE`）。
- 备份加密、异地存放，保留期不少于一年（审计要求）。

## 8. 升级与回滚

```bash
# 升级
git pull && docker compose build
docker compose exec app alembic upgrade head
docker compose up -d

# 回滚
docker compose down
git checkout <previous-commit> && docker compose build && docker compose up -d
# 必要时恢复数据库快照
```
