# ST-MCP：神通数据库（ShenTong / Oscar）的 MCP 服务端

用自然语言查神通库。跑一个 Docker 容器，把数据库暴露成 10 个 MCP 工具，
Qoder / Claude Desktop 等客户端填一个 URL 就能连。

    list_schemas · list_objects · get_object_details · execute_sql · get_performance_metrics
    explain_query · analyze_db_health · get_top_queries · analyze_workload_indexes · analyze_query_indexes

为**完全断网**的环境设计：整条链路（装库 → 建镜像 → 起服务 → 自验收 19 项）不访问外网，
也不需要 pip 源。已在麒麟 V10 SP3 / aarch64 的真机上从空机器跑到 `19 PASS / 0 FAIL / 0 SKIP`
并跨机接入过客户端。

> 发布前请先读 [`NOTICE.md`](NOTICE.md)：`src/` 是在厂商交付代码基础上改造的，
> 且本仓库**不含**数据库介质、闭源驱动与 `libaci.so`（要自备，见 `vendor/PUT-FILES-HERE.md`）。


## 快速开始

**1) 准备二进制**（联网机器上做，或按 `vendor/PUT-FILES-HERE.md` 手工放）

```sh
git clone <本仓库> st-mcp && cd st-mcp
sh tools/fetch-offline-deps.sh          # 开源轮子 + 可选的基础镜像归档
# 再手工放：wheels/STPython-*-cp311-cp311-linux_aarch64.whl、aci/libaci.so
```

**2) 填口令**（唯一必须手工输入的信息）

```sh
cp secrets/st-mcp.env.example secrets/st-mcp.env
vi secrets/st-mcp.env                   # 只改 ST_PASSWORD= 这一行
chmod 600 secrets/st-mcp.env
```

**3) 部署**

```sh
sh install-all.sh
```

期望最后三行：

```
===== 验收汇总：19 PASS / 0 FAIL / 0 SKIP =====
[..:..:..] 部署完成：实例 主 的 MCP 端点 http://127.0.0.1:8100/mcp
[..:..:..] 连的库：SYSDBA@127.0.0.1:2003/OSRDB
```

**4) 客户端填 URL**

```json
{ "mcpServers": { "shentong": { "url": "http://<服务器IP>:8100/mcp" } } }
```

验证服务端真能查库（纯 curl，不依赖任何 MCP 客户端）：

```sh
sh tools/curl-mcp-probe.sh http://127.0.0.1:8100/mcp
# 判据：第 4 步返回里有 "isError":false 和版本行
```


## 默认配置连的是哪个库（先看清，别改错文件）

`deploy.conf` 出厂默认 = **在这台机器上现装一个神通库并连它**
（`ST_HOST=127.0.0.1`、`ST_PORT=2003`、`ST_DB=OSRDB`、`ST_USER=SYSDBA`、
`INSTALL_SHENTONG=yes`、`HOST_PORT=8100`、`TRANSPORT=streamable-http`、`MCP_PATH=/mcp`、
`ACCESS_MODE=unrestricted`）。

| 场景 | 要做什么 | 改哪几行 |
|---|---|---|
| A 本机装库并连它 | 什么都不改，直接 `sh install-all.sh` | — |
| B 连另一台已装好的库 | 不装库，只当网关 | `ST_HOST=<库机IP>`（+ 需要时 `ST_PORT/ST_DB/ST_USER`）、`INSTALL_SHENTONG=no` |
| C 一台机器连多个库 | 首选动态连接（一个容器即可）；需要独立 token/实例隔离时再一库一容器 | 动态：`ST_DYNAMIC_ENABLED=yes` + `ST_DYNAMIC_ALLOW`；多实例：`sh scripts/new-instance.sh erp <库IP>` |

