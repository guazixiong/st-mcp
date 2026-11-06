# ST-MCP Windows 发布包（x64）

解压后即可运行：便携 Python 3.13、依赖和 st-mcp 全部在 `env\` 里，不访问外网。

> 本包**不含**神通数据库本体和厂商闭源驱动（`STPython`、`ACI.dll`）。
> 没有它们服务能启动、能完成 MCP 握手与动态连接校验；执行 SQL 前请安装
> 神通 Windows 客户端，或在 `config\st-mcp.conf` 的 `ST_BIN_DIR=` 指向其 `bin` 目录。

## 快速开始

1. 解压 `st-mcp-0.1.0-windows-x64.zip`
2. 双击 `一键启动.bat`（默认 `http://0.0.0.0:8100/mcp`）
3. 浏览器打开 `http://127.0.0.1:8100/healthz`，应返回
   `{"ok": true, "tenants": 0, "dynamic": true}`

自检：双击 `验收检查.bat`。没装神通客户端时预期
`7 PASS / 0 FAIL / 2 SKIP`；装好后预期 `9 PASS / 0 FAIL / 0 SKIP`。

## 客户端怎么填

URL 固定为 `http://<服务器IP>:8100/mcp`，目标库写在请求头里：

```json
{
  "X-ST-DB-Host": "10.0.0.21",
  "X-ST-DB-Port": "2003",
  "X-ST-DB-User": "SYSDBA",
  "X-ST-DB-Password": "******",
  "X-ST-DB-Name": "OSRDB"
}
```

口令含中文，或客户端只支持一个自定义头时，改用
`X-ST-DB: base64url({"host":...,"port":...,"user":...,"password":...,"database":...})`。
不要加 `Authorization`。

白名单默认只放行 `127.0.0.1:2003`；连别的库请改 `config\st-mcp.conf` 的
`ST_DYNAMIC_ALLOW` / `ST_DYNAMIC_ALLOW_PORTS` 后重启。

## 目录

| 路径 | 内容 |
|---|---|
| `env\` | 便携 Python 3.13 + 已安装依赖 |
| `config\st-mcp.conf` | 运行参数 |
| `scripts\` | 启动、验收、探针 |
| `source\` | 完整源码 |
| `dist\` | `st_mcp-0.1.0-py3-none-any.whl` |
| `一键启动.bat` / `验收检查.bat` | 入口 |
