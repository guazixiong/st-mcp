#!/bin/sh
# 在**联网机器**上准备离线部署需要的两类二进制，产物随仓库目录一起拷进内网。
# 用法：sh tools/fetch-offline-deps.sh [目标目录，默认 wheels/]
# 说明：只下载开源依赖（wheels/requirements.txt），不下载也不分发厂商闭源件。
set -eu

PKG=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-"$PKG/wheels"}
REQ="$PKG/wheels/requirements.txt"

[ -f "$REQ" ] || { echo "缺少 $REQ"; exit 1; }
mkdir -p "$OUT"

command -v python3 >/dev/null 2>&1 || python3 -c 'import pip' 2>/dev/null || {
    echo "需要 python3 + pip（在联网机器上执行本脚本）"; exit 1; }

PY=$(command -v python3 || command -v python)

echo "[1/2] 下载开源轮子（cp311 / aarch64，不安装到本机）"
"$PY" -m pip download -r "$REQ" \
    --only-binary=:all: \
    --python-version 311 \
    --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 --platform linux_aarch64 \
    -d "$OUT"

echo "  得到 $(ls "$OUT"/*.whl 2>/dev/null | wc -l) 个轮子"
echo "  还需要手工放：厂商 STPython-*-cp311-cp311-linux_aarch64.whl（见 vendor/PUT-FILES-HERE.md）"

echo "[2/2] 基础镜像（可选，目标机完全断网时才需要）"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker pull --platform linux/arm64 python:3.11-slim
    docker save python:3.11-slim | gzip -1 > "$PKG/images/01-python-3.11-slim.tar.gz"
    echo "  images/01-python-3.11-slim.tar.gz = $(wc -c < "$PKG/images/01-python-3.11-slim.tar.gz") 字节"
else
    echo "  本机没有可用的 docker，跳过；目标机能联网就不用这个文件"
fi

echo "完成。把整个目录（含 wheels/ images/ aci/ vendor/ 里的文件）拷到目标机即可离线部署。"
