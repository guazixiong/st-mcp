"""Single-port multi-tenant routing for ST-MCP.

One server process listens on one port.  Every MCP request carries a tenant
token (``Authorization: Bearer <token>`` or ``X-ST-Token``); the token selects
a database account, and that account's own privileges keep the tenants apart.
The database stays the authorization boundary -- this module only routes the
request to the matching connection pool.

The tenant registry is a JSON file owned by the deployment (mode 600).  It is
re-read whenever its mtime changes, so adding a tenant does not need a
restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from st_mcp.sql import ConnectionSpec, DbConnPool

logger = logging.getLogger(__name__)

REGISTRY_ENV = "ST_TENANT_REGISTRY"
DEFAULT_TENANT_ENV = "ST_DEFAULT_TENANT"
ALLOW_DEFAULT_ENV = "ST_ALLOW_DEFAULT"
ACCESS_MODES = ("unrestricted", "restricted")

# Written by the middleware after it resolves the tenant.  Tool handlers run in
# a task started by the MCP session manager, not in the HTTP request task, so
# they cannot see the middleware's ContextVar; the resolved name is carried on
# the request scope instead (client-supplied copies are stripped first).
RESOLVED_HEADER = "x-st-tenant-resolved"

# Set for the duration of one HTTP request (and inherited by the task the MCP
# transport spins up for it).  Tools read this instead of a global pool.
current_tenant: ContextVar[Optional["Tenant"]] = ContextVar("st_mcp_tenant", default=None)


def _connect_host(host: str) -> str:
    """Map loopback to the host gateway when running inside the container.

    entrypoint.sh does the same for the shared connection; tenant pools are
    built here, so the same rewrite has to happen here too.
    """
    if host in ("127.0.0.1", "localhost", "::1"):
        gateway = os.environ.get("ST_HOST_GATEWAY", "").strip()
        if gateway:
            return gateway
    return host


@dataclass(frozen=True)
class Tenant:
    name: str
    token: str
    host: str
    port: int
    database: str
    user: str
    password: str
    access_mode: str = "unrestricted"

    def spec(self) -> ConnectionSpec:
        return ConnectionSpec(
            host=_connect_host(self.host),
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )


def _parse_tenant(raw: Dict[str, Any]) -> Tenant:
    name = str(raw.get("name") or "").strip()
    token = str(raw.get("token") or "").strip()
    user = str(raw.get("user") or "").strip()
    password = str(raw.get("password") or "")
    host = str(raw.get("host") or "127.0.0.1").strip()
    database = str(raw.get("database") or "OSRDB").strip()
    access_mode = str(raw.get("access_mode") or "unrestricted").strip().lower()
    if not name or not token or not user:
        raise ValueError("name/token/user are required")
    if len(token) < 16:
        raise ValueError("token must be at least 16 characters")
    if access_mode not in ACCESS_MODES:
        raise ValueError("access_mode must be unrestricted or restricted")
    if raw.get("enabled", True) is False:
        raise ValueError("tenant is disabled")
    return Tenant(
        name=name,
        token=token,
        host=host,
        port=int(raw.get("port") or 2003),
        database=database,
        user=user,
        password=password,
        access_mode=access_mode,
    )


class TenantRegistry:
    def __init__(self, path: str) -> None:
        self.path = path
        self._mtime_ns = -1
        self._by_name: Dict[str, Tenant] = {}
        self._by_token: Dict[str, Tenant] = {}
        self._lock = threading.Lock()
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        try:
            stat = os.stat(self.path)
        except OSError:
            if force:
                logger.warning("Tenant registry not found: %s", self.path)
            return
        if not force and stat.st_mtime_ns == self._mtime_ns:
            return
        with self._lock:
            if not force and stat.st_mtime_ns == self._mtime_ns:
                return
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    document = json.load(fh)
            except Exception as exc:  # keep serving the last good copy
                logger.error("Cannot read tenant registry %s: %s", self.path, exc)
                return
            by_name: Dict[str, Tenant] = {}
            by_token: Dict[str, Tenant] = {}
            for raw in document.get("tenants") or []:
                try:
                    tenant = _parse_tenant(raw)
                except Exception as exc:
                    logger.error("Skipping invalid tenant %r: %s", raw.get("name"), exc)
                    continue
                if tenant.token in by_token:
                    logger.error("Duplicate token for tenant %s; skipped", tenant.name)
                    continue
                by_name[tenant.name] = tenant
                by_token[tenant.token] = tenant
            self._by_name = by_name
            self._by_token = by_token
            self._mtime_ns = stat.st_mtime_ns
            logger.info("Tenant registry loaded: %d tenant(s)", len(by_name))

    def get(self, name: str) -> Optional[Tenant]:
        self.reload()
        return self._by_name.get(name)

    def by_token(self, token: str) -> Optional[Tenant]:
        self.reload()
        return self._by_token.get(token)

    def all(self) -> List[Tenant]:
        self.reload()
        return list(self._by_name.values())


_registry: Optional[TenantRegistry] = None
_pools: "OrderedDict[str, DbConnPool]" = OrderedDict()
_tool_cache: Dict[str, Tuple[Any, ...]] = {}
_pool_lock: Optional[asyncio.Lock] = None
MAX_POOLS_ENV = "ST_MAX_TARGETS"


def init_registry(path: Optional[str] = None) -> Optional[TenantRegistry]:
    global _registry
    path = path or os.environ.get(REGISTRY_ENV)
    if not path:
        return None
    _registry = TenantRegistry(path)
    return _registry


def registry() -> Optional[TenantRegistry]:
    return _registry


def registry_path() -> str:
    return os.environ.get(REGISTRY_ENV, "")


def tenant_from_request(request: Any) -> Optional[Tenant]:
    """Tenant or dynamic target for a tool call, from the ContextVar or scope."""
    tenant = current_tenant.get()
    if tenant is not None:
        return tenant
    if request is None:
        return None
    try:
        name = request.headers.get(RESOLVED_HEADER, "").strip()
        if name:
            resolved = _registry.get(name) if _registry is not None else None
            if resolved is None:
                from st_mcp import dynamic

                resolved = dynamic.lookup(name)
            return resolved
        if _registry is None:
            return None
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        token = token or request.headers.get("x-st-token", "").strip()
        return _registry.by_token(token) if token else None
    except Exception:
        return None


def _same_spec(pool: DbConnPool, tenant: Tenant) -> bool:
    spec = pool.spec
    return bool(
        spec
        and spec.host == tenant.host
        and int(spec.port) == tenant.port
        and spec.user == tenant.user
        and spec.password == tenant.password
        and spec.database == tenant.database
    )


def _lock() -> asyncio.Lock:
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def get_pool(tenant: Tenant) -> DbConnPool:
    async with _lock():
        pool = _pools.get(tenant.name)
        if pool is not None and _same_spec(pool, tenant):
            _pools.move_to_end(tenant.name)
            return pool
        if pool is not None:
            await pool.close()
        pool = DbConnPool()
        await pool.pool_connect(spec=tenant.spec())
        _pools[tenant.name] = pool
        _pools.move_to_end(tenant.name)
        limit = max(1, int(os.environ.get(MAX_POOLS_ENV) or 16))
        while len(_pools) > limit:
            _evicted_name, evicted = _pools.popitem(last=False)
            try:
                await evicted.close()
            except Exception as exc:
                logger.error("Error closing evicted pool: %s", exc)
        return pool


async def get_tools(tenant: Tenant) -> Tuple[Any, Any, Any, Any]:
    """Explain/health/top-queries/index-analyzer bound to this tenant's pool."""
    from st_mcp.database_health.database_health_tool import DatabaseHealthTool
    from st_mcp.explain.explain_plan_tool import ExplainPlanTool
    from st_mcp.index_analysis.index_analyzer import IndexAnalyzer
    from st_mcp.sql import SqlDriver
    from st_mcp.top_queries.top_queries_calc import TopQueriesCalc

    key = (tenant.user, tenant.password, tenant.host, tenant.port, tenant.database)
    cached = _tool_cache.get(tenant.name)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2], cached[3], cached[4]
    pool = await get_pool(tenant)
    driver = SqlDriver(conn=pool)
    tools = (
        ExplainPlanTool(driver),
        DatabaseHealthTool(driver),
        TopQueriesCalc(driver),
        IndexAnalyzer(driver),
    )
    _tool_cache[tenant.name] = (key,) + tools
    return tools


