#!/usr/bin/env bash
#
# 项目镜像离线打包 / 分发（docker save / docker load）
#
# 适用场景：
#   目标机器（CI / 内网服务器 / 客户现场）无法稳定访问 Docker Hub 或 ghcr.io，
#   与其反复折腾加速源，不如在能联网的机器上一次性打包好，拷贝过去直接 load。
#   这是对 ghcr.io 镜像（registry-mirrors 对其完全无效）最可靠的方案。
#
# 用法：
#   打包（在能联网的机器上执行）：
#     bash scripts/offline-images.sh save
#     bash scripts/offline-images.sh save --mirror docker.m.daocloud.io
#   导入（在目标机器上执行，需先把 tar 拷过去）：
#     bash scripts/offline-images.sh load
#     bash scripts/offline-images.sh load --bundle /path/to/party-agent-images.tar
#
set -uo pipefail

ACTION="${1:-}"
if [ "$#" -gt 0 ]; then shift; fi

BUNDLE="party-agent-images.tar"
MIRROR="docker.m.daocloud.io"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mirror) MIRROR="${2#https://}"; MIRROR="${MIRROR#http://}"; MIRROR="${MIRROR%/}"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    -h|--help) ACTION="help"; shift ;;
    *) echo "未知参数：$1"; exit 1 ;;
  esac
done

# 格式： "<加速源下的路径>|<本地目标标签>"
DOCKERHUB_IMAGES=(
  "library/python:3.11-slim|python:3.11-slim"
  "pgvector/pgvector:pg16|pgvector/pgvector:pg16"
  "library/redis:7-alpine|redis:7-alpine"
  "dpage/pgadmin4:latest|dpage/pgadmin4:latest"
  "rediscommander/redis-commander:latest|rediscommander/redis-commander:latest"
)

# 非 Docker Hub 镜像（registry-mirrors 无效，只能直连或走支持 ghcr 的源）
OTHER_IMAGES=(
  "ghcr.io/huggingface/text-embeddings-inference:cpu-1.2"
)

TARGETS=()
for entry in "${DOCKERHUB_IMAGES[@]}"; do
  TARGETS+=("${entry##*|}")
done
for img in "${OTHER_IMAGES[@]}"; do
  TARGETS+=("$img")
done

usage() {
  sed -n '2,20p' "$0"
}

do_save() {
  command -v docker >/dev/null 2>&1 || { echo "错误：未找到 docker 命令。" >&2; exit 1; }
  ok=0; fail=0

  echo "== 第 1 步：从加速源拉取 Docker Hub 镜像并重打标签 =="
  echo "   加速源：${MIRROR}"
  for entry in "${DOCKERHUB_IMAGES[@]}"; do
    src="${MIRROR}/${entry%%|*}"
    dst="${entry##*|}"
    printf '  [%s] <- %s\n' "$dst" "$src"
    if docker pull "$src" >/dev/null 2>&1; then
      docker tag "$src" "$dst" && { echo "      ✓ 就绪"; ok=$((ok + 1)); }
    else
      echo "      ✗ 拉取失败，请先运行 scripts/check-docker-mirrors.sh 换一个可用源"
      fail=$((fail + 1))
    fi
  done

  echo
  echo "== 第 2 步：直连拉取非 Docker Hub 镜像 =="
  for img in "${OTHER_IMAGES[@]}"; do
    printf '  [%s]\n' "$img"
    if docker pull "$img" >/dev/null 2>&1; then
      echo "      ✓ 就绪"; ok=$((ok + 1))
    else
      echo "      ✗ 拉取失败：ghcr.io 无法通过 registry-mirrors 加速，"
      echo "        请换一台能直连 GHCR 的机器打包，或改用私有 registry 同步。"
      fail=$((fail + 1))
    fi
  done

  if [ "$fail" -gt 0 ]; then
    echo
    echo "有 ${fail} 个镜像未就绪，已中止打包。修好后再重跑本命令。"
    exit 1
  fi

  echo
  echo "== 第 3 步：打包为 ${BUNDLE} =="
  docker save -o "$BUNDLE" "${TARGETS[@]}" && {
    size="$(du -h "$BUNDLE" 2>/dev/null | cut -f1)"
    echo "  ✓ 打包完成：${BUNDLE}（${size:-未知大小}）"
    echo
    echo "下一步：把 ${BUNDLE} 拷贝到目标机器，然后执行"
    echo "  bash scripts/offline-images.sh load --bundle ${BUNDLE}"
  }
}

do_load() {
  command -v docker >/dev/null 2>&1 || { echo "错误：未找到 docker 命令。" >&2; exit 1; }
  [ -f "$BUNDLE" ] || { echo "错误：找不到镜像包 ${BUNDLE}" >&2; exit 1; }

  echo "== 导入镜像包 ${BUNDLE} =="
  docker load -i "$BUNDLE" && {
    echo "  ✓ 导入完成。以下镜像现已就绪："
    for t in "${TARGETS[@]}"; do echo "    - $t"; done
    echo
    echo "现在可以直接构建，无需再访问任何外部 registry："
    echo "  docker compose up -d --build"
  }
}

case "$ACTION" in
  save) do_save ;;
  load) do_load ;;
  *) usage; echo; echo "请指定动作：save 或 load" ;;
esac
