# ST-MCP

**MCP server for ShenTong (OSCAR) databases.** It exposes a ShenTong database as
10 Model Context Protocol tools, so clients such as Qoder, Claude Desktop or any
MCP SDK can inspect schemas, run SQL and read performance data over one HTTP
endpoint.

English | [简体中文](README.zh-CN.md)

- One `streamable-http` endpoint (`POST /mcp`) or legacy `sse` / `stdio`.
- **Dynamic connections**: each request chooses the target database with headers
  or URL parameters — one process can serve many databases.
- Optional tenant registry: a bearer token maps to a fixed database account.
- Offline release bundles for Linux arm64, Linux x86_64 and Windows x64.

```
list_schemas · list_objects · get_object_details · execute_sql
get_performance_metrics · explain_query · analyze_db_health · get_top_queries
analyze_workload_indexes · analyze_query_indexes
```

## Requirements

- A reachable ShenTong / OSCAR server (TCP port `2003` by default).
- **Vendor driver for real SQL**: the closed-source `STPython` package and
  `libaci.so` (Linux) / `ACI.dll` (Windows) are **not** distributed here. Without
  them the server still starts and completes MCP handshakes, but SQL tools return
  an error. See [`vendor/PUT-FILES-HERE.md`](vendor/PUT-FILES-HERE.md).
- Python ≥ 3.11 if you install the wheel. The Linux bundles include a portable
  CPython 3.11 and the Windows bundle a portable CPython 3.13, so neither needs a
  system Python.
- Linux glibc ≥ 2.28 (Kylin V10, RHEL 8, Debian 10 or newer) or Windows x64.
  Docker is optional.

The published `STPython` wheel targets CPython 3.11 on Linux aarch64. Other
platforms need a matching driver build from the vendor.

## Quick start from a release

Every release ships five assets plus `SHA256SUMS`:

| Asset | Contents |
|---|---|
| `st-mcp-<ver>-source.tar.gz` | Full source for the tag. |
| `st_mcp-<ver>-py3-none-any.whl` | Universal wheel for any Python ≥ 3.11. |
| `st-mcp-<ver>-linux-arm64.tar.gz` | Source + portable CPython + wheels + `install.sh` / `run.sh`. |
| `st-mcp-<ver>-linux-x86_64.tar.gz` | Same for x86_64. |
| `st-mcp-<ver>-windows-x64.zip` | Portable CPython 3.13 with the dependencies installed + start/verify scripts + source. |

### Linux bundle (no Docker)

```sh
tar -xzf st-mcp-<ver>-linux-x86_64.tar.gz
cd st-mcp-<ver>-linux-x86_64
sh install.sh
sh run.sh
```

`install.sh` unpacks the bundled CPython into `./python` and installs the
open-source dependencies offline; it does not touch the system Python.

`run.sh` starts the server on `0.0.0.0:8100/mcp` with dynamic connections enabled
but restricted to `127.0.0.1:2003`. To accept other targets:

```sh
ST_DYNAMIC_ALLOW='10.0.0.0/24' ST_DYNAMIC_ALLOW_PORTS=2003 sh run.sh
# or allow everything (only inside a trusted network):
ST_DYNAMIC_ALLOW='*' ST_DYNAMIC_ALLOW_PORTS='*' sh run.sh
```

Check that it is alive:

```sh
curl -s http://127.0.0.1:8100/healthz
# {"ok": true, "tenants": 0, "dynamic": true}
```

### Windows bundle

Unzip and double-click `一键启动.bat` (or run `powershell -File scripts\start-server.ps1`).
The script reads `config\st-mcp.conf`, starts `0.0.0.0:8100/mcp` in the foreground
and prints the client URLs. Run `验收检查.bat` for a self-check
(7 PASS / 0 FAIL / 2 SKIP without the vendor driver). To connect other database
hosts, add them to `ST_DYNAMIC_ALLOW` in `config\st-mcp.conf`.

### Wheel

```sh
python -m pip install st_mcp-<ver>-py3-none-any.whl
ST_DYNAMIC_ENABLED=yes ST_DYNAMIC_ALLOW=127.0.0.1 \
  st-mcp --transport streamable-http --sse-host 0.0.0.0 --sse-port 8100 --mcp-path /mcp
```

For a fixed database instead of dynamic targets, pass `--host`, `--port`,
`--user`, `--database` and put the password in `ST_PASSWORD` (a password in
`--password` is visible in the process list).

## Client configuration

Point the client at the endpoint. Most MCP clients accept custom headers:

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

