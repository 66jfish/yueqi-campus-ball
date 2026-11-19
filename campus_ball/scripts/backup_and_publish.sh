#!/usr/bin/env bash
# ============================================================================
# 数据库备份 → 恢复验证 → 入库存档 → 双平台推送（在服务器上执行，一条命令搞定）
# ----------------------------------------------------------------------------
# 用法（在仓库根目录）：
#     bash scripts/backup_and_publish.sh
#     bash scripts/backup_and_publish.sh --sanitize   # 顺带脱敏手机号（仓库公开时建议加）
#
# 它会依次做：
#   1. mysqldump 导出到 ~/backup/final_backup.sql（并校验大小/含 CREATE TABLE）
#   2. 导入临时库 restore_test 验证可恢复，比对表数量一致后 DROP 掉临时库
#   3. 复制到 deliverables/final_backup.sql 并 commit
#   4. 同时 push 到 origin(GitHub) 与 gitee(Gitee)，任一失败会明确提示
# ============================================================================
set -euo pipefail

SANITIZE=0
[[ "${1:-}" == "--sanitize" ]] && SANITIZE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ★ 自动定位仓库根目录：脚本在 <repo>/campus_ball/scripts/ 下，
#   所以根目录是「上两级」；同时兼容把脚本放到 <repo>/scripts/ 的情况。
#   （上一版只回退一级，导致把 campus_ball/ 当成了仓库根 → 误报找不到 .env）
REPO_ROOT=""
for cand in "$SCRIPT_DIR/.." "$SCRIPT_DIR/../.."; do
  if [[ -f "$cand/campus_ball/.env" ]]; then
    REPO_ROOT="$(cd "$cand" && pwd)"
    break
  fi
done
if [[ -z "$REPO_ROOT" ]]; then
  echo "✗ 未能定位仓库根目录（应包含 campus_ball/.env）"
  echo "  脚本位置：$SCRIPT_DIR"
  echo "  请确认 .env 存在于 <仓库根>/campus_ball/.env"
  exit 1
fi
cd "$REPO_ROOT"
echo "仓库根目录：$REPO_ROOT"

ENV_FILE="campus_ball/.env"
BACKUP_DIR="$HOME/backup"
BACKUP_FILE="$BACKUP_DIR/final_backup.sql"
TARGET="deliverables/final_backup.sql"
CONTAINER="yueqi-mysql"
DB="campus_ball"
TMP_DB="restore_test"

[[ -f "$ENV_FILE" ]] || { echo "✗ 找不到 $ENV_FILE（请在仓库根目录执行，且 .env 已配置）"; exit 1; }
ROOT_PW="$(grep -E '^MYSQL_ROOT_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
[[ -n "$ROOT_PW" ]] || { echo "✗ .env 里没有 MYSQL_ROOT_PASSWORD"; exit 1; }

# 统一用 MYSQL_PWD 传密码：避免 -p 参数在命令行暴露，也绕开引号嵌套问题
DOCKER_EXEC=(sudo docker exec -i -e "MYSQL_PWD=$ROOT_PW" "$CONTAINER")
mysql_exec() { "${DOCKER_EXEC[@]}" mysql -uroot "$@"; }

echo "[1/4] 导出备份 → $BACKUP_FILE"
mkdir -p "$BACKUP_DIR"
"${DOCKER_EXEC[@]}" mysqldump -uroot --single-transaction --routines --triggers "$DB" > "$BACKUP_FILE"
SIZE=$(wc -c < "$BACKUP_FILE")
echo "      大小：${SIZE} 字节"
[[ "$SIZE" -gt 1024 ]] || { echo "✗ 备份文件过小，疑似导出失败（检查容器名/密码）"; exit 1; }
grep -q "CREATE TABLE" "$BACKUP_FILE" && echo "      ✓ 含 CREATE TABLE" || { echo "✗ 未发现 CREATE TABLE"; exit 1; }
echo "      开头几行："; head -n 3 "$BACKUP_FILE" | sed 's/^/        /'

echo "[2/4] 恢复验证：导入临时库 $TMP_DB"
"${DOCKER_EXEC[@]}" mysql -uroot -e "DROP DATABASE IF EXISTS $TMP_DB; CREATE DATABASE $TMP_DB DEFAULT CHARACTER SET utf8mb4;"
"${DOCKER_EXEC[@]}" mysql -uroot "$TMP_DB" < "$BACKUP_FILE"
SRC_TABLES=$(mysql_exec -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB'")
DST_TABLES=$(mysql_exec -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$TMP_DB'")
SRC_USERS=$(mysql_exec -N -e "SELECT COUNT(*) FROM $DB.t_user")
DST_USERS=$(mysql_exec -N -e "SELECT COUNT(*) FROM $TMP_DB.t_user")
echo "      表数量：$DB=$SRC_TABLES  $TMP_DB=$DST_TABLES"
echo "      用户行数：$DB=$SRC_USERS  $TMP_DB=$DST_USERS"
if [[ "$SRC_TABLES" == "$DST_TABLES" && "$SRC_USERS" == "$DST_USERS" ]]; then
  echo "      ✓ 恢复验证通过"
else
  echo "      ✗ 恢复后数据不一致，已保留 $TMP_DB 供排查（未删除）"; exit 1
fi
"${DOCKER_EXEC[@]}" mysql -uroot -e "DROP DATABASE $TMP_DB"
echo "      ✓ 临时库已清理"

echo "[3/4] 复制到仓库并提交"
mkdir -p deliverables
cp "$BACKUP_FILE" "$TARGET"
if [[ "$SANITIZE" == "1" ]]; then
  # 脱敏：手机号替换为占位符（公开仓库建议执行）
  sed -i -E "s/'1[3-9][0-9]{9}'/'138****0000'/g" "$TARGET"
  echo "      ✓ 已脱敏手机号（--sanitize）"
fi
git add "$TARGET"
git commit -m "chore: 归档数据库备份 final_backup.sql（含演示数据与演示账号）" || echo "      （无变化，跳过提交）"

echo "[4/4] 推送双平台"
# Gitee remote 不存在时自动补上（服务器通常只 clone 了 GitHub）
if ! git remote get-url gitee >/dev/null 2>&1; then
  git remote add gitee https://gitee.com/j_66_fish/yueqi-campus-ball.git
  echo "      已添加 gitee 远端：https://gitee.com/j_66_fish/yueqi-campus-ball.git"
fi
git push origin main && echo "      ✓ GitHub(origin) 已推送" || echo "      ✗ GitHub 推送失败（网络或认证），稍后可用 git push origin main 重试"
if git push gitee main; then
  echo "      ✓ Gitee(gitee) 已推送"
else
  echo "      ✗ Gitee 推送失败（通常是服务器没有 Gitee 凭据），改用一次性 URL："
  echo "        git push https://j_66_fish:<你的GiteeToken>@gitee.com/j_66_fish/yueqi-campus-ball.git main:main"
fi

echo
echo "完成。仓库内路径：$TARGET"
