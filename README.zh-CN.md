# ST-MCP

**神通数据库（ShenTong / OSCAR）的 MCP 服务端。** 它把神通库暴露成 10 个
Model Context Protocol 工具，Qoder、Claude Desktop 或任意 MCP SDK 通过一个 HTTP
端点即可浏览模式、执行 SQL、读取性能数据。

[English](README.md) | 简体中文

- 一个 `streamable-http` 端点（`POST /mcp`），也支持旧的 `sse` / `stdio`。
- **动态连接**：每次请求用请求头或 URL 参数指定目标库，一个进程可服务多台库。
- 可选的租户注册表：Bearer token 对应固定的数据库账号。
- 提供 Linux arm64、Linux x86_64、Windows x64 的离线发布包。

```
list_schemas · list_objects · get_object_details · execute_sql
get_performance_metrics · explain_query · analyze_db_health · get_top_queries
analyze_workload_indexes · analyze_query_indexes
```

## 运行要求

- 可访问的神通 / OSCAR 服务器（默认 TCP `2003` 端口）。
- **真实 SQL 需要厂商驱动**：闭源的 `STPython` 与 `libaci.so`（Linux）/
  `ACI.dll`（Windows）**不在本仓库中**。没有它们服务也能启动、能完成 MCP 握手，
  但 SQL 工具会返回错误。见 [`vendor/PUT-FILES-HERE.md`](vendor/PUT-FILES-HERE.md)。
- 用 wheel 安装需要 Python ≥ 3.11；Linux 发布包自带便携 CPython 3.11，Windows 包自带
  便携 CPython 3.13，都不依赖系统 Python。
- Linux glibc ≥ 2.28（麒麟 V10、RHEL 8、Debian 10 或更新）或 Windows x64。
  Docker 可选。

已发布的 `STPython` wheel 面向 Linux aarch64 上的 CPython 3.11；其它平台需要
厂商提供的对应驱动。

## 从发布包快速开始

每个 Release 提供 5 个产物，外加 `SHA256SUMS`：

| 产物 | 内容 |
|---|---|
| `st-mcp-<ver>-source.tar.gz` | 对应 tag 的完整源码。 |
| `st_mcp-<ver>-py3-none-any.whl` | 通用 wheel，适用于任意 Python ≥ 3.11。 |
| `st-mcp-<ver>-linux-arm64.tar.gz` | 源码 + 便携 CPython + 依赖轮子 + `install.sh` / `run.sh`。 |
| `st-mcp-<ver>-linux-x86_64.tar.gz` | 同上，x86_64。 |
| `st-mcp-<ver>-windows-x64.zip` | 便携 CPython 3.13（依赖已装好）+ 启动/验收脚本 + 源码。 |

### Linux 包（不需要 Docker）

```sh
tar -xzf st-mcp-<ver>-linux-x86_64.tar.gz
cd st-mcp-<ver>-linux-x86_64
sh install.sh
sh run.sh
```

`install.sh` 把随包 CPython 解压到 `./python`，离线安装开源依赖，不改系统 Python。

`run.sh` 在 `0.0.0.0:8100/mcp` 启动服务，动态连接已开启，但白名单只放行
`127.0.0.1:2003`。要接受其它目标：

```sh
ST_DYNAMIC_ALLOW='10.0.0.0/24' ST_DYNAMIC_ALLOW_PORTS=2003 sh run.sh
# 或在可信网络内全部放行：
ST_DYNAMIC_ALLOW='*' ST_DYNAMIC_ALLOW_PORTS='*' sh run.sh
```

探活：

```sh
curl -s http://127.0.0.1:8100/healthz
# {"ok": true, "tenants": 0, "dynamic": true}
```

### Windows 包

解压后双击 `一键启动.bat`（或运行 `powershell -File scripts\start-server.ps1`）。
脚本读取 `config\st-mcp.conf`，在前台启动 `0.0.0.0:8100/mcp` 并打印客户端地址。
`验收检查.bat` 可自检（没有厂商驱动时为 7 PASS / 0 FAIL / 2 SKIP）。要连其它
数据库主机，把地址加入 `config\st-mcp.conf` 的 `ST_DYNAMIC_ALLOW`。

### Wheel

```sh
python -m pip install st_mcp-<ver>-py3-none-any.whl
ST_DYNAMIC_ENABLED=yes ST_DYNAMIC_ALLOW=127.0.0.1 \
  st-mcp --transport streamable-http --sse-host 0.0.0.0 --sse-port 8100 --mcp-path /mcp
```

如果不使用动态目标、只连固定库，传 `--host`、`--port`、`--user`、`--database`，
口令放 `ST_PASSWORD`（写在 `--password` 里会出现在进程列表）。

## 客户端配置

把端点填进客户端。多数 MCP 客户端支持自定义请求头：