async def close_all() -> None:
    for pool in list(_pools.values()):
        try:
            await pool.close()
        except Exception as exc:
            logger.error("Error closing tenant pool: %s", exc)
    _pools.clear()
    _tool_cache.clear()


class TenantMiddleware:
    """Resolve the database target from request headers, then bind it.

    Three sources, highest priority first: a tenant token, a dynamic target
    (``X-ST-DB-*`` headers or URL query), and the shared/default connection.
    Also serves ``GET /healthz`` (unauthenticated, no tenant data) so the
    deployment script can tell the process is alive before any tenant exists.
    """

    def __init__(
        self,
        app: Any,
        tenant_registry: Optional[TenantRegistry],
        mcp_path: str = "/mcp",
        dynamic_settings: Any = None,
        allow_list: Any = None,
    ) -> None:
        self.app = app
        self.registry = tenant_registry
        self.mcp_path = mcp_path
        self.dynamic_settings = dynamic_settings
        self.allow_list = allow_list
        self.sessions: Dict[str, Tuple[str, str]] = {}
        self.allow_default = os.environ.get(ALLOW_DEFAULT_ENV, "0") == "1"
        self.default_tenant = os.environ.get(DEFAULT_TENANT_ENV, "")

    def _tenant_count(self) -> int:
        return len(self.registry.all()) if self.registry is not None else 0

    def _dynamic_enabled(self) -> bool:
        return bool(self.dynamic_settings is not None and self.dynamic_settings.enabled)

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path == "/healthz":
            await self._json(
                send,
                200,
                {"ok": True, "tenants": self._tenant_count(), "dynamic": self._dynamic_enabled()},
            )
            return
        if path != self.mcp_path and not path.startswith(self.mcp_path + "/"):
            await self.app(scope, receive, send)
            return

        scope = dict(scope)
        # A per-tenant URL (/mcp/<token>) needs no client header support: strip the
        # token from the path, hand the plain MCP path to the transport.
        path_token = ""
        if path != self.mcp_path:
            path_token = path[len(self.mcp_path) + 1:].strip("/")
            scope["path"] = self.mcp_path
            scope["raw_path"] = self.mcp_path.encode("latin-1")

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        session_id = headers.get("mcp-session-id")
        tenant, reason, status = self._resolve(headers, session_id, path_token, scope.get("query_string"))
        if tenant is None:
            await self._json(
                send,
                status,
                {"error": "unauthorized" if status == 401 else "rejected", "message": reason},
                extra_headers=[(b"www-authenticate", b'Bearer realm="st-mcp"')] if status == 401 else None,
            )
            return
        bound = self.sessions.get(session_id) if session_id else None
        if bound is not None and bound[1] != tenant.name:
            await self._json(send, 401, {"error": "unauthorized", "message": "session belongs to another target"})
            return

        token = current_tenant.set(tenant)
        scope["headers"] = self._clean_headers(scope) + [
            (RESOLVED_HEADER.encode("latin-1"), tenant.name.encode("latin-1"))
        ]

        async def send_with_session(message: Dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                for key, value in message.get("headers") or []:
                    if key.lower() == b"mcp-session-id":
                        self._bind(value.decode("latin-1"), tenant)
                        break
            await send(message)

        try:
            await self.app(scope, receive, send_with_session)
        finally:
            current_tenant.reset(token)

    @staticmethod
    def _clean_headers(scope: Dict[str, Any]) -> List[Tuple[bytes, bytes]]:
        """Drop credential-bearing and client-forged routing headers."""
        from st_mcp import dynamic

        kept = dynamic.strip_headers(scope)
        reserved = RESOLVED_HEADER.encode("latin-1")
        return [(key, value) for key, value in kept if key.lower() != reserved]

    def _resolve(
        self,
        headers: Dict[str, str],
        session_id: Optional[str],
        path_token: str = "",
        query_string: Any = b"",
    ) -> Tuple[Optional[Tenant], str, int]:
        token = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            token = headers.get("x-st-token", "").strip()
        if token and path_token and token != path_token:
            return None, "URL token and header token do not match", 401
        token = token or path_token
        name = headers.get("x-st-tenant", "").strip()

        if token:
            if self.registry is None:
                return None, "this server has no tenant registry; pass database info in X-ST-DB-* headers", 401
            tenant = self.registry.by_token(token)
            if tenant is None:
                return None, "unknown token", 401
            if name and name != tenant.name:
                return None, "tenant and token do not match", 401
            return tenant, "", 200
        if name:
            if self.registry is None:
                return None, "this server has no tenant registry", 401
            tenant = self.registry.get(name)
            if tenant is None:
                return None, "unknown tenant", 401
            return tenant, "", 200

        if self._dynamic_enabled():
            from st_mcp import dynamic

            try:
                target = dynamic.resolve(headers, query_string, self.dynamic_settings, self.allow_list)
            except dynamic.TargetNotAllowed as exc:
                return None, str(exc), 403
            except dynamic.TargetError as exc:
                return None, str(exc), 400
            if target is not None:
                return target, "", 200

        if session_id and session_id in self.sessions:
            kind, bound_name = self.sessions[session_id]
            if kind == "tenant":
                tenant = self.registry.get(bound_name) if self.registry is not None else None
                if tenant is not None:
                    return tenant, "", 200
                return None, "session tenant no longer exists", 401
            from st_mcp import dynamic

            target = dynamic.lookup(bound_name)
            if target is not None:
                return target, "", 200
            return None, "session target is no longer available", 401

        if self.allow_default and self.default_tenant and self.registry is not None:
            tenant = self.registry.get(self.default_tenant)
            if tenant is not None:
                return tenant, "", 200
        return None, (
            "missing database target: use /mcp/<token>, Authorization: Bearer <token>, "
            "X-ST-DB-* headers, or the st_* URL parameters"
        ), 401

    def _bind(self, session_id: str, tenant: Tenant) -> None:
        if not session_id:
            return
        if len(self.sessions) > 10000:
            self.sessions.clear()
        self.sessions[session_id] = ("tenant" if tenant.token else "dynamic", tenant.name)

    @staticmethod
    async def _json(send: Any, status: int, payload: Dict[str, Any], extra_headers: Optional[List[Tuple[bytes, bytes]]] = None) -> None:
        import json as _json

        body = _json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]
        headers.extend(extra_headers or [])
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
