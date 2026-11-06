import base64
import json

import pytest

from st_mcp import dynamic
from st_mcp.tenancy import TenantMiddleware


def settings(**overrides):
    base = dict(
        enabled=True,
        allow="10.0.0.0/8,127.0.0.1,*.corp.example",
        allow_ports="2003,2100",
        default_port=2003,
        default_database="OSRDB",
        access_mode="unrestricted",
        allow_default=False,
        max_targets=4,
    )
    base.update(overrides)
    return dynamic.Settings(**base)


def allow(**overrides):
    conf = settings(**overrides)
    return dynamic.AllowList(conf.allow, conf.allow_ports)


def test_headers_fields():
    raw = dynamic.from_headers(
        {
            "x-st-db-host": "10.1.2.3",
            "x-st-db-port": "2100",
            "x-st-db-user": "SYSDBA",
            "x-st-db-password": "p@ss/word",
            "x-st-db-name": "OSRDB",
        }
    )
    assert raw == {
        "host": "10.1.2.3",
        "port": "2100",
        "user": "SYSDBA",
        "password": "p@ss/word",
        "database": "OSRDB",
    }


def test_blob_header_json_and_base64():
    payload = {"ip": "10.9.9.9", "username": "u1", "pwd": "s3cret", "db": "DB1"}
    raw_json = dynamic.from_headers({"x-st-db": json.dumps(payload)})
    assert raw_json == {"host": "10.9.9.9", "user": "u1", "password": "s3cret", "database": "DB1"}
    blob = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert dynamic.from_headers({"x-st-db": blob}) == raw_json


def test_query_parameters_and_blob():
    raw = dynamic.from_query("st_host=10.0.0.5&st_user=bob&st_password=x&st_db=D2&st_port=2100")
    assert raw == {"host": "10.0.0.5", "user": "bob", "password": "x", "database": "D2", "port": "2100"}
    blob = base64.urlsafe_b64encode(b'{"host":"10.0.0.6","user":"eve","password":"y"}').decode()
    assert dynamic.from_query("st=" + blob) == {"host": "10.0.0.6", "user": "eve", "password": "y"}


def test_headers_win_over_query():
    target = dynamic.resolve(
        {"x-st-db-host": "10.2.2.2", "x-st-db-user": "a", "x-st-db-password": "p"},
        b"st_host=10.3.3.3&st_user=b&st_password=q",
        settings(),
        allow(),
    )
    assert target is not None
    assert target.host == "10.2.2.2"
    assert target.user == "a"


def test_allow_list_rules():
    listed = allow()
    assert listed.allows_host("10.1.1.1")
    assert listed.allows_host("127.0.0.1")
    assert listed.allows_host("db1.corp.example")
    assert not listed.allows_host("11.0.0.1")
    assert not listed.allows_host("corp.example")
    assert listed.allows_port(2003)
    assert not listed.allows_port(2004)
    assert dynamic.AllowList("*", "*").allows_host("203.0.113.9")
    assert not dynamic.AllowList("", "2003").allows_host("127.0.0.1")


def test_build_target_validation():
    conf = settings()
    listed = allow()
    good = dynamic.build_target(
        {"host": "10.0.0.8", "user": "u", "password": "p", "database": "OSRDB", "port": "2003"},
        conf,
        listed,
    )
    assert good.name.startswith("dyn-")
    assert good.token == ""
    assert good.port == 2003

    with pytest.raises(dynamic.TargetError):
        dynamic.build_target({"host": "10.0.0.8", "password": "p"}, conf, listed)
    with pytest.raises(dynamic.TargetError):
        dynamic.build_target({"host": "10.0.0.8", "user": "u"}, conf, listed)
    with pytest.raises(dynamic.TargetNotAllowed):
        dynamic.build_target({"host": "192.168.1.1", "user": "u", "password": "p"}, conf, listed)
    with pytest.raises(dynamic.TargetNotAllowed):
        dynamic.build_target({"host": "10.0.0.8", "user": "u", "password": "p", "port": "2004"}, conf, listed)


def test_identity_changes_with_password():
    a = dynamic.build_target({"host": "10.0.0.8", "user": "u", "password": "a"}, settings(), allow())
    b = dynamic.build_target({"host": "10.0.0.8", "user": "u", "password": "b"}, settings(), allow())
    assert a.name != b.name
    assert dynamic.build_target({"host": "10.0.0.8", "user": "u", "password": "a"}, settings(), allow()).name == a.name


def test_strip_headers_removes_credentials():
    scope = {
        "headers": [
            (b"x-st-db-host", b"10.0.0.1"),
            (b"X-ST-DB-Password", b"s3cret"),
            (b"x-st-db", b"blob"),
            (b"authorization", b"Bearer t"),
            (b"x-st-tenant-resolved", b"forged"),
        ]
    }
    left = dynamic.strip_headers(scope)
    assert left == [(b"authorization", b"Bearer t"), (b"x-st-tenant-resolved", b"forged")]


def test_middleware_resolution_status_codes():
    conf = settings()
    middleware = TenantMiddleware(None, None, "/mcp", dynamic_settings=conf, allow_list=allow())

    tenant, reason, code = middleware._resolve(
        {"x-st-db-host": "10.0.0.9", "x-st-db-user": "u", "x-st-db-password": "p"}, None, "", b""
    )
    assert code == 200 and tenant is not None and tenant.host == "10.0.0.9"

    tenant, reason, code = middleware._resolve(
        {"x-st-db-host": "8.8.8.8", "x-st-db-user": "u", "x-st-db-password": "p"}, None, "", b""
    )
    assert code == 403 and tenant is None

    tenant, reason, code = middleware._resolve({}, None, "", b"")
    assert code == 401 and "missing database target" in reason


def test_resolved_target_is_remembered():
    middleware = TenantMiddleware(None, None, "/mcp", dynamic_settings=settings(), allow_list=allow())
    tenant, _reason, code = middleware._resolve(
        {"x-st-db-host": "10.0.0.9", "x-st-db-user": "u", "x-st-db-password": "p"}, None, "", b""
    )
    assert code == 200 and tenant is not None
    assert dynamic.lookup(tenant.name) is tenant
