#!/usr/bin/env bash
# 党建工作智能体 - 服务器端一键部署脚本（root 执行）
# 支持：Ubuntu/Debian（apt）与 OpenCloudOS/CentOS 系（dnf，如腾讯云轻量 OpenCloudOS 9）
#
# 用法（腾讯云 WebShell 或 SSH root 下粘贴执行）：
#   bash deploy/server/bootstrap.sh
#
# 或者不 clone 直接跑（仓库已有脚本时）：
#   curl -fsSL https://raw.githubusercontent.com/jaimelove67/dangjian-agent/master/deploy/server/bootstrap.sh | bash
#
# 做四件事：装 Docker -> 拉代码 -> 生成 .env -> 构建/迁移/启动 -> 健康检查
set -euo pipefail

REPO="${REPO:-https://github.com/jaimelove67/dangjian-agent.git}"
BRANCH="${BRANCH:-master}"
DIR="${DIR:-/opt/dangjian-agent}"
PUBLIC_IP="${PUBLIC_IP:-}"

log() { echo ""; echo "==== $* ===="; }

# ---------- 0. 环境检查 ----------
log "0/7 环境检查"
[ "$(id -u)" = "0" ] || { echo "请用 root 执行（sudo -i 后重试）"; exit 1; }
. /etc/os-release
echo "系统：$PRETTY_NAME"
echo "CPU ：$(nproc) 核"
echo "内存：$(free -h | awk '/^Mem:/{print $2}')"
echo "磁盘：$(df -h / | awk 'NR==2{print $4}') 可用"

# 探测公网 IP（腾讯云元数据服务，失败则留空由用户手填）
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP=$(curl -fsS --max-time 3 http://metadata.tencentyun.com/latest/meta-data/public-ipv4 2>/dev/null || true)
fi
[ -n "$PUBLIC_IP" ] || PUBLIC_IP=$(curl -fsS --max-time 3 ifconfig.me 2>/dev/null || true)
echo "公网 IP：$PUBLIC_IP"

# 内存小于 3G 时加 2G swap，避免前端构建 OOM
if [ "$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)" -lt 3000 ] && ! swapon --show | grep -q 'swapfile'; then
  log "0.1/7 内存偏小，创建 2G swap"
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "swap 已启用：$(swapon --show | tail -1)"
fi

# ---------- 1. 安装 Docker（支持 Ubuntu/Debian 与 OpenCloudOS/CentOS 系） ----------
log "1/7 安装 Docker"
PKG=""
case "${ID:-}" in
  ubuntu|debian) PKG="apt" ;;
  opencloudos|centos|rhel|rocky|almalinux|tencentos) PKG="dnf" ;;
  *) command -v dnf >/dev/null 2>&1 && PKG="dnf" || PKG="apt" ;;
esac
echo "包管理：$PKG"

if ! command -v docker >/dev/null 2>&1; then
  if [ "$PKG" = "dnf" ]; then
    # 腾讯云内网镜像源（轻量服务器访问 mirrors.cloud.tencent.com 快）
    dnf install -y -q dnf-plugins-core
    dnf config-manager --add-repo https://mirrors.cloud.tencent.com/docker-ce/linux/centos/docker-ce.repo
    dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg git
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME:-$(. /etc/os-release && echo "$VERSION_CODENAME")} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  systemctl enable --now docker
  echo "Docker 安装完成：$(docker --version)"
else
  echo "Docker 已安装：$(docker --version)"
fi
docker compose version || { echo "缺少 docker compose 插件"; exit 1; }

# ---------- 2. 获取代码 ----------
log "2/7 获取代码到 $DIR"
if [ -d "$DIR/.git" ]; then
  cd "$DIR" && git fetch --all --quiet && git checkout "$BRANCH" --quiet && git pull --ff-only --quiet
  echo "已更新到：$(git rev-parse --short HEAD)"
