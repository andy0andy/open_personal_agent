#!/usr/bin/env bash
# 恢复（make restore BACKUP=<名字>）：用一份备份替换现有的数据库与个人文件。参数同 backup.sh，另有：
#   BACKUP          备份目录名（BACKUP_ROOT 下）
#   CONFIRM         为 yes 时不再询问（测试用）
#   BEFORE_RESTORE  确认之后、动数据之前执行的命令（可选；Makefile 用它停掉 backend 与 litellm）
#   AFTER_RESTORE   结束时执行的命令（可选；无论成败，只要执行过 BEFORE_RESTORE 就会执行）
#   SAFETY_KEEP     恢复前的自动备份保留几份（默认 3）
# 顺序：检查（名字、完整、能读）→ 确认 → 停服务 → 备份当前数据 → 各库先恢复到临时库，全部成功后
# 再整体替换（失败时现有的库完全不动；与备份完全一致，备份之后新建的表不会残留）→ 恢复文件
# （备份里有 .seeded 就整份换成备份时的；没有的旧备份不动现有的）。
# 恢复后会话或消息比恢复前少时，结尾提醒一句（设计 2026-10-23 7.2）。
# 兼容 macOS 自带的 bash 3.2；变量名后紧跟中文时写 ${名字}。
set -euo pipefail

: "${PG_EXEC:?}" "${PG_USER:?}" "${WORKDATA:?}" "${FILE_DIRS:?}" "${BACKUP_ROOT:?}" "${KEEP:?}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
name="${BACKUP:-}"
source_dir="$BACKUP_ROOT/$name"

refuse() {
  echo "$1" >&2
  exit 1
}

if [ -z "$name" ] || [ ! -d "$source_dir" ]; then
  refuse "找不到备份：${name:-（没有给出名字）}。已有的备份在 ${BACKUP_ROOT}/ 下"
fi

# 1. 检查备份是否完整、能读：有问题就不动现有数据，也不停服务
manifest="$source_dir/manifest.txt"
[ -f "$manifest" ] || refuse "备份不完整：缺少 manifest.txt（可能是中断的备份）"
# 迁移前（第一轮优化之前，D22）的备份：库结构与目录都不一样，恢复了也用不了
grep -qx "format=2" "$manifest" \
  || refuse "这份备份是旧格式（第一轮优化之前做的），不能恢复到现在的版本；需要时先用 2026-10-19 的整体快照退回旧版本（见快照里的 README.txt）"
databases="$(sed -n 's/^databases=//p' "$manifest")"
[ -s "$source_dir/files.tar.gz" ] || refuse "备份不完整：缺少 files.tar.gz"
for db in $databases; do
  [ -s "$source_dir/$db.dump" ] || refuse "备份不完整：缺少 ${db}.dump"
  $PG_EXEC pg_restore --list < "$source_dir/$db.dump" > /dev/null 2>&1 \
    || refuse "备份已损坏：${db}.dump 读不出来"
done
tar -tzf "$source_dir/files.tar.gz" > /dev/null 2>&1 || refuse "备份已损坏：files.tar.gz 读不出来"

# 2. 确认
if [ "${CONFIRM:-}" != "yes" ]; then
  printf '将用备份 %s 替换现有的对话、知识库和文件。恢复前会先自动备份当前数据。输入 yes 继续：' "$name"
  read -r answer || answer=""
  if [ "$answer" != "yes" ]; then
    echo "没有恢复。"
    exit 1
  fi
fi

# 结尾的提醒（数据变少了）：停过服务时等服务起来以后再说，免得被起服务的输出盖住
note=""
# 起回服务（在子 shell 里：起不来时它会 exit 1，不能让提醒没机会说），保留原来的退出码
restart_services() {
  exit_status=$?
  trap - EXIT
  if [ -n "${AFTER_RESTORE:-}" ]; then
    (eval "$AFTER_RESTORE") || exit_status=1
  fi
  if [ -n "$note" ]; then echo "$note"; fi
  exit "$exit_status"
}

# 3. 停服务；之后无论成败（包括 Ctrl-C）都把它们起回来
if [ -n "${BEFORE_RESTORE:-}" ]; then
  trap restart_services EXIT
  trap 'exit 130' INT TERM
  eval "$BEFORE_RESTORE"
fi

# 不显示 "does not exist, skipping" 之类的英文提示；出错信息照常显示
psql_admin() {
  $PG_EXEC psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -q \
    -c "SET client_min_messages = warning" -c "$1" > /dev/null
}

# 一个库里的会话数与消息数（消息按 runs 的行数），输出"会话数 消息数"；
# 库不存在、没有这两张表时（比如测试用的库、网关的库）什么都不输出
count_data() {
  local has
  has="$($PG_EXEC psql -U "$PG_USER" -d "$1" -At -c "SELECT to_regclass('public.threads') \
    IS NOT NULL AND to_regclass('public.runs') IS NOT NULL" 2> /dev/null)" || return 0
  [ "$has" = "t" ] || return 0
  $PG_EXEC psql -U "$PG_USER" -d "$1" -At -F ' ' \
    -c "SELECT (SELECT count(*) FROM threads), (SELECT count(*) FROM runs)" 2> /dev/null || true
}

