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