场景 B 的两个坑：`ST_HOST` 填成 `127.0.0.1` 会被入口脚本改写成 `172.17.0.1`（于是去连本机库，
报 `connection refused`）；`INSTALL_SHENTONG` 忘了改 `no` 会在这台机器上白装一个库。
改完 `deploy.conf` 必须重跑 `sh install-all.sh` 才生效（幂等，会重建镜像并重启容器）。


## 动态连接：一个实例连多个库

客户端在请求头或 URL 里带目标库的 IP/端口/账号，同一个进程就按请求切换数据库：

```bash
# 分字段头
-H 'X-ST-DB-Host: 10.0.0.21' -H 'X-ST-DB-Port: 2003' \
-H 'X-ST-DB-User: APP' -H 'X-ST-DB-Password: secret' -H 'X-ST-DB-Name: OSRDB'

# 单头（口令含中文时必须用这个，HTTP 头值只能是 latin-1）
-H 'X-ST-DB: base64url({"host":"10.0.0.21","port":2003,"user":"APP","password":"口令","database":"OSRDB"})'

# URL
http://服务器:8100/mcp?st_host=10.0.0.21&st_port=2003&st_user=APP&st_password=secret&st_db=OSRDB
```

默认**白名单**只放行 `127.0.0.1:2003`；加 IP/CIDR 到 `ST_DYNAMIC_ALLOW` 才放行，
端口用 `ST_DYNAMIC_ALLOW_PORTS`。不带目标、不带 token 的请求在 `ALLOW_DEFAULT=no`（默认）下返回 401。
租户 token 的优先级高于动态目标。完整规则、状态码、容器内 `127.0.0.1` 重映射和连接池说明见
[`docs/07-动态连接.md`](docs/07-动态连接.md)。

真机探针（口令只从 stdin/$ST_PASSWORD 读，不进 argv）：

```sh
ST_PASSWORD='...' python3 scripts/probe-dynamic.py --base http://127.0.0.1:8100 \
    --host 127.0.0.1 --user SYSDBA --db OSRDB
```


## 协议与状态码（接客户端最容易踩的一段）

服务端两种传输二选一，一个容器一次只讲一种：

| 现象 | 容器实际在跑的 | 结论 |
|---|---|---|
| `POST /mcp` → 200 | streamable-http | 正常（默认） |
| `GET /mcp` → **406** | streamable-http | **正常**，只收 POST，别用浏览器探活 |
| `POST /sse` → **405** | sse | 客户端讲的是 streamable-http，URL 换 `/mcp` |
| `/mcp` → 404 | sse | 这台机器没有 `/mcp` 路由，切 `TRANSPORT=streamable-http` |
| `/mcp` → 421 | 旧镜像 | Host 白名单只放行 127.0.0.1：重建镜像（本仓库源码已规避；**本地 127.0.0.1 测不出，跨机第一次就要用真实 IP 测**） |

只会讲 sse 的老客户端：给它是 `TRANSPORT=sse` 的实例，不要改主实例。


## 发行版（Release）

每个 Release 附带 5 个产物，**都不含**神通数据库本体、`STPython` 驱动和 `libaci.so`：

| 产物 | 内容 |
|---|---|
| `st-mcp-<ver>-source.tar.gz` | 完整源码（同 git tag） |
| `st-mcp-<ver>-py3-none-any.whl` | 通用 wheel，可装进任意 Python ≥3.11 |
| `st-mcp-<ver>-linux-arm64.tar.gz` | 源码 + 便携 CPython 3.11 + 开源依赖 + `install.sh`/`run.sh` |
| `st-mcp-<ver>-linux-x86_64.tar.gz` | 同上，x86_64 |
| `st-mcp-<ver>-windows-x64.zip` | 便携 Python 3.13 + 依赖 + 一键启动/验收脚本 + 源码 |

Linux 包解压后 `sh install.sh && sh run.sh`；Windows 包解压后双击 `一键启动.bat`。
没有厂商驱动时服务仍可启动并完成 MCP 握手、动态连接校验，只是不能执行真实 SQL。

