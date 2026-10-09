# Docker 镜像源与网络排障指南

> 适用症状：`docker build` / `docker pull` 报
> `unexpected media type text/html`、
> `encountered unknown type text/html; children may not be fetched`，
> 或拉取长时间卡住、构建卡在 `load metadata for docker.io/...`。

---

## 1. 先分清病因

| 报错/现象 | 病因 |
|---|---|
| `unexpected media type text/html` | 请求打到了镜像加速器，对方返回了一张 HTML 网页，根本不是 registry |
| `encountered unknown type text/html` | 同上，只是 buildkit 的措辞不同 |
| `toomanyrequests` / HTTP 429 | 这才是 **Docker Hub 官方匿名拉取限流**，与加速器无关 |
| 长时间无响应后超时 | 加速源不可达（域名解析不到 / 防火墙丢包） |

**关键结论：本项目部署时遇到的 `text/html` 不是限流。** Docker 拉镜像时会请求
`GET /v2/<name>/manifests/<tag>`，期望拿到 JSON 格式的 manifest；如果收到的响应头是
`Content-Type: text/html`，说明这个"加速器"在服务异常时直接把错误页返回给了 Docker。

**为什么配了多个源还是失败？** `registry-mirrors` 是列表，但回退并不可靠：只有当某个源
连接失败或返回 5xx 时才会尝试下一个；一旦某个源返回"HTTP 层成功、内容是 HTML"的响应，
Docker 会直接判死报错，**不会自动切到列表里下一个可用源**。所以一个坏源就能拖垮整次拉取。

---

## 2. 三步定位与修复

### 第 1 步：自检哪些源可用

```bash
bash scripts/check-docker-mirrors.sh
```

脚本会逐个探测候选源的 `/v2/` 端点，并给出判定：

- `可用（真 registry）` —— 返回 JSON，可以用
- `坏源：返回 HTML 网页，不是 registry` —— 就是它导致构建失败，必须移除
- `不可达（连接失败或超时）` —— 网络到不了，同样移除

> 也可以带上自己的源：`bash scripts/check-docker-mirrors.sh https://your-mirror`

### 第 2 步：清理 daemon.json，只留实测可用的源

```bash
# 备份原配置
sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.bak 2>/dev/null || true

# 用模板覆盖（模板默认只保留一个社区源，按第 1 步结果自行增删）
sudo cp deploy/docker/daemon.json.example /etc/docker/daemon.json

# 生效
sudo systemctl daemon-reload
sudo systemctl restart docker

# 确认生效
docker info | grep -A5 "Registry Mirrors"
```

**务必删掉这一条：`https://mirror.ccs.tencentyun.com`**
它是腾讯云容器服务的**内网专用**加速器，只有腾讯云 CVM 内网能访问；换到本机、GitHub
Actions、其他云厂商，请求必然失败，是最隐蔽的坑之一。

### 第 3 步：验证

```bash
docker pull python:3.11-slim
```

能正常拉取即修复完成。若仍然失败，回到第 1 步换源重试，或直接采用第 5 步的离线方案。

---

## 3. 换源不改代码

仓库已经做了两处解耦，**镜像源不进代码，只走环境变量**：

**Dockerfile / Dockerfile.dev** —— 基础镜像用 ARG 暴露：

```dockerfile
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
```

单独构建时临时换源：

```bash
docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim .
```

**docker-compose.yml / docker-compose.dev.yml** —— 所有 `image` 与 `build.args` 都读 `.env`：

```dotenv
# .env
DOCKERHUB_MIRROR=docker.m.daocloud.io
GHCR_MIRROR=ghcr.io
```

不设置时默认值是 `docker.io` / `ghcr.io`，**行为与改造前完全一致**，网络正常的机器无感知。

> 注意：`DOCKERHUB_MIRROR` 只在拉取阶段生效。它不会改写镜像名，构建产物仍是标准镜像。

---

## 4. ghcr.io 镜像单独决策

本项目有一个镜像不在 Docker Hub：

```
ghcr.io/huggingface/text-embeddings-inference:cpu-1.2
```

**`registry-mirrors` 对它完全无效**（mirror 只加速 `docker.io`）。三条路，按环境选一条：

| 方案 | 做法 | 适用 |
|---|---|---|
| A. 直连 | 机器能访问 `ghcr.io`，什么都不用做 | 有外网/代理的环境 |
| B. 换源 | 找一个支持 GHCR 的源，设 `GHCR_MIRROR=<该源域名>` | 有可用替代源时 |
| C. 离线分发（推荐） | 联网机器打包 → 拷到目标机导入 | CI、内网、客户现场 |

