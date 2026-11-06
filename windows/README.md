# Windows 一键启动包（源码部分）

这里是在 Windows 上运行 ST-MCP 的脚本与配置。**便携 Python 运行时（约 250 MB）不进 git**，
组装发布包时从已有的 Windows 离线包复制 `env\` 目录进来即可。

## 目录

| 文件 | 作用 |
|---|---|
| `config\st-mcp.conf` | 唯一需要现场修改的文件：动态白名单、默认库、监听端口 |
| `scripts\st-mcp-common.ps1` | 读配置、导出环境变量、探测 `ACI.dll` |
| `scripts\start-server.ps1` | 前台启动，先打印端点与示例，再跑服务 |
| `scripts\verify.ps1` | 一键验收：环境 / 驱动 / 配置 / 启动 / 协议 / 数据库 |
| `scripts\probe.py` | 纯标准库的 MCP 协议探针（被 verify.ps1 调用） |
| `一键启动.bat` | 双击启动（`chcp 65001` + 调 start-server.ps1） |
| `验收检查.bat` | 双击验收 |

## 组装完整发布包

```powershell
# 在一个已经有 env\ 的物理目录里组装（例如从旧版 Windows 离线包复制）
$pkg = 'C:\build\st-mcp-win64-20261102'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
Copy-Item -Recurse .\windows\* $pkg
Copy-Item -Recurse 'D:\path\to\old-bundle\env' (Join-Path $pkg 'env')
Copy-Item (Join-Path $pkg '..\README.md') $pkg   # 或使用交付包里的 START-HERE.md
```

运行时要求：Python 3.13 x64，已安装本仓库的 `st_mcp` wheel 与 `STPython`
（`env\Scripts\st-mcp.exe` 存在即满足）。升级代码后重新安装 wheel：

```powershell
.\env\python.exe -m pip install --no-index --force-reinstall wheels\st_mcp-0.1.0-py3-none-any.whl
```

## 一键启动

双击 `一键启动.bat`。默认监听 `0.0.0.0:8100`，端点 `http://<本机IP>:8100/mcp`。
窗口保持打开，按 `Ctrl+C` 停止。

## 动态目标怎么带

见仓库 [`docs/07-动态连接.md`](../docs/07-动态连接.md)。最短版本：

```text
请求头  X-ST-DB-Host / X-ST-DB-Port / X-ST-DB-User / X-ST-DB-Password / X-ST-DB-Name
单头    X-ST-DB: base64url({"host":...})
URL     http://IP:8100/mcp?st_host=...&st_port=2003&st_user=...&st_password=...&st_db=OSRDB
```

口令含中文时**不能**用 `X-ST-DB-Password`（HTTP 头只接受 latin-1），要用
`X-ST-DB` JSON/base64 头或 URL percent-encode。

## 神通客户端（`ACI.dll`）

STPython 是闭源扩展，导入它需要神通 Windows 客户端自带的 `ACI.dll` 等依赖。
`start-server.ps1` / `verify.ps1` 会按以下顺序找：

1. `config\st-mcp.conf` 的 `ST_BIN_DIR`；
2. `C:\ShentongDB\bin`、`D:\ShentongDB\bin`、`C:\OSCAR\bin`、
   `C:\Program Files\ShentongDB\bin`、`C:\Program Files (x86)\ShentongDB\bin`；
3. 当前 `PATH`。

找到后会把该目录加到 `PATH` 前面。**服务本身不依赖它也能启动**，只是执行 SQL 会返回
驱动加载失败；装上客户端后重启服务即可。

## 实测记录

| 环境 | 结果 | 说明 |
|---|---|---|
| 麒麟 V10 SP3 aarch64（QEMU）+ 神通 7.0.21 | **14 PASS / 0 FAIL** | 容器内真实建连：分头 / blob / URL 三种目标、两个不同账号分别查询、会话绑定、白名单 403、默认 401、错口令返回工具错误 |
| Windows 10 x64 19045 + 便携 Python 3.13.13 | **7 PASS / 0 FAIL / 2 SKIP** | 启动、healthz、401、403、分头、blob、URL 均通过；两项 SKIP 是机器上没有神通客户端，`STPython` 无法导入，因此未执行 SQL |
