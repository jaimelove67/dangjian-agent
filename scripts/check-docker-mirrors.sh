#!/usr/bin/env bash
#
# Docker 镜像加速源可用性自检
#
# 用途：
#   当 docker pull / docker build 报
#     unexpected media type text/html
#     encountered unknown type text/html; children may not be fetched
#   或长时间卡住时，先跑这个脚本，快速定位是哪个加速源坏了。
#
# 判定依据：
#   真 registry 的 /v2/ 端点返回 JSON（通常 401 + application/json）；
#   坏掉的加速源（停服 / 过载 / 被拦截）会返回一张 HTML 网页 -> text/html。
#
# 用法：
#   bash scripts/check-docker-mirrors.sh
#   bash scripts/check-docker-mirrors.sh https://docker.m.daocloud.io https://your-mirror
#
set -uo pipefail

TIMEOUT=8
PROBE_PATH="/v2/"
SEP="--------------------------------------------------------------------------------"

DEFAULT_MIRRORS=(
  "https://docker.m.daocloud.io"
  "https://docker.1panelproxy.com"
  "https://docker.xuanyuan.me"
  "https://hub-mirror.c.163.com"
  "https://mirror.baidubce.com"
  "https://docker.mirrors.ustc.edu.cn"
  "https://mirror.ccs.tencentyun.com"
)

if [ "$#" -gt 0 ]; then
  MIRRORS=("$@")
else
  MIRRORS=("${DEFAULT_MIRRORS[@]}")
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "错误：需要 curl，请先安装。" >&2
  exit 1
fi

printf '%-36s %-6s %-20s %s\n' "镜像源" "HTTP" "Content-Type" "判定"
echo "$SEP"

pass=0
total=0

for url in "${MIRRORS[@]}"; do
  total=$((total + 1))
  base="${url%/}"
  probe="${base}${PROBE_PATH}"

  resp="$(curl -sS -m "$TIMEOUT" -o /dev/null -w '%{http_code} %{content_type}' "$probe" 2>/dev/null)"
  code="$(printf '%s' "$resp" | awk '{print $1}')"
  ctype="$(printf '%s' "$resp" | cut -d' ' -f2-)"
  [ -z "$code" ] && code="000"
  [ -z "$ctype" ] && ctype="-"

  if [ "$code" = "000" ]; then
    verdict="不可达（连接失败或超时）"
  elif printf '%s' "$ctype" | grep -qi 'text/html'; then
    verdict="坏源：返回 HTML 网页，不是 registry"
  elif printf '%s' "$ctype" | grep -qi 'json'; then
    verdict="可用（真 registry）"
    pass=$((pass + 1))
  elif [ "$code" = "200" ] || [ "$code" = "401" ]; then
    verdict="疑似可用（HTTP 正常，但返回非 JSON）"
    pass=$((pass + 1))
  else
    verdict="异常（HTTP ${code}）"
  fi

  printf '%-36s %-6s %-20s %s\n' "$base" "$code" "$(printf '%s' "$ctype" | cut -c1-20)" "$verdict"
done

echo "$SEP"
echo "结论：${total} 个源中 ${pass} 个可用。"

if [ "$pass" -eq 0 ]; then
  echo "提示：所有源都不可用。请检查网络 / 代理设置，或改用自建 / 云厂商私有 registry。"
elif [ "$pass" -lt "$total" ]; then
  echo "提示：存在不可用的源。请把坏源从 daemon.json 的 registry-mirrors 中删除，"
  echo "      只保留上面判定为「可用」的 1~2 个，避免坏源拖垮整次拉取。"
fi