For a server started with a fixed database and dynamic connections disabled, the
URL alone is enough:

```json
{ "mcpServers": { "shentong": { "url": "http://db-host:8100/mcp" } } }
```

Clients that cannot set headers can put the target in the URL instead:

```text
http://db-host:8100/mcp?st_host=10.0.0.21&st_port=2003&st_user=APP&st_password=secret&st_db=OSRDB
```

## Dynamic connections

A request selects its database in this order (first match wins):

1. **Tenant token** — `/mcp/<token>`, `Authorization: Bearer <token>` or
   `X-ST-Token: <token>` from the tenant registry.
2. **Request target** — `X-ST-DB` blob, then `X-ST-DB-*` fields, then URL query.

While dynamic connections are enabled, a request that carries neither is rejected
with `401`; the server's own connection is not used as a fallback. With dynamic
connections disabled the server always uses its own fixed connection.

Target fields:

| Field | Header | Query (URL) | Required | Default |
|---|---|---|---|---|
| Host | `X-ST-DB-Host` | `st_host` | yes | — |
| Port | `X-ST-DB-Port` | `st_port` | no | `ST_DYNAMIC_DEFAULT_PORT` (2003) |
| User | `X-ST-DB-User` | `st_user` | yes | — |
| Password | `X-ST-DB-Password` | `st_password` | yes | — |
| Database | `X-ST-DB-Name` | `st_db` | no | `ST_DYNAMIC_DEFAULT_DB` (OSRDB) |

Single-value forms, useful when a client exposes only one custom header:

```text
X-ST-DB: {"host":"10.0.0.21","port":2003,"user":"APP","password":"secret","database":"OSRDB"}
X-ST-DB: <base64url of the same JSON>          # use this when the password is not latin-1
?st=<base64url JSON>
```

`X-ST-DB` wins over the individual headers; headers win over the query string.
Sources are never merged. Credential headers (`X-ST-DB`, `X-ST-DB-*`) are removed
before the MCP layer sees the request. URL parameters are not removed — they stay
in the request URL — so prefer headers and keep the endpoint behind a trusted
network. HTTP access logging is disabled so the query string is not written to the
access log.

Every target must pass both lists:

- `ST_DYNAMIC_ALLOW` — comma-separated exact hosts, CIDR ranges or `*.suffix`;
  `*` allows all, empty denies all.
- `ST_DYNAMIC_ALLOW_PORTS` — comma-separated ports or `*`.

Response codes for dynamic requests:

| Situation | HTTP |
|---|---|
| Valid target (or session already bound) | `200` |
| No target and no token | `401` |
| Host or port not in the allow-list | `403` |
| Missing field, bad port, malformed JSON/base64 | `400` |
| Target valid but the database rejects the connection | `200` + `Error:` in the tool result |

Each distinct target (host, port, user, password, database) gets its own pooled
connection; `ST_MAX_TARGETS` caps the number of pools (default 16).

## Configuration

### Server

| Variable / flag | Default | Meaning |
|---|---|---|
| `--transport` | `sse` (`streamable-http` in bundles) | `streamable-http`, `sse` or `stdio`. |
| `--sse-host` (`SSE_HOST` in wrappers) | `localhost` (`0.0.0.0` in bundles) | Listen address. |
| `--sse-port` (`SSE_PORT` in wrappers) | `8000` (`8100` in bundles) | Listen port. |
| `--mcp-path` (`MCP_PATH` in wrappers) | `/mcp` | Endpoint path for `streamable-http`. |
| `--log-level` (`LOG_LEVEL` in wrappers) | `INFO` | Log level. |
| `--access-mode` | `unrestricted` | `restricted` rejects write SQL. |
| `ST_DYNAMIC_ENABLED` | off | Enable per-request targets. |
| `ST_DYNAMIC_ALLOW` | empty | Target host allow-list. |
| `ST_DYNAMIC_ALLOW_PORTS` | `2003` | Target port allow-list. |
| `ST_DYNAMIC_DEFAULT_PORT` | `2003` | Port when the request omits it. |
| `ST_DYNAMIC_DEFAULT_DB` | `OSRDB` | Database when the request omits it. |
| `ST_DYNAMIC_ACCESS_MODE` | follows `--access-mode` | SQL mode for dynamic targets. |
| `ST_DYNAMIC_ALLOW_DEFAULT` | `no` | Open the server's own connection at startup; it does not accept tokenless requests while dynamic connections are enabled. |
| `ST_MAX_TARGETS` | `16` | Connection-pool cap. |
| `ST_TENANT_REGISTRY` / `--tenant-registry` | unset | Tenant registry JSON. |
| `ST_ALLOW_DEFAULT` | `0` | `1` accepts tokenless requests as `ST_DEFAULT_TENANT`; needs a tenant registry. |
| `ST_DEFAULT_TENANT` | unset | Registry tenant used for tokenless requests. |

