#!/bin/sh
# 离线安装随包的唯一依赖（不联网）。安装到随包便携 Python，不改系统环境。
set -eu

BASE=$(cd "$(dirname "$0")" && pwd)
PY="$BASE/python/bin/python3"
if [ ! -x "$PY" ]; then
    RT=$(ls "$BASE"/runtime/cpython-*.tar.gz 2>/dev/null | head -n 1)
    [ -n "$RT" ] || { echo "缺少便携 Python 压缩包：$BASE/runtime/" >&2; exit 1; }
    echo "[0/3] 解压便携 Python 到 $BASE/python"
    tar -xzf "$RT" -C "$BASE"
fi
[ -x "$PY" ] || { echo "便携 Python 解压失败：$PY" >&2; exit 1; }

WHEELS="$BASE/wheels"
[ -d "$WHEELS" ] || { echo "缺少依赖目录：$WHEELS" >&2; exit 1; }

echo "[1/3] 安装开源依赖"
"$PY" -m pip install --no-index --find-links "$WHEELS" -r "$WHEELS/requirements.txt"

echo "[2/3] 安装 st-mcp"
"$PY" -m pip install --no-index --no-deps "$BASE"/dist/st_mcp-*.whl

"$PY" -c 'import st_mcp, mcp; print("ok:", st_mcp.__file__)'
echo "完成。启动：$BASE/run.sh"
echo "真实 SQL 还需要厂商的 STPython 驱动和 libaci.so，见 vendor/PUT-FILES-HERE.md。"
