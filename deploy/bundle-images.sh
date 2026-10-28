#!/usr/bin/env bash
# 打包镜像（make bundle，设计 2026-10-28 4.4）：在构建电脑上构建 backend、拉取另外几个镜像，
# 把 compose 用到的全部镜像存成一个文件；目标机器 load 之后直接 compose up -d。
# 参数都来自环境变量：
#   COMPOSE     compose 命令（默认：docker 可用就 docker compose，否则 podman compose）
#   PLATFORM    目标机器的芯片，如 linux/arm64（可选；同时作用于构建与拉取）
#   SKIP_BUILD  为 1 时不构建、不拉取，只把本机已有的镜像存起来
#   OUT_DIR     存放位置（默认项目里的 dist/）
# 兼容 macOS 自带的 bash 3.2；变量名后紧跟中文时写 ${名字}。
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 构建电脑上不需要 .env（.env 只是本机运行时的环境变量）：compose 用一份空的环境文件解析，
# 两项必填的密钥给占位值——只用来让 compose 文件解析得过去，不进镜像
empty_env="$(mktemp)"
trap 'rm -f "$empty_env"' EXIT
export LITELLM_SALT_KEY="${LITELLM_SALT_KEY:-bundle-placeholder}"
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-bundle-placeholder}"
# 与 Makefile 一样用项目里的空 Docker 配置：本机全局配置残留的凭据程序会让构建、拉取失败
export DOCKER_CONFIG="${DOCKER_CONFIG:-$root/deploy/docker-config}"
if [ -z "${COMPOSE:-}" ]; then
  if command -v docker > /dev/null 2>&1 && docker info > /dev/null 2>&1; then
    COMPOSE="docker compose"
  else
    COMPOSE="podman compose"
  fi
fi
engine="${COMPOSE%% *}" # docker 或 podman：save 用它
case "$(basename "$engine")" in
  docker | podman) ;;
  *)
    echo "COMPOSE 要写成 'docker compose' 或 'podman compose'（现在是：${COMPOSE}）" >&2
    exit 1
    ;;
esac
# shellcheck disable=SC2206 # 有意按空格拆成命令与参数
compose=($COMPOSE --env-file "$empty_env" -f "$root/deploy/docker-compose.yml")

if [ -n "${PLATFORM:-}" ]; then
  export DOCKER_DEFAULT_PLATFORM="$PLATFORM"
fi

if [ "${SKIP_BUILD:-}" != "1" ]; then
  "${compose[@]}" build backend
  "${compose[@]}" pull postgres litellm ollama
elif [ -n "${PLATFORM:-}" ]; then
  echo "注意：SKIP_BUILD=1 时不构建也不拉取，PLATFORM 不起作用，存的是本机已有的镜像" >&2
fi

images="$("${compose[@]}" config --images | sort -u)"
out="${OUT_DIR:-$root/dist}"
mkdir -p "$out"
file="$out/open-personal-agent-images-$(date +%Y%m%d-%H%M%S).tar"
# podman 存多个镜像要 -m（多镜像归档），docker 本来就支持
multi=()
if [ "$(basename "$engine")" = "podman" ]; then multi=(-m); fi
# shellcheck disable=SC2086 # images 有意按换行拆开
"$engine" save ${multi[@]+"${multi[@]}"} -o "$file" $images

echo "已存到 ${file}"
echo "目标机器上：podman load -i $(basename "$file")（或 docker load -i …），然后在 deploy 目录里 podman compose up -d"