方案 C 的执行命令：

```bash
# 在能联网的机器上打包（会自动拉取 + 重打标签 + 打成 tar）
bash scripts/offline-images.sh save

# 把 party-agent-images.tar 拷到目标机器后导入
bash scripts/offline-images.sh load

# 之后构建完全不触网
docker compose up -d --build
```

该脚本打包了项目全部基础镜像（含 `ghcr.io` 那个），是内网部署最稳的方式。

---

## 5. 长期方案：自建私有 registry

只要还在依赖公共加速器，"今天能用、明天挂掉"就会反复发生。团队规模稳定后，建议把基础
镜像统一缓存到自己的 registry。三个成熟选项：

| 方案 | 说明 |
|---|---|
| **Harbor**（自建） | 开源、可完全离线、带镜像代理缓存（proxy cache）功能 |
| **腾讯云 TCR** | 托管服务，与腾讯云 CVM 内网互通，免运维 |
| **阿里云 ACR** | 托管服务，与阿里云 ECS 内网互通，免运维 |

**推荐做法：用 Harbor 的 Proxy Cache。** 配置一个指向 `docker.io` 的代理项目后，任何
`docker pull <harbor>/proxy/xxx` 都会自动回源并缓存，之后同一镜像的拉取全部命中内网，
既快又不受公共源状态影响。

配置完成后，只需在 `.env` 里改一行，全场切换到私有源：

```dotenv
DOCKERHUB_MIRROR=registry.example.com/proxy
GHCR_MIRROR=registry.example.com/ghcr-proxy
```

**迁移到私有 registry 的操作步骤：**

```bash
# 1. 在 Harbor 上创建 proxy cache 项目，例如 proxy（指向 docker.io）
# 2. 登录
docker login registry.example.com

# 3. 用离线脚本把镜像推到私有 registry（替换 --mirror 指向 Harbor 代理）
#    或逐条执行：
for img in python:3.11-slim pgvector/pgvector:pg16 redis:7-alpine \
           dpage/pgadmin4:latest rediscommander/redis-commander:latest; do
  docker pull "registry.example.com/proxy/$img"
  docker tag  "registry.example.com/proxy/$img" "$img"
done

# 4. 在 .env 中设置 DOCKERHUB_MIRROR=registry.example.com/proxy
```

---

## 6. 候选镜像源速查

> **重要：公共镜像源的状态变化极快**（停服、限流、被拦截都可能在一夜之间发生）。
> 下表仅作候选清单，**使用前必须用 `scripts/check-docker-mirrors.sh` 实测**，
> 只把你网络环境下判定为「可用」的源填进 `daemon.json`。

| 源 | 性质 | 备注 |
|---|---|---|
| `docker.m.daocloud.io` | 社区公共源 | 常被推荐，可用性较好；模板默认值 |
| `docker.xuanyuan.me` | 社区公共源 | 有免费额度限制 |
| `mirror.baidubce.com` | 云厂商公共源 | 需实测 |
| `hub-mirror.c.163.com` | 云厂商公共源 | 老地址，时好时坏 |
| `docker.mirrors.ustc.edu.cn` | 高校源 | 可能仅对教育网开放 |
| `docker.1panelproxy.com` | 第三方代理 | **曾返回 HTML 错误页导致本次故障**，不建议 |
| `mirror.ccs.tencentyun.com` | 腾讯云**内网**专用 | **非腾讯云机器必然失败，务必删除** |

---

## 7. 快速命令卡

```bash
# 源自检
bash scripts/check-docker-mirrors.sh

# 查看当前生效的镜像源
docker info | grep -A5 "Registry Mirrors"

# 定位构建卡在哪一步（加 --progress plain）
docker compose build --progress plain

# 离线打包 / 导入
bash scripts/offline-images.sh save
bash scripts/offline-images.sh load

# 确认镜像是本地已有的（离线构建前自检）
docker images | grep -E "python|pgvector|redis|pgadmin|text-embeddings"
```

---

## 附：完整报错示例与对照

```
#1 [internal] load metadata for docker.io/library/python:3.11-slim
#1 ERROR: encountered unknown type text/html; children may not be fetched
------
error: failed to solve: ... failed to create LLB definition:
encountered unknown type text/html; children may not be fetched
```

出现这段即确认：**某台机器的 `registry-mirrors` 里有返回 HTML 的坏源**。
按第 2 步清理即可，与项目代码无关。
