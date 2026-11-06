"""Per-request database targets for a single ST-MCP instance.

A client can point one ST-MCP process at a different ShenTong database on every
request.  The target is chosen, in order of precedence, by:

1. the tenant token (``/mcp/<token>``, ``Authorization: Bearer``, ``X-ST-Token``)
   -- a fixed account from the tenant registry;
2. a dynamic target carried by the request (see below);
3. the shared connection configured through the environment.

Dynamic targets travel in one of three shapes; headers win over the URL:

* separate headers -- ``X-ST-DB-Host``, ``X-ST-DB-Port``, ``X-ST-DB-User``,
  ``X-ST-DB-Password``, ``X-ST-DB-Name``;
* one header -- ``X-ST-DB`` holding either raw JSON or base64url JSON with the
  same keys (some clients only expose one custom header);
* URL query parameters -- ``?st_host=...&st_port=...&st_user=...&st_password=...&st_db=...``
  or ``?st=<base64url json>``.

Every dynamic target must match ``ST_DYNAMIC_ALLOW``: a comma-separated list of
exact hosts, CIDR ranges, or ``*.suffix`` patterns; ``*`` allows everything.
An empty list denies every target.  Credentials are never logged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl

from st_mcp.tenancy import Tenant

logger = logging.getLogger(__name__)

ENV_ENABLED = "ST_DYNAMIC_ENABLED"
ENV_ALLOW = "ST_DYNAMIC_ALLOW"
ENV_ALLOW_PORTS = "ST_DYNAMIC_ALLOW_PORTS"
ENV_DEFAULT_PORT = "ST_DYNAMIC_DEFAULT_PORT"
ENV_DEFAULT_DATABASE = "ST_DYNAMIC_DEFAULT_DB"
ENV_ACCESS_MODE = "ST_DYNAMIC_ACCESS_MODE"
ENV_ALLOW_DEFAULT = "ST_DYNAMIC_ALLOW_DEFAULT"
ENV_MAX_TARGETS = "ST_MAX_TARGETS"

BLOB_HEADER = "x-st-db"
FIELD_HEADERS = {
    "host": "x-st-db-host",
    "port": "x-st-db-port",
    "user": "x-st-db-user",
    "password": "x-st-db-password",
    "database": "x-st-db-name",
}
QUERY_PREFIX = "st_"
BLOB_QUERY = "st"

_ALIASES = {
    "host": ("host", "ip", "address", "db_host"),
    "port": ("port", "db_port"),
    "user": ("user", "username", "account", "db_user"),
    "password": ("password", "pass", "pwd", "db_password"),
    "database": ("database", "db", "dbname", "db_name", "service", "service_name"),
}


class TargetError(ValueError):
    """The request described a target that cannot be used."""

    status = 400


class TargetNotAllowed(TargetError):
    """The target is well-formed but the deployment does not allow it."""

    status = 403


def _flag(value: Optional[str], default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _port(value: object, default: int) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        port = int(text)
    except ValueError:
        raise TargetError(f"port {text!r} is not a number")
    if not 1 <= port <= 65535:
        raise TargetError(f"port {port} is out of range 1-65535")
    return port


@dataclass(frozen=True)
class Settings:
    """Dynamic-target policy, loaded once at startup."""

    enabled: bool = False
    allow: str = ""
    allow_ports: str = "2003"
    default_port: int = 2003
    default_database: str = "OSRDB"
    access_mode: str = "unrestricted"
    allow_default: bool = False
    max_targets: int = 16

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        e = os.environ if env is None else env
        return cls(
            enabled=_flag(e.get(ENV_ENABLED), False),
            allow=(e.get(ENV_ALLOW) or "").strip(),
            allow_ports=(e.get(ENV_ALLOW_PORTS) or "2003").strip(),
            default_port=_port(e.get(ENV_DEFAULT_PORT) or 2003, 2003),
            default_database=(e.get(ENV_DEFAULT_DATABASE) or "OSRDB").strip() or "OSRDB",
            access_mode=(e.get(ENV_ACCESS_MODE) or "unrestricted").strip().lower(),
            allow_default=_flag(e.get(ENV_ALLOW_DEFAULT), False),
            max_targets=max(1, int(e.get(ENV_MAX_TARGETS) or 16)),
        )


class AllowList:
    """Host and port allow-list for dynamic targets."""

    def __init__(self, hosts: str, ports: str = "2003") -> None:
        self.entries = [item.strip() for item in hosts.split(",") if item.strip()]
        self.all_hosts = "*" in self.entries
        self.port_entries = [item.strip() for item in ports.split(",") if item.strip()]
        self.all_ports = "*" in self.port_entries or not self.port_entries

    def allows_host(self, host: str) -> bool:
        if self.all_hosts:
            return True
        candidate = host.strip().strip("[]").lower()
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            address = None
        for entry in self.entries:
            lowered = entry.lower()
            if "/" in entry:
                if address is None:
                    continue
                try:
                    network = ipaddress.ip_network(entry, strict=False)
                except ValueError:
                    logger.warning("Ignoring invalid CIDR in %s: %s", ENV_ALLOW, entry)
                    continue
                if address in network:
                    return True
                continue
            if lowered.startswith("*."):
                if candidate.endswith(lowered[1:]) and candidate != lowered[2:]:
                    return True
                continue
            if candidate == lowered:
                return True
        return False

    def allows_port(self, port: int) -> bool:
        if self.all_ports:
            return True
        for entry in self.port_entries:
            if entry.isdigit() and int(entry) == port:
                return True
        return False


def _decode_blob(value: str) -> Dict[str, object]:
    text = value.strip()
    if not text:
        raise TargetError("empty dynamic target")
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise TargetError(f"dynamic target JSON is invalid: {exc}")
    else:
        padded = text + "=" * (-len(text) % 4)
        raw = None
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                raw = decoder(padded)
                break
            except (binascii.Error, ValueError):
                continue
        if raw is None:
            raise TargetError("dynamic target is neither JSON nor base64url JSON")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TargetError(f"dynamic target payload is invalid: {exc}")
    if not isinstance(data, dict):
        raise TargetError("dynamic target payload must be a JSON object")
    return data


def _normalize(data: Mapping[str, object]) -> Dict[str, object]:
    lowered = {str(key).strip().lower(): value for key, value in data.items()}
    out: Dict[str, object] = {}
    for field_name, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in lowered and lowered[alias] not in (None, ""):
                out[field_name] = lowered[alias]
                break
    return out


def from_headers(headers: Mapping[str, str]) -> Optional[Dict[str, object]]:
    """Dynamic target from request headers (already lowercased)."""
    blob = headers.get(BLOB_HEADER)
    if blob:
        return _normalize(_decode_blob(blob))
    values = {}
    for field_name, header in FIELD_HEADERS.items():
        value = headers.get(header)
        if value not in (None, ""):
            values[field_name] = value
    return _normalize(values) if values else None


def from_query(query_string: object) -> Optional[Dict[str, object]]:
    """Dynamic target from the URL query string."""
    if not query_string:
        return None
    if isinstance(query_string, bytes):
        query_string = query_string.decode("latin-1")
    pairs = parse_qsl(query_string, keep_blank_values=True)
    if not pairs:
        return None
    values: Dict[str, object] = {}
    for key, value in pairs:
        if key == BLOB_QUERY and value:
            return _normalize(_decode_blob(value))
    for key, value in pairs:
        if key.startswith(QUERY_PREFIX):
            name = key[len(QUERY_PREFIX):]
            if value != "":
                values[name] = value
    return _normalize(values) if values else None


def _identity(host: str, port: int, user: str, password: str, database: str) -> str:
    digest = hashlib.sha256(
        "\x00".join((host, str(port), user, password, database)).encode("utf-8")
    ).hexdigest()
    return "dyn-" + digest[:16]


_targets: Dict[str, Tenant] = {}


def remember(target: Tenant) -> Tenant:
    if len(_targets) > 4096:
        _targets.clear()
    _targets[target.name] = target
    return target


def lookup(name: str) -> Optional[Tenant]:
    return _targets.get(name)


def forget_except(names: Iterable[str]) -> None:
    keep = set(names)
    for name in [name for name in _targets if name not in keep]:
        _targets.pop(name, None)


def build_target(raw: Mapping[str, object], settings: Settings, allow: AllowList) -> Tenant:
    """Validate one client-supplied target and turn it into a routable tenant."""
    host = str(raw.get("host") or "").strip()
    user = str(raw.get("user") or "").strip()
    password = raw.get("password")
    password = "" if password is None else str(password)
    database = str(raw.get("database") or settings.default_database).strip()
    if not host:
        raise TargetError("dynamic target is missing host")
    if not user:
        raise TargetError("dynamic target is missing user")
    if not password:
        raise TargetError("dynamic target is missing password")
    if not database:
        raise TargetError("dynamic target is missing database")
    port = _port(raw.get("port"), settings.default_port)

    if not allow.allows_host(host):
        raise TargetNotAllowed(f"host {host} is not in {ENV_ALLOW}")
    if not allow.allows_port(port):
        raise TargetNotAllowed(f"port {port} is not in {ENV_ALLOW_PORTS}")

    return Tenant(
        name=_identity(host, port, user, password, database),
        token="",
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        access_mode=settings.access_mode,
    )


def resolve(headers: Mapping[str, str], query_string: object, settings: Settings, allow: AllowList) -> Optional[Tenant]:
    """Resolve a dynamic target; ``None`` means the request did not ask for one."""
    raw = from_headers(headers)
    if raw is None:
        raw = from_query(query_string)
    if raw is None:
        return None
    return remember(build_target(raw, settings, allow))


def describe(settings: Settings, allow: AllowList) -> str:
    if not settings.enabled:
        return "dynamic connections disabled"
    allowed = "all hosts" if allow.all_hosts else f"{len(allow.entries)} allow-list entry(ies)"
    ports = "all ports" if allow.all_ports else ",".join(allow.port_entries)
    return f"dynamic connections enabled ({allowed}; ports {ports})"


def strip_headers(scope: Mapping[str, object]) -> List[Tuple[bytes, bytes]]:
    """Remove the dynamic headers so the MCP transport never sees credentials."""
    reserved = {BLOB_HEADER.encode("latin-1")} | {value.encode("latin-1") for value in FIELD_HEADERS.values()}
    return [(key, value) for key, value in scope.get("headers") or [] if key.lower() not in reserved]
