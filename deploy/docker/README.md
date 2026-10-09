# Docker 部署指南

## 目录结构

```
deploy/
├── docker/
│   ├── README.md                    # 本文档
│   ├── init-db.sh                   # 数据库初始化脚本
│   └── nginx.conf                   # Nginx 配置（生产环境）
└── kubernetes/                      # K8s 配置（可选）
```

## 快速开始

### 1. 开发环境

**启动所有服务：**

```bash
# 复制环境变量文件
cp .env.example .env

# 编辑 .env，填入必要的配置（至少填写 QWEN_API_KEY）
vim .env

# 启动开发环境（包含热重载、pgAdmin、Redis Commander）
docker-compose -f docker-compose.dev.yml up -d

# 查看日志
docker-compose -f docker-compose.dev.yml logs -f app
```

**访问地址：**

- 应用 API: http://localhost:8000
- API 文档: http://localhost:8000/docs
- pgAdmin: http://localhost:5050 (admin@party-agent.local / admin)
- Redis Commander: http://localhost:8081

**停止服务：**

```bash
docker-compose -f docker-compose.dev.yml down
```

**清理数据（重置数据库）：**

```bash
docker-compose -f docker-compose.dev.yml down -v
```

### 2. 生产环境

**启动服务：**

```bash
# 确保 .env 已配置生产环境参数
# 特别注意：修改 SECRET_KEY、POSTGRES_PASSWORD、REDIS_PASSWORD

# 启动生产环境
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

**数据库迁移：**

```bash
# 进入应用容器
docker exec -it party-agent-app bash

# 执行数据库迁移
alembic upgrade head

# 退出容器
exit
```

**停止服务：**

```bash
docker-compose down
```

## 常用命令

### 查看日志

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f app
docker-compose logs -f postgres
docker-compose logs -f redis
```

### 进入容器

```bash
# 进入应用容器
docker exec -it party-agent-app bash

# 进入数据库容器
docker exec -it party-agent-postgres psql -U party_user -d party_agent
```

### 数据库操作

```bash
# 备份数据库
docker exec party-agent-postgres pg_dump -U party_user party_agent > backup_$(date +%Y%m%d_%H%M%S).sql

# 恢复数据库
docker exec -i party-agent-postgres psql -U party_user party_agent < backup.sql

# 查看数据库大小
docker exec party-agent-postgres psql -U party_user -d party_agent -c "SELECT pg_size_pretty(pg_database_size('party_agent'));"
```

### 清理和重建

```bash
# 清理未使用的 Docker 资源
docker system prune -a

# 重建镜像（代码更新后）
docker-compose build --no-cache

# 重建并启动
docker-compose up -d --build
```

## 性能优化

### 1. 数据库连接池

在 `app/db/session.py` 中配置：

```python
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=20,          # 连接池大小
    max_overflow=10,       # 最大溢出连接数
    pool_pre_ping=True,    # 连接健康检查
    pool_recycle=3600,     # 连接回收时间（秒）
)
```

### 2. Redis 持久化

生产环境建议使用 AOF 持久化：

```yaml
# docker-compose.yml
redis:
  command: redis-server --appendonly yes --appendfsync everysec
```

### 3. 应用多副本

生产环境可以启动多个应用实例：

```bash
docker-compose up -d --scale app=3
```

需要配合 Nginx 做负载均衡（见下文）。

## 监控和健康检查

### 查看容器健康状态

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### 手动健康检查

```bash
# 应用健康检查
curl http://localhost:8000/health

# 数据库健康检查
docker exec party-agent-postgres pg_isready -U party_user -d party_agent

# Redis 健康检查
docker exec party-agent-redis redis-cli ping
```

### 查看资源使用

```bash
# 查看所有容器资源使用情况
docker stats

# 查看特定容器
docker stats party-agent-app
```

## 故障排查

### 应用无法启动

1. **检查日志：**
   ```bash
   docker-compose logs app
   ```

2. **检查环境变量：**
   ```bash
   docker exec party-agent-app env | grep DATABASE_URL
   ```

3. **检查依赖服务：**
   ```bash
   docker-compose ps
   ```

### 数据库连接失败

1. **检查数据库是否启动：**
   ```bash
   docker-compose ps postgres
   ```

2. **检查数据库日志：**
   ```bash
   docker-compose logs postgres
   ```

3. **测试数据库连接：**
   ```bash
   docker exec party-agent-app python -c "from app.db.session import engine; print('OK')"
   ```