发布前的本机实测（Release v0.1.0 对应的资产，均在离线条件下安装）：

| 平台 | 环境 | 结果 |
|---|---|---|
| linux-arm64 | 麒麟 V10（glibc 2.28，ARM64） | `install.sh` 离线安装成功；26 个单元测试全过；`initialize` 判据 401（无目标）/200（header）/200（单头 base64url）/403（白名单外） |
| linux-x86_64 | Ubuntu（WSL1，x86_64） | `install.sh` 离线安装成功；26 个单元测试全过；`initialize` 判据 401/200/200/403/400（缺字段） |
| windows-x64 | Windows 10 x64，无厂商驱动 | 自带 `verify.ps1` 7 PASS / 0 FAIL / 2 SKIP（跳过项为需厂商驱动的真实 SQL）；服务在 8100 正常起停 |

本地重新打包（需要预先准备便携 Python 与各架构轮子目录）：

```sh
VER=0.1.0 ARM64_PY_TGZ=... X64_PY_TGZ=... \
ARM64_WHEELS=... X64_WHEELS=... WIN_BUNDLE=... \
sh tools/build-release.sh
```


## 目录

    install-all.sh              一条命令完成装库/建镜像/起容器/19 项自验收
    deploy.conf                 主实例参数（不含口令）
    docker/                     Dockerfile.offline + entrypoint.sh（含 127.0.0.1 → 172.17.0.1 改写）
    scripts/                    build-image / verify / new-instance / list-instances / common
    shentong/install-shentong.sh 解压介质 → 装 → CREATE DATABASE → 初始化 → 起服务（含小内存保护）
    src/st_mcp/                 Python 源码；src/test/ 16 项无依赖自测
    wheels/ images/ aci/ vendor/ 二进制投递位，仓库不含二进制，各自 README 说明
    tools/                      curl-mcp-probe.sh（握手链验证）、diag-2003.sh（只读诊断）、fetch-offline-deps.sh
    docs/07-动态连接.md          header/URL 指定目标库的完整规则
    windows/                    Windows 一键启动脚本与配置（便携 env 需另行组装）
    RUNBOOK.md                  运维手册（状态/日志/升级/多实例/回退/安全边界）
    PATCH-NOTES.md              改造记录与踩坑（含中文 locale 让整包校验静默失效那一条）


## 已知边界

- 驱动只覆盖厂商发布过的组合（当前 **cp311 + linux_aarch64**）；x86_64 要换该架构的驱动与 ACI。
- Windows：x64 用 `windows/` 下的一键脚本；SQL 依赖神通 Windows 客户端自带的 `ACI.dll`，
  只有协议层（启动、路由、401/403）不需要它。
- **不做任何鉴权**：监听 `0.0.0.0:8100`，能连到这个端口的人都能用那 10 个工具查这块库。
  内网部署的取舍，需要收窄请用防火墙按源地址放行，或用 `ACCESS_MODE=restricted` 走只读。
- 数据库口令只在 `secrets/*.env`（600），不进配置文件、命令行和日志；含 `@ : / # % ! $ 空格 中文`
  的口令按原样使用，不需要转义。
- 厂商介质自带**试用 license**（版本串 `license invalid after 90 days`），到期后库拒起。


## 开发 / 贡献

```sh
PYTHONPATH=src sh -c 'for t in src/test/test_*.py; do python "$t"; done'   # 16 项自测
sh -n install-all.sh scripts/*.sh docker/entrypoint.sh                     # POSIX sh + bash 双跑
sh .secrets-scan.sh                                                        # 提交前哨兵
```

脚本必须能在 `/bin/sh`（dash/ash）下跑：不用进程替换、不用 bash 数组。
判据里凡解析外部命令输出的英文关键字都要钉 `LC_ALL=C`（麒麟中文环境会把 `OK/FAILED` 译成
`确定/失败`，整包校验因此静默失效过一次）。

MIT 许可，见 `LICENSE` 与 `NOTICE.md`。
