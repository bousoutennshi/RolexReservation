#!/bin/bash
# launchd / 手動実行 共通のラッパー。
# venv の python で reserve.py を実行し、ログを logs/ に追記する。
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs
STAMP="$(date +%Y%m%d_%H%M%S)"

# launchd は最小限のPATHで起動するため、必要なら明示する
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

echo "===== run start ${STAMP} =====" >> logs/launchd.out
exec ./venv/bin/python reserve.py "$@" \
  >> "logs/launchd.out" 2>> "logs/launchd.err"
