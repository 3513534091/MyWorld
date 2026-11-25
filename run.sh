#!/usr/bin/env sh
# MyWorld 启动脚本（Linux / macOS / Git Bash）
set -eu
cd "$(dirname "$0")"
exec python3 -m myworld "$@"
