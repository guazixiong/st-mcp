# ST-MCP Linux 发布包（{PLATFORM}）

这是 ST-MCP 的免安装运行包：源码、通用 wheel、{PLATFORM} 便携 CPython 3.11
压缩包和全部开源依赖都在包里，不访问外网。

> 本包**不含**神通数据库本体、厂商闭源驱动 STPython 和 `libaci.so`。
> 没有它们服务也能启动、能完成 MCP 握手和动态连接校验；
> 真正执行 SQL 前，请按 `source/vendor/PUT-FILES-HERE.md` 放置厂商驱动。

## 快速开始

```sh
tar -xzf st-mcp-0.1.0-{PLATFORM}.tar.gz
cd st-mcp-0.1.0-{PLATFORM}
sh install.sh          # 把依赖装进随包 Python，不联网
sh run.sh              # 默认 0.0.0.0:8100/mcp
```

自检：

```sh
curl -s http://127.0.0.1:8100/healthz
# {"ok": true, "tenants": 0, "dynamic": true}
```

动态白名单默认只放行 `127.0.0.1:2003`。要让客户端连其它库：

```sh
ST_DYNAMIC_ALLOW='*' ST_DYNAMIC_ALLOW_PORTS='*' sh run.sh
```

## 目录

| 路径 | 内容 |
|---|---|
| `source/` | 完整源码（`src/`、部署脚本、文档） |
| `runtime/` | 便携 CPython 3.11（{PLATFORM}）压缩包，首次 `install.sh` 自动解压 |
| `wheels/` | 开源依赖轮子 + `requirements.txt` |
| `dist/` | `st_mcp-0.1.0-py3-none-any.whl` |
| `install.sh` / `run.sh` | 离线安装 / 启动 |

## 非 Docker 方式

本包用便携 Python 直接运行，适合没有 Docker 的机器。需要 Docker 的完整部署
（装库、建镜像、19 项自验收）见 `source/README.md` 和 `source/RUNBOOK.md`。
