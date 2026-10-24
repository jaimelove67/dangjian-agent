# Docker镜像与网络排障

更新日期：2026-10-11，依据项目当前Compose、Dockerfile及辅助脚本。本次没有联网探测镜像源，不声明第三方源当前可用。

## 当前项目镜像

两套Compose使用Docker Hub的pgvector PostgreSQL、Redis，以及开发工具pgAdmin、Redis Commander。基础镜像为 `python:3.11-slim`。当前Compose没有本地Embedding容器，也不引用 `ghcr.io/huggingface/text-embeddings-inference`；向量化与重排接入云端。

`DOCKERHUB_MIRROR` 会修改Compose中的镜像仓库前缀及构建的BASE_IMAGE，因此最终请求/镜像名也随前缀变化。环境示例默认为 `docker.io`。`GHCR_MIRROR` 在环境示例中保留，但当前Compose未使用它。

## 排查顺序

先查看实际失败的registry、镜像名和响应。HTML响应表示请求没有取得预期manifest，应检查镜像代理、登录跳转或网关错误页；不能仅凭报错就断定某个供应商故障。

从项目根目录执行以下检查（涉及网络请求，执行前按当前环境规则确认）：

```bash
bash scripts/check-docker-mirrors.sh
# 或只检查已批准的目标
bash scripts/check-docker-mirrors.sh https://your-approved-registry.example
```

脚本只探测 `/v2/` 状态和Content-Type，是初筛，不保证目标仓库、标签或实际拉取可用。通过初筛后再核对实际镜像拉取和构建；不要把“返回JSON”当作整套部署已验证。

Docker daemon配置模板位于 `deploy/docker/daemon.json.example`。合并需要的配置并备份已有文件，不直接覆盖其他运行项目的设置。重启Docker会影响已有容器，应在已确认的维护窗口执行。候选公共源的可用性取决于网络和时间，模板不是已验证清单。

## 临时覆盖基础镜像

```bash
docker build --build-arg BASE_IMAGE=your-approved-registry.example/library/python:3.11-slim .
```

Compose使用 `.env` 中的 `DOCKERHUB_MIRROR` 覆盖。使用私有仓库时核对项目路径、镜像标签和授权；不要把凭据写入仓库前缀或提交到文档。

## 离线分发的现有边界

```bash
bash scripts/offline-images.sh save --mirror docker.io
bash scripts/offline-images.sh load --bundle /path/to/party-agent-images.tar
```

脚本当前仍包含旧GHCR Embedding镜像，`save` 会尝试拉取它，失败时中止打包；这不是当前应用依赖。脚本也没有打包已构建的应用镜像或Python安装依赖，导入基础镜像不能直接保证全离线构建。若要用于正式离线交付，应先把打包清单和构建策略对齐实际环境，再验证目标机。本文只说明限制，没有修改脚本或执行拉取。

导入标签与Compose仓库前缀必须一致。脚本将Docker Hub镜像重标为标准标签，使用自定义前缀时应另外核对本地标签。完整启动、迁移与生产边界见[Docker指南](README.md)。