else
  git clone --branch "$BRANCH" "$REPO" "$DIR"
  cd "$DIR"
  echo "已克隆到：$(git rev-parse --short HEAD)"
fi

# ---------- 3. 生成 .env ----------
log "3/7 生成 .env"
cd "$DIR"
if [ ! -f .env ]; then
  SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  PG_PASS=$(openssl rand -hex 12 2>/dev/null || head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 24)
  cat > .env <<EOF
# 由 deploy/server/bootstrap.sh 自动生成于 $(date -Is)
# 公网 IP：$PUBLIC_IP
ENV=development
DEBUG=false
LOG_LEVEL=INFO
LOG_FORMAT=json

SECRET_KEY=${SECRET_KEY}
ALLOWED_HOSTS=["${PUBLIC_IP}", "localhost", "127.0.0.1"]

POSTGRES_DB=party_agent
POSTGRES_USER=party_user
POSTGRES_PASSWORD=${PG_PASS}

# 百炼 API Key：留空时系统可启动，但智能问答/向量化不可用。
# 拿到 Key 后执行：sed -i 's|^DASHSCOPE_API_KEY=.*|DASHSCOPE_API_KEY=sk-xxx|' .env && docker compose -f docker-compose.server.yml up -d app
DASHSCOPE_API_KEY=
CHAT_MODEL=qwen3.8-flash
EMBED_MODEL=qwen3.7-text-embedding-flash
RERANK_MODEL=qwen3.7-text-rerank
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com
ALLOWED_EXTERNAL_MODELS=["dashscope.aliyuncs.com"]
ALLOWED_LOCAL_MODEL_HOSTS=[]

JOB_WORKER_ENABLED=false

# 国内拉取 Docker Hub 慢时改成可用加速源，见 deploy/docker/MIRROR_GUIDE.md
DOCKERHUB_MIRROR=docker.io
EOF
  chmod 600 .env
  echo ".env 已生成（SECRET_KEY / POSTGRES_PASSWORD 为随机值，已保存，勿泄露）"
else
  echo ".env 已存在，保持不变"
fi

# ---------- 4. 构建镜像 ----------
log "4/7 构建镜像（首次约 5-15 分钟）"
docker compose -f docker-compose.server.yml build

# ---------- 5. 启动数据库与 Redis ----------
log "5/7 启动 PostgreSQL / Redis"
docker compose -f docker-compose.server.yml up -d postgres redis
for i in $(seq 1 40); do
  if docker compose -f docker-compose.server.yml ps --format json postgres redis 2>/dev/null | grep -q '"healthy"'; then
    echo "postgres/redis 已健康"; break
  fi
  sleep 3
done
docker compose -f docker-compose.server.yml ps postgres redis

# ---------- 6. 数据库迁移 ----------
log "6/7 执行 Alembic 迁移"
docker compose -f docker-compose.server.yml run --rm app python -m alembic upgrade head
docker compose -f docker-compose.server.yml run --rm app python -m alembic current

# ---------- 7. 启动应用与前端 ----------
log "7/7 启动应用与前端"
docker compose -f docker-compose.server.yml up -d app frontend
sleep 8

echo ""
echo "================= 部署结果 ================="
docker compose -f docker-compose.server.yml ps
echo ""
echo "-- 本机健康检查 --"
curl -fsS --max-time 10 http://127.0.0.1/api/v1/health/live && echo "  <- live OK" || echo "live 未通过"
curl -fsS --max-time 15 http://127.0.0.1/api/v1/health/ready && echo "" && echo "  <- ready OK" || echo "ready 未通过（看日志：docker compose -f docker-compose.server.yml logs --tail=100 app）"
echo ""
echo "浏览器访问：http://${PUBLIC_IP}"
echo "若打不开：腾讯云控制台 -> 安全组 -> 放行 TCP 80"
echo "日志：cd $DIR && docker compose -f docker-compose.server.yml logs -f app"
