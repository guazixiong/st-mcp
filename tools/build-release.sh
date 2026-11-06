#!/bin/sh
# 生成 GitHub Release 资产：源码包、通用 wheel、linux-arm64、linux-x86_64、
# windows-x64，以及 SHA256SUMS。只在本地运行，所有输入都是本机文件。
#
# 需要事先准备（环境变量）：
#   ARM64_PY_TGZ   便携 CPython 3.11（linux-arm64, install_only 包）
#   X64_PY_TGZ     便携 CPython 3.11（linux-x86_64, install_only 包）
#   ARM64_WHEELS   linux-arm64 开源依赖轮子目录（不含 STPython）
#   X64_WHEELS     linux-x86_64 开源依赖轮子目录（不含 STPython）
#   WIN_BUNDLE     已解压的 Windows 运行包目录（含 env/ config/ scripts/）
# 可选：
#   VER（默认 0.1.0） OUT（默认 release/） SEVENZIP（Windows 上的 7z 路径）
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VER=${VER:-0.1.0}
OUT=${OUT:-$ROOT/release}
WHEEL="$ROOT/dist/st_mcp-$VER-py3-none-any.whl"
STAGE="$ROOT/.release-stage"
LINUX_TEMPLATE="$ROOT/packaging/RELEASE-README-linux.md"
WIN_TEMPLATE="$ROOT/packaging/RELEASE-README-windows.md"

need() { [ -e "$2" ] || { echo "缺少 $1：$2" >&2; exit 1; }; }

# Git Bash 的 GNU tar 会把 D:/ 当成远程主机，统一转成 /d/ 形式。
u() { if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf %s "$1"; fi; }
need ARM64_PY_TGZ "${ARM64_PY_TGZ:-}" 
need X64_PY_TGZ "${X64_PY_TGZ:-}"
need ARM64_WHEELS "${ARM64_WHEELS:-}"
need X64_WHEELS "${X64_WHEELS:-}"
need WIN_BUNDLE "${WIN_BUNDLE:-}"
need wheel "$WHEEL"

rm -rf "$STAGE"
mkdir -p "$OUT" "$STAGE/src"

echo "[1/5] 导出源码"
git -C "$ROOT" archive --format=tar HEAD | tar -xf - -C "$STAGE/src"

# 依赖目录：只要开源轮子，厂商闭源件（STPython）与本项目自身轮子不进来。
stage_wheels() {
    w_src=$1
    w_dst=$2
    mkdir -p "$w_dst"
    for w in "$w_src"/*.whl; do
        [ -e "$w" ] || continue
        base=$(basename "$w")
        case "$base" in
            STPython*|st_mcp-*|stpython-*) continue ;;
        esac
        cp -p "$w" "$w_dst/"
    done
    cp -p "$ROOT/wheels/requirements.txt" "$w_dst/"
}

build_linux() {
    arch=$1
    py_tgz=$2
    wheels_dir=$3
    name="st-mcp-$VER-linux-$arch"
    dst="$STAGE/$name"
    echo "[linux-$arch] 组装 $name"
    mkdir -p "$dst/source"
    cp -a "$STAGE/src/." "$dst/source/"
    mkdir -p "$dst/runtime"
    cp -p "$(u "$py_tgz")" "$dst/runtime/"
    stage_wheels "$wheels_dir" "$dst/wheels"
    mkdir -p "$dst/dist"
    cp -p "$WHEEL" "$dst/dist/"
    cp -p "$ROOT/packaging/linux/install.sh" "$dst/install.sh"
    cp -p "$ROOT/packaging/linux/run.sh" "$dst/run.sh"
    chmod +x "$dst/install.sh" "$dst/run.sh"
    sed -e "s/{PLATFORM}/linux-$arch/g" -e "s/{VER}/$VER/g" "$LINUX_TEMPLATE" > "$dst/RELEASE-README.md"
    for f in install.sh run.sh RELEASE-README.md dist/st_mcp-$VER-py3-none-any.whl; do
        [ -e "$dst/$f" ] || { echo "linux-$arch 缺少 $f" >&2; exit 1; }
    done
    [ -d "$dst/source/src" ] || { echo "linux-$arch 源码不完整" >&2; exit 1; }
    tar -czf "$(u "$OUT/$name.tar.gz")" -C "$STAGE" "$name"
}

build_linux arm64 "$ARM64_PY_TGZ" "$ARM64_WHEELS"
build_linux x86_64 "$X64_PY_TGZ" "$X64_WHEELS"

echo "[4/5] 组装 Windows 包"
WIN_NAME="st-mcp-$VER-windows-x64"
WIN_STAGE="$STAGE/$WIN_NAME"
cp -a "$WIN_BUNDLE" "$WIN_STAGE"
# 厂商闭源驱动不进开源发布包（环境里可能残留，必须先清掉）。
rm -rf "$WIN_STAGE/env/STPython-doc" \
       "$WIN_STAGE/env/Lib/site-packages/STPython" \
       "$WIN_STAGE/env/Lib/site-packages"/stpython-*.dist-info \
       "$WIN_STAGE/env/Lib/site-packages"/STPython-*.dist-info
find "$WIN_STAGE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
# 运行环境里可能装着旧版 wheel，强制换成本次发布的版本。
"$WIN_STAGE/env/python.exe" -m pip install --no-index --no-deps --force-reinstall "$(u "$WHEEL")" >/dev/null
"$WIN_STAGE/env/python.exe" -c "import st_mcp, mcp; print(\"windows env wheel ok\")"
cp -a "$STAGE/src" "$WIN_STAGE/source"
mkdir -p "$WIN_STAGE/dist"
cp -p "$WHEEL" "$WIN_STAGE/dist/"
sed "s/{VER}/$VER/g" "$WIN_TEMPLATE" > "$WIN_STAGE/RELEASE-README.md"
for f in source/src dist/st_mcp-$VER-py3-none-any.whl RELEASE-README.md env/python.exe; do
    [ -e "$WIN_STAGE/$f" ] || { echo "Windows 包缺少 $f" >&2; exit 1; }
done
if [ -e "$WIN_STAGE/env/STPython-doc" ]; then
    echo "Windows 包残留 STPython-doc" >&2
    exit 1
fi
rm -f "$OUT/$WIN_NAME.zip"
if [ -n "${SEVENZIP:-}" ] && [ -x "$SEVENZIP" ]; then
    ( cd "$STAGE" && "$SEVENZIP" a -tzip -mx=5 -mcu=on "$OUT/$WIN_NAME.zip" "$WIN_NAME" >/dev/null )
else
    ( cd "$STAGE" && zip -qr "$OUT/$WIN_NAME.zip" "$WIN_NAME" )
fi

echo "[5/5] 源码包与校验和"
git -C "$ROOT" archive --format=tar.gz --prefix="st-mcp-$VER/" \
    -o "$OUT/st-mcp-$VER-source.tar.gz" HEAD
cp -p "$WHEEL" "$OUT/"
( cd "$OUT" && LC_ALL=C sha256sum "st-mcp-$VER-"*.tar.gz "st-mcp-$VER-"*.zip "st_mcp-$VER-"*.whl > SHA256SUMS )

echo "完成，产物在 $OUT："
ls -l "$OUT"
