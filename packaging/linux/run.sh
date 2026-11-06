#!/bin/sh
# 用随包便携 Python 直接起服务（不需要 Docker）。真实 SQL 需另行放置厂商驱动。
set -eu

BASE=$(cd "$(dirname "$0")" && pwd)
EXE="$BASE/python/bin/st-mcp"
[ -x "$EXE" ] || { echo "先执行 $BASE/install.sh" >&2; exit 1; }

# 动态连接默认只放行本机；要让别的客户端连指定库，改这两个变量后重启。
export ST_DYNAMIC_ENABLED="${ST_DYNAMIC_ENABLED:-yes}"
export ST_DYNAMIC_ALLOW="${ST_DYNAMIC_ALLOW:-127.0.0.1}"
export ST_DYNAMIC_ALLOW_PORTS="${ST_DYNAMIC_ALLOW_PORTS:-2003}"
export ST_DYNAMIC_ALLOW_DEFAULT="${ST_DYNAMIC_ALLOW_DEFAULT:-no}"
export ST_HOST="${ST_HOST:-127.0.0.1}"
export ST_PORT="${ST_PORT:-2003}"
export ST_USER="${ST_USER:-SYSDBA}"
export ST_DB="${ST_DB:-OSRDB}"

exec "$EXE" \
    --transport streamable-http \
    --sse-host "${SSE_HOST:-0.0.0.0}" \
    --sse-port "${SSE_PORT:-8100}" \
    --mcp-path "${MCP_PATH:-/mcp}" \
    --log-level "${LOG_LEVEL:-INFO}"
