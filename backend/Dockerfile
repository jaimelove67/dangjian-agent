# 运行镜像只安装经哈希锁定的生产依赖；学校登记与模型审批由管理入口完成。
# 基础镜像与 apt/pip 源均经 ARG 注入，默认值等价官方地址（镜像源不进代码）。
ARG BASE_IMAGE=python:3.11-slim-bookworm
ARG APT_MIRROR=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple
FROM ${BASE_IMAGE}
# stage 内重新声明以继承全局 ARG 值（否则 RUN 的 shell 展开为空）
ARG APT_MIRROR
ARG PIP_INDEX_URL
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_INDEX_URL=${PIP_INDEX_URL}
# bookworm 使用 DEB822 格式源文件 /etc/apt/sources.list.d/debian.sources
RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --require-hashes --no-cache-dir -r requirements.lock
COPY app ./app
COPY migrations ./migrations
COPY config ./config
COPY scripts ./scripts
COPY alembic.ini ./
RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /app/uploads /app/audit-spool \
    && chown -R appuser:appuser /app \
    && chmod 700 /app/uploads /app/audit-spool
USER 1000:1000
EXPOSE 8000
# 存活与业务就绪分开；待配置会在 /health/ready 返回503。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/api/v1/health/live || exit 1
ENTRYPOINT ["python", "scripts/module6_entrypoint.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
