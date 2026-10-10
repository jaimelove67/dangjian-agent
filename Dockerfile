# 党建工作智能体 - 生产环境 Dockerfile
#
# 基础镜像默认使用官方 Docker Hub 镜像，可直接构建。
# 网络受限时不必改代码，通过 build arg 指定加速源即可：
#   docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim .
# 或使用 compose 变量：在 .env 中设置 DOCKERHUB_MIRROR=docker.m.daocloud.io
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY ./app ./app
COPY ./migrations ./migrations
COPY ./config ./config
COPY ./scripts ./scripts
COPY alembic.ini ./alembic.ini

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health/ready || exit 1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
