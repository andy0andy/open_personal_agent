#!/usr/bin/env bash
# 备份（make backup）：数据库与 .workdata 里的个人文件，放在 BACKUP_ROOT/<时间>/，只保留最近 KEEP 份。
# manifest.txt 的 format=2 表示 D22（.workdata、设置进数据库）之后的备份；恢复脚本只认这个格式。
# 参数都来自环境变量（Makefile 给出正式环境的值；测试指向测试库与临时目录）：
#   PG_EXEC      在数据库容器里执行命令的前缀，如 "docker compose ... exec -T postgres"
#   PG_USER      数据库用户
#   DATABASES    要备份的库，空格分隔
#   WORKDATA     个人数据目录
#   FILE_DIRS    WORKDATA 下要打包的目录，空格分隔（不存在的跳过）
#   BACKUP_ROOT  备份放在哪
#   KEEP         保留最近几份
#   PREFIX       备份名的前缀（可选）：恢复前的自动备份用 pre-restore-，与手动备份分开计数
#   PROTECT      轮换时不删的备份名（可选，空格分隔）：如正要恢复的那份
#   BACKUP_TIME  当作"现在"的时间（可选，形如 20261024-030000）：只给测试用，平时不设
#   EMIT_NAME    设了就在最后多打印一行 BACKUP_NAME=<名字>（可选）：恢复脚本用它找到自动备份
# 兼容 macOS 自带的 bash 3.2：不用关联数组、mapfile；变量名后紧跟中文时一律写 ${名字}，
# 否则在某些语言设置下中文的字节会被当成变量名的一部分。
set -euo pipefail

: "${PG_EXEC:?}" "${PG_USER:?}" "${DATABASES:?}" "${WORKDATA:?}" "${FILE_DIRS:?}" "${BACKUP_ROOT:?}" "${KEEP:?}"

PREFIX="${PREFIX:-}"
PROTECT="${PROTECT:-}"
NAME_PATTERN="^${PREFIX}[0-9]{8}-[0-9]{6}(-[0-9]+)?\$"

mkdir -p "$BACKUP_ROOT"
name="${PREFIX}${BACKUP_TIME:-$(date +%Y%m%d-%H%M%S)}"
# 同一秒里做了两次（如恢复前的自动备份紧跟在手动备份之后）：加序号
if [ -e "$BACKUP_ROOT/$name" ]; then
  n=2
  while [ -e "$BACKUP_ROOT/$name-$n" ]; do n=$((n + 1)); done
  name="$name-$n"
fi
target="$BACKUP_ROOT/$name"
mkdir "$target"
# 被中断（Ctrl-C、被杀掉）时删掉这次的半成品，免得以后被当成一份备份
trap 'rm -rf "$target"; exit 130' INT TERM

fail() {
  echo "备份失败：$1（详情见 $target/backup.log）" >&2
  # 不完整的备份不留下，免得以后被当成可用的备份
  rm -rf "$target"
  exit 1
}

for db in $DATABASES; do
  # 只取标准输出：compose 的提示写在标准错误里，混进来会损坏备份文件
  $PG_EXEC pg_dump -U "$PG_USER" -Fc "$db" > "$target/$db.dump" 2>> "$target/backup.log" \
    || fail "数据库 $db 导出出错"
done

dirs=""
for dir in $FILE_DIRS; do
  if [ -d "$WORKDATA/$dir" ]; then dirs="$dirs $dir"; fi
done
# .seeded 记的是这份数据做过哪些默认内容的补写（backend/settings/seed.py），要跟着数据走：
# 不然恢复到新的 .workdata 后，删掉的默认技能、模型会在启动时被重新写回
entries="$dirs"
seeded="no"
if [ -f "$WORKDATA/.seeded" ]; then
  entries="$entries .seeded"
  seeded="yes"
fi
# shellcheck disable=SC2086 # entries 有意按空格拆开
tar -czf "$target/files.tar.gz" -C "$WORKDATA" $entries 2>> "$target/backup.log" \
  || fail "文件打包出错"

{
  echo "format=2"
  echo "created=$(date '+%Y-%m-%d %H:%M:%S')"
  echo "databases=$DATABASES"
  echo "dirs=${dirs# }"
  echo "seeded=$seeded"
} > "$target/manifest.txt"

trap - INT TERM

# 只保留最近 KEEP 份：只算同一前缀、完整的（有 manifest.txt）备份，名字按时间排序，删最旧的；
# 半成品不占名额，PROTECT 里的不删
backups=()
while IFS= read -r line; do
  [ -f "$BACKUP_ROOT/$line/manifest.txt" ] || continue
  case " $PROTECT " in *" $line "*) continue ;; esac
  backups+=("$line")
done < <(
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | grep -E "$NAME_PATTERN" | sort
)
excess=$(( ${#backups[@]} - KEEP ))
i=0
while [ "$i" -lt "$excess" ]; do
  rm -rf "${BACKUP_ROOT:?}/${backups[$i]}"
  i=$((i + 1))
done

size="$(du -sh "$target" | cut -f1)"
echo "已备份到 ${target}（${size}）"
if [ -n "${EMIT_NAME:-}" ]; then echo "BACKUP_NAME=$name"; fi