```json
{
  "mcpServers": {
    "shentong": {
      "url": "http://db-host:8100/mcp",
      "headers": {
        "X-ST-DB-Host": "10.0.0.21",
        "X-ST-DB-Port": "2003",
        "X-ST-DB-User": "APP",
        "X-ST-DB-Password": "secret",
        "X-ST-DB-Name": "OSRDB"
      }
    }
  }
}
```

服务端以固定库启动、且关闭动态连接时，只填 URL 即可：

```json
{ "mcpServers": { "shentong": { "url": "http://db-host:8100/mcp" } } }
```

不能设置请求头的客户端，可以把目标放进 URL：

```text
http://db-host:8100/mcp?st_host=10.0.0.21&st_port=2003&st_user=APP&st_password=secret&st_db=OSRDB
```

## 动态连接

请求按以下顺序选库（先命中者生效）：

1. **租户 token** —— 注册表里的 `/mcp/<token>`、`Authorization: Bearer <token>` 或
   `X-ST-Token: <token>`。
2. **请求目标** —— 先看 `X-ST-DB` 单头，再看 `X-ST-DB-*` 分字段头，最后看 URL 查询。

开启动态连接时，两者都不带的请求会被拒绝（`401`），不会回落到服务端自己的库；
关闭动态连接时，服务端始终使用自己的固定连接。

目标字段：

| 字段 | 请求头 | URL 查询 | 必填 | 默认 |
|---|---|---|---|---|
| 主机 | `X-ST-DB-Host` | `st_host` | 是 | — |
| 端口 | `X-ST-DB-Port` | `st_port` | 否 | `ST_DYNAMIC_DEFAULT_PORT`（2003） |
| 用户 | `X-ST-DB-User` | `st_user` | 是 | — |
| 口令 | `X-ST-DB-Password` | `st_password` | 是 | — |
| 库名 | `X-ST-DB-Name` | `st_db` | 否 | `ST_DYNAMIC_DEFAULT_DB`（OSRDB） |

客户端只能加一个自定义头时，用单值形式：

```text
X-ST-DB: {"host":"10.0.0.21","port":2003,"user":"APP","password":"secret","database":"OSRDB"}
X-ST-DB: <同一 JSON 的 base64url>              # 口令含非 latin-1 字符时必须用这个
?st=<base64url JSON>
```

`X-ST-DB` 优先于分字段头，请求头优先于 URL 查询；不同来源不会混合拼接。
凭据请求头（`X-ST-DB`、`X-ST-DB-*`）在进入 MCP 层之前会被移除；URL 参数不会被移除，
它会留在请求 URL 里，因此优先用请求头，并把端点放在可信网络中。服务端关闭了 HTTP
访问日志，避免把查询串写进访问日志。

目标必须同时通过两个白名单：

- `ST_DYNAMIC_ALLOW` —— 逗号分隔的精确主机、CIDR 或 `*.后缀`；`*` 全部放行，
  留空全部拒绝。
- `ST_DYNAMIC_ALLOW_PORTS` —— 逗号分隔的端口，或 `*`。

动态请求的响应码：

| 情况 | HTTP |
|---|---|
| 目标合法（或会话已绑定） | `200` |
| 没有目标、没有 token | `401` |
| 主机或端口不在白名单 | `403` |
| 字段缺失、端口非法、JSON/base64 解析失败 | `400` |
| 目标合法但数据库拒绝连接（口令错、库未启动） | `200`，工具结果里带 `Error:` |

每个不同目标（主机、端口、用户、口令、库名）使用独立连接池；
`ST_MAX_TARGETS` 限制池数量（默认 16）。

## 配置

### 服务端

| 变量 / 参数 | 默认 | 说明 |
|---|---|---|
| `--transport` | `sse`（发布包为 `streamable-http`） | `streamable-http`、`sse` 或 `stdio`。 |
| `--sse-host`（包装脚本用 `SSE_HOST`） | `localhost`（发布包为 `0.0.0.0`） | 监听地址。 |
| `--sse-port`（包装脚本用 `SSE_PORT`） | `8000`（发布包为 `8100`） | 监听端口。 |
| `--mcp-path`（包装脚本用 `MCP_PATH`） | `/mcp` | `streamable-http` 端点路径。 |
| `--log-level`（包装脚本用 `LOG_LEVEL`） | `INFO` | 日志级别。 |
| `--access-mode` | `unrestricted` | `restricted` 拒绝写 SQL。 |
| `ST_DYNAMIC_ENABLED` | 关闭 | 启用按请求指定目标。 |
| `ST_DYNAMIC_ALLOW` | 空 | 目标主机白名单。 |
| `ST_DYNAMIC_ALLOW_PORTS` | `2003` | 目标端口白名单。 |
| `ST_DYNAMIC_DEFAULT_PORT` | `2003` | 请求未给端口时的默认值。 |
| `ST_DYNAMIC_DEFAULT_DB` | `OSRDB` | 请求未给库名时的默认值。 |
| `ST_DYNAMIC_ACCESS_MODE` | 跟随 `--access-mode` | 动态目标的 SQL 权限。 |
| `ST_DYNAMIC_ALLOW_DEFAULT` | `no` | 启动时是否也打开服务端自己的连接；开启动态连接时它不会让无 token/目标的请求通过。 |
| `ST_MAX_TARGETS` | `16` | 连接池上限。 |
| `ST_TENANT_REGISTRY` / `--tenant-registry` | 未设置 | 租户注册表 JSON。 |
| `ST_ALLOW_DEFAULT` | `0` | 设为 `1` 时，无 token 请求按 `ST_DEFAULT_TENANT` 处理；必须有租户注册表。 |
| `ST_DEFAULT_TENANT` | 未设置 | 无 token 请求使用的注册表租户。 |