### Redis 连接失败

1. **检查 Redis 是否启动：**
   ```bash
   docker-compose ps redis
   ```

2. **测试 Redis 连接：**
   ```bash
   docker exec party-agent-redis redis-cli ping
   ```

### 模型加载失败

1. **检查模型路径：**
   ```bash
   docker exec party-agent-app ls -lh /models
   ```

2. **检查环境变量：**
   ```bash
   docker exec party-agent-app env | grep MODEL
   ```

## 生产环境部署建议

### 1. 使用 Nginx 反向代理

**nginx.conf 示例：**

```nginx
upstream party_agent_backend {
    server app:8000;
    # 多实例负载均衡
    # server app2:8000;
    # server app3:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    # 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL 证书
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # 客户端请求体大小限制（上传文件）
    client_max_body_size 50M;

    # 代理到后端
    location / {
        proxy_pass http://party_agent_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket 支持（如需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 静态文件（如有）
    location /static/ {
        alias /app/static/;
        expires 30d;
    }
}
```

### 2. 数据备份策略

**自动备份脚本：**

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup"
DATE=$(date +%Y%m%d_%H%M%S)

# 备份数据库
docker exec party-agent-postgres pg_dump -U party_user party_agent | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

# 备份 Redis
docker exec party-agent-redis redis-cli --rdb /data/dump.rdb
docker cp party-agent-redis:/data/dump.rdb "$BACKUP_DIR/redis_$DATE.rdb"

# 删除 7 天前的备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
find $BACKUP_DIR -name "*.rdb" -mtime +7 -delete

echo "Backup completed: $DATE"
```

**设置 cron 定时备份：**

```bash
# 每天凌晨 2 点备份
0 2 * * * /path/to/backup.sh >> /var/log/party-agent-backup.log 2>&1
```

### 3. 日志轮转

**docker-compose.yml 配置：**

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 4. 资源限制

**docker-compose.yml 配置：**

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

## 安全建议

### 1. 修改默认密码

- ✅ 修改 `POSTGRES_PASSWORD`
- ✅ 修改 `REDIS_PASSWORD`
- ✅ 修改 `SECRET_KEY`
- ✅ 修改 pgAdmin 默认密码

### 2. 限制端口暴露

生产环境不要暴露数据库和 Redis 端口到宿主机：

```yaml
services:
  postgres:
    # ports:
    #   - "5432:5432"  # 注释掉，只在容器网络内访问
```

### 3. 使用非 root 用户

Dockerfile 中已配置非 root 用户：

```dockerfile
USER appuser
```

### 4. 扫描镜像漏洞

```bash
# 使用 Trivy 扫描镜像
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image party-agent-app:latest
```

## 升级和回滚

### 升级应用

```bash
# 1. 拉取最新代码
git pull

# 2. 备份数据库
./backup.sh

# 3. 重新构建镜像
docker-compose build

# 4. 停止旧版本
docker-compose down

# 5. 启动新版本
docker-compose up -d

# 6. 执行数据库迁移（如有）
docker exec -it party-agent-app alembic upgrade head

# 7. 验证服务
docker-compose ps
curl http://localhost:8000/health
```

### 回滚

```bash
# 1. 停止当前版本
docker-compose down

# 2. 切换到旧版本代码
git checkout <previous-commit>

# 3. 重新构建并启动
docker-compose build
docker-compose up -d

# 4. 恢复数据库（如需要）
docker exec -i party-agent-postgres psql -U party_user party_agent < backup.sql
```

## 常见问题

### Q: 如何查看应用的环境变量？

```bash
docker exec party-agent-app env
```

### Q: 如何在容器内运行 Python 脚本？

```bash
docker exec -it party-agent-app python scripts/your_script.py
```

### Q: 如何运行测试？

```bash
# 开发环境
docker-compose -f docker-compose.dev.yml exec app pytest

# 带覆盖率
docker-compose -f docker-compose.dev.yml exec app pytest --cov=app
```

### Q: 如何清理所有数据重新开始？

```bash
# 警告：这会删除所有数据！
docker-compose down -v
docker-compose up -d
```

### Q: 容器启动后立即退出？

查看日志找出原因：

```bash
docker-compose logs app
```

常见原因：
- 数据库连接失败
- 环境变量配置错误
- 依赖包缺失

---

**需要帮助？**

- 查看项目文档：`docs/`
- 提交 Issue：[GitHub Issues](your-repo-url/issues)
- 联系团队：your-email@example.com