# 恢复会让会话或消息变少时输出"会话 A→B、消息 C→D，比恢复前少；"（比较现在的库与恢复好的临时库）
shrink_note() {
  local now restoring
  now="$(count_data "$1")"
  restoring="$(count_data "${1}__restoring")"
  [ -n "$now" ] && [ -n "$restoring" ] || return 0
  # shellcheck disable=SC2086 # 有意按空格拆成四个数
  set -- $now $restoring
  if [ "$3" -lt "$1" ] || [ "$4" -lt "$2" ]; then
    echo "会话 ${1}→${3}、消息 ${2}→${4}，比恢复前少；"
  fi
}

safety=""
restored=""
shrunk=""
abort() {
  echo "恢复中途失败：${1}。" >&2
  if [ -n "$restored" ]; then echo "已经替换的：${restored}。" >&2; fi
  if [ -n "$safety" ]; then
    echo "恢复前的数据在备份 ${safety} 里，可用 make restore BACKUP=${safety} 退回。" >&2
  fi
  exit 1
}

# 4. 备份当前数据（单独命名、单独保留，不挤掉手动备份；正要恢复的那份不会被删）
safety_output="$(
  EMIT_NAME=1 PREFIX="pre-restore-" KEEP="${SAFETY_KEEP:-3}" PROTECT="$name" \
    DATABASES="$databases" bash "$here/backup.sh"
)" || abort "恢复前的自动备份失败，现有数据没有动"
safety="$(echo "$safety_output" | sed -n 's/^BACKUP_NAME=//p')"

# 5. 各库先恢复到临时库（单个事务，出错即停），全部成功后再替换
for db in $databases; do
  psql_admin "DROP DATABASE IF EXISTS \"${db}__restoring\" WITH (FORCE)" \
    || abort "建临时库 ${db}__restoring 失败，现有数据没有动"
  psql_admin "CREATE DATABASE \"${db}__restoring\"" \
    || abort "建临时库 ${db}__restoring 失败，现有数据没有动"
  $PG_EXEC pg_restore -U "$PG_USER" --no-owner --exit-on-error --single-transaction \
    -d "${db}__restoring" < "$source_dir/$db.dump" > /dev/null \
    || abort "数据库 ${db} 恢复失败，现有数据没有动"
  # 服务已停、现有的库还没动：这时数一遍恢复前后的会话与消息
  shrunk="${shrunk}$(shrink_note "$db")"
done
for db in $databases; do
  psql_admin "DROP DATABASE IF EXISTS \"${db}__old\" WITH (FORCE)" || abort "替换数据库 ${db} 失败"
  psql_admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE datname = '${db}' AND pid <> pg_backend_pid()" || abort "替换数据库 ${db} 失败"
  if [ -n "$($PG_EXEC psql -U "$PG_USER" -d postgres -At -c \
    "SELECT 1 FROM pg_database WHERE datname = '${db}'")" ]; then
    psql_admin "ALTER DATABASE \"${db}\" RENAME TO \"${db}__old\"" || abort "替换数据库 ${db} 失败"
  fi
  psql_admin "ALTER DATABASE \"${db}__restoring\" RENAME TO \"${db}\"" || abort "替换数据库 ${db} 失败"
  psql_admin "DROP DATABASE IF EXISTS \"${db}__old\" WITH (FORCE)" || true
  restored="${restored:+${restored}、}数据库 ${db}"
done

# 6. 文件：先解到临时目录，成功后再替换各目录的内容（保留目录本身：它可能被容器挂载着）
staging="$WORKDATA/.restoring"
rm -rf "$staging"
mkdir -p "$staging"
tar -xzf "$source_dir/files.tar.gz" -C "$staging" || abort "解开 files.tar.gz 失败"
# macOS 的 find 删除或搬动失败时仍返回成功，所以做完后检查目录是否真的空了
for dir in $FILE_DIRS; do
  mkdir -p "$WORKDATA/$dir" || abort "准备目录 ${dir} 失败"
  find "$WORKDATA/$dir" -mindepth 1 -delete 2> /dev/null || true
  [ -z "$(ls -A "$WORKDATA/$dir")" ] || abort "清空目录 ${dir} 失败"
  if [ -d "$staging/$dir" ]; then
    find "$staging/$dir" -mindepth 1 -maxdepth 1 -exec mv {} "$WORKDATA/$dir/" \; 2> /dev/null || true
    [ -z "$(ls -A "$staging/$dir")" ] || abort "放回目录 ${dir} 的文件失败"
  fi
  restored="${restored:+${restored}、}目录 ${dir}"
done
# .seeded 记的是"备份时那份数据做过哪些补写"：整份替换、不合并（比如恢复一份没有会话索引的
# 旧备份时，能让索引重新补建）；备份里没有（旧备份）就不动现有的
if [ -f "$staging/.seeded" ]; then
  mv -f "$staging/.seeded" "$WORKDATA/.seeded" || abort "放回 .seeded 失败"
  restored="${restored:+${restored}、}.seeded"
fi
rm -rf "$staging"

echo "已恢复备份 ${name}。恢复前的数据备份在 ${safety}（${BACKUP_ROOT}/${safety}）"
if [ -n "$shrunk" ]; then
  note="${shrunk}不是你想要的就用 ${safety} 退回（make restore BACKUP=${safety}）"
  if [ -z "${BEFORE_RESTORE:-}" ]; then echo "$note"; fi
fi
