#!/usr/bin/env bash
# 党建工作智能体 - 服务器端部署脚本（Ubuntu / 2核2G 单机简化版）
#
# 前置：
#   - 本脚本在服务器 /root/dangjian-agent 或上传解压后的项目目录内执行
#   - 已配置 deploy/server/env.example -> .env 的实际值（含 DASHSCOPE_API_KEY）
#
# 步骤：安装 Docker -> 检查 .env -> 构建 -> 启动 -> 迁移 -> 就绪检查
set -euo pipefail

cd "$(dirname "$0")/../.."
echo "项目目录：$(pwd)"

# ---------- 1. 安装 Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "[1/6] 安装 Docker Engine 与 Compose 插件..."
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else
  echo "[1/6] Docker 已安装：$(docker --version)"
fi

# ---------- 2. 检查 .env ----------
echo "[2/6] 检查 .env ..."
if [ ! -f .env ]; then
  echo "缺少 .env！请执行：cp deploy/server/env.example .env 并填写实际值（SECRET_KEY / POSTGRES_PASSWORD / DASHSCOPE_API_KEY / ALLOWED_HOSTS）。"
  exit 1
fi
grep -q 'SECRET_KEY=please_change' .env && { echo "错误：SECRET_KEY 仍是示例值，请修改 .env"; exit 1; }
grep -q 'POSTGRES_PASSWORD=please_change' .env && { echo "错误：POSTGRES_PASSWORD 仍是示例值，请修改 .env"; exit 1; }
echo "    .env 检查通过"

# ---------- 3. 构建镜像 ----------
echo "[3/6] 构建镜像（国内网络慢可用 DOCKERHUB_MIRROR 或重试）..."
set -x
docker compose -f docker-compose.server.yml build
set +x

# ---------- 4. 启动数据库与 Redis ----------
echo "[4/6] 启动基础设施..."
docker compose -f docker-compose.server.yml up -d postgres redis
for i in $(seq 1 30); do
  if docker compose -f docker-compose.server.yml ps postgres redis | grep -q "healthy"; then
    echo "    postgres/redis 健康"
    break
  fi
  sleep 2
done

# ---------- 5. 执行数据库迁移 ----------
echo "[5/6] 执行 Alembic 迁移..."
docker compose -f docker-compose.server.yml run --rm app python -m alembic upgrade head

# ---------- 6. 启动应用与前端 ----------
echo "[6/6] 启动应用与前端..."
docker compose -f docker-compose.server.yml up -d app frontend

echo ""
echo "部署完成！验证："
echo "  curl http://127.0.0.1/api/v1/health/live"
echo "  curl http://127.0.0.1/api/v1/health/ready"
echo "  浏览器访问 http://<服务器公网IP>"
echo "  内存：docker stats --no-stream"
echo ""
echo "首次使用：在项目内 python scripts/create_test_user.py ... （见 docs/RUNNING.md）"