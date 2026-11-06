# aci/ —— ACI 客户端共享库投递位

`STPython` 是编译扩展，运行期要 `dlopen` 厂商的 `libaci.so`（Windows 上对应 `ACI.dll`）。
镜像里通过 `LD_LIBRARY_PATH=/opt/st-mcp/aci` 指向本目录，`docker/Dockerfile.offline` 整目录 `COPY aci/`，
**所以本目录必须存在**（仓库里只放这份说明）。

本仓库**不提供 `libaci.so`**：它是厂商闭源二进制，随数据库介质分发。获取方式：

```sh
# 从厂商 aarch64 介质解压后的目录里取（介质自备，见 ../vendor/PUT-FILES-HERE.md）
cp <介质解包目录>/drivers/aci/arm64/libaci.so aci/libaci.so
```

或者直接从**已装好的库**上取现场那一份（推荐，版本天然匹配）：

```sh
cp $SZ_OSCAR_HOME/drivers/aci/arm64/libaci.so aci/libaci.so
IMAGE_MODE=build sh install-all.sh
```

三条硬约束：

1. **ACI 版本必须与被连的数据库一致**，否则握手失败。连的是远端 V7.0.5 就取那台的 `libaci.so`。
2. 架构与 Python 必须同为 **64 位 + cp311**；换 x86_64 要取该架构介质里对应的那份。
3. `ldd libaci.so` 只需要 `libpthread / libstdc++ / libdl / libgcc_s / libc / libm`，
   Debian slim 基础镜像自带，不需要额外装包。

就位后构建脚本会打印 `将打入 ACI：aci/libaci.so（N 字节）`，并跑一次 import 自检
（`IMPORT_OK`）；缺失时是警告而不是静默失败。