`SSE_HOST`、`SSE_PORT`、`MCP_PATH`、`LOG_LEVEL` 由发布包的包装脚本
（`run.sh`、`docker/entrypoint.sh`、`scripts\start-server.ps1`）读取后转成上面的参数；
Python 服务端只认这些命令行参数。

### Docker 部署

`deploy.conf` 保存容器参数，`secrets/st-mcp.env` 保存口令（权限 `600`）。
默认配置会在本机安装一个神通库并连它；连已有服务器时改 `ST_HOST`、`ST_PORT`、
`ST_USER`、`ST_DB`，并把 `INSTALL_SHENTONG` 设为 `no`。

```sh
cp secrets/st-mcp.env.example secrets/st-mcp.env
vi secrets/st-mcp.env                    # 只填 ST_PASSWORD
chmod 600 secrets/st-mcp.env
sh install-all.sh                        # 建镜像、起容器、跑自验收
sh tools/curl-mcp-probe.sh http://127.0.0.1:8100/mcp
```

容易踩的几个点：

- 改完 `deploy.conf` 必须重跑 `install-all.sh`（幂等）。
- 容器内的 `127.0.0.1` 指容器自己；入口脚本会把它改写成 `ST_HOST_GATEWAY`
  （默认 `172.17.0.1`），以便连宿主机上的库。
- 宿主机上的库必须监听 `0.0.0.0:2003`，只监听 `127.0.0.1:2003` 时容器连不上。

多实例与排障见 [`RUNBOOK.md`](RUNBOOK.md) 和
[`docs/07-动态连接.md`](docs/07-动态连接.md)。

## 协议说明

| 请求 | 结果 | 含义 |
|---|---|---|
| `POST /mcp` | `200` | `streamable-http` 正常握手。 |
| `GET /mcp` | `401` / `406` | 不带 token/目标时 `401`；带合法 token/目标时传输层返回 `406`（只接受 POST）。 |
| `POST /sse` | `405` | 服务端在跑 `sse`，应使用 `/sse` 端点。 |
| `/mcp` | `404` | 服务端在跑 `sse` 或路径不同。 |
| `/mcp` | `421` | Host 头被拒绝，请使用当前版本。 |

## 安全

- 关闭动态连接、也没有配置租户注册表时，本服务**不做鉴权**：能连到端口的人都能使用
  这些工具。请用防火墙限制来源，或配置租户注册表让调用方必须携带 token。
- 开启动态连接后，每个请求必须带目标或 token，但目标本身就是数据库凭据：
  知道 `ST_DYNAMIC_ALLOW` 白名单内任一主机账号的人都能使用。
- 本版本的租户隔离只是路由机制，隔离强度取决于数据库账号权限。
- 动态目标允许调用方在白名单内选择数据库。`ST_DYNAMIC_ALLOW` 应尽量收窄，
  不要把这个端口暴露到公网。
- 服务端不记录口令。但口令和 token 会出现在请求头或 URL 中，建议使用 HTTPS
  或可信网络。

## 已知边界

- 本仓库不含数据库介质、`STPython` wheel 和 `libaci.so`。
- 厂商为 Linux aarch64 发布的驱动只支持 CPython 3.11。
- Windows 上执行 SQL 需要神通 Windows 客户端（`ACI.dll`）。
- 自备的神通介质带 90 天试用 license。

## 开发

```sh
PYTHONPATH=src sh -c 'for t in src/test/test_*.py; do python "$t"; done'
sh -n install-all.sh scripts/*.sh docker/entrypoint.sh
sh .secrets-scan.sh
```

Shell 脚本必须能在 POSIX `/bin/sh`（dash/ash）下运行：不用进程替换、不用 bash 数组。
解析外部命令英文关键字时必须钉 `LC_ALL=C`。

本地重新打包（需要便携 Python 压缩包与各架构轮子目录）：

```sh
VER=0.1.1 ARM64_PY_TGZ=... X64_PY_TGZ=... \
ARM64_WHEELS=... X64_WHEELS=... WIN_BUNDLE=... \
sh tools/build-release.sh
```

## 许可

MIT，见 [`LICENSE`](LICENSE)。`src/` 基于厂商交付代码改造，来源与边界见
[`NOTICE.md`](NOTICE.md)。