`SSE_HOST`, `SSE_PORT`, `MCP_PATH` and `LOG_LEVEL` are read by the bundled
wrappers (`run.sh`, `docker/entrypoint.sh`, `scripts\start-server.ps1`), which pass
them to the flags above; the Python CLI itself reads only the flags.

### Docker deployment

`deploy.conf` holds the container settings, `secrets/st-mcp.env` holds the
password (mode `600`). The default configuration installs a ShenTong database on
the same host and connects to it; to use an existing server set `ST_HOST`,
`ST_PORT`, `ST_USER`, `ST_DB` and `INSTALL_SHENTONG=no`.

```sh
cp secrets/st-mcp.env.example secrets/st-mcp.env
vi secrets/st-mcp.env                    # ST_PASSWORD only
chmod 600 secrets/st-mcp.env
sh install-all.sh                        # build image, start container, run the self-check
sh tools/curl-mcp-probe.sh http://127.0.0.1:8100/mcp
```

Rules that are easy to get wrong:

- Changing `deploy.conf` requires re-running `install-all.sh`; it is idempotent.
- Inside the container, `127.0.0.1` means the container. The entrypoint rewrites
  it to `ST_HOST_GATEWAY` (default `172.17.0.1`) so a database on the host is
  reachable.
- A database on the host must listen on `0.0.0.0:2003`, not `127.0.0.1:2003`.

For multi-instance setups and troubleshooting see [`RUNBOOK.md`](RUNBOOK.md) and
[`docs/07-动态连接.md`](docs/07-动态连接.md) (Chinese; the rules match this README).

## Protocol notes

| Request | Result | Meaning |
|---|---|---|
| `POST /mcp` | `200` | Normal `streamable-http` handshake. |
| `GET /mcp` | `401` / `406` | Without a token or target: `401`. With a valid token/target the transport answers `406` (POST only). |
| `POST /sse` | `405` | The server is running `sse`; use the `/sse` endpoint. |
| `/mcp` | `404` | The server is running `sse` or another path. |
| `/mcp` | `421` | Host header rejected; use a current build. |

## Security

- With dynamic connections disabled and no tenant registry, the server performs
  **no authentication**: anyone who can reach the port can use the tools. Restrict
  access with a firewall, or configure a tenant registry so callers need a token.
- With dynamic connections enabled every request must carry a target or token, but
  the target itself is a database credential: anyone who knows an account for a
  host inside `ST_DYNAMIC_ALLOW` can use it.
- Tenant isolation in this edition is only a routing mechanism. The caller must
  still be authorized by the database account privileges.
- Dynamic targets let a caller choose any database allowed by the allow-list.
  Keep `ST_DYNAMIC_ALLOW` as narrow as possible and never expose the port to the
  internet.
- The server does not log passwords. Still, prefer HTTPS or a trusted network:
  passwords and tokens travel in headers or URLs.

## Limitations

- No vendor database media, `STPython` wheel or `libaci.so` in this repository.
- The vendor driver published for Linux aarch64 is CPython 3.11 only.
- Windows SQL execution needs the ShenTong Windows client (`ACI.dll`).
- The bundled ShenTong media (if you supply it) carries a 90-day trial license.

## Development

```sh
PYTHONPATH=src sh -c 'for t in src/test/test_*.py; do python "$t"; done'
sh -n install-all.sh scripts/*.sh docker/entrypoint.sh
sh .secrets-scan.sh
```

Shell scripts must run under POSIX `/bin/sh` (no process substitution, no bash
arrays). External output parsed for English keywords must pin `LC_ALL=C`.

Rebuild the release assets locally (requires the portable Python archives and
per-architecture wheel directories):

```sh
VER=0.1.1 ARM64_PY_TGZ=... X64_PY_TGZ=... \
ARM64_WHEELS=... X64_WHEELS=... WIN_BUNDLE=... \
sh tools/build-release.sh
```

## License

MIT — see [`LICENSE`](LICENSE). `src/` is derived from vendor-delivered code;
scope and attribution are in [`NOTICE.md`](NOTICE.md).
