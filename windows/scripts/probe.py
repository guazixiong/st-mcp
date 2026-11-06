#!/usr/bin/env python3
"""Protocol probe for a running ST-MCP server (dynamic connection edition).

Only uses the standard library, so it runs on the package's own interpreter.
Reads credentials from the package config instead of argv.
"""

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

PASS = 0
FAIL = 0
SKIP = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("[PASS] %s %s" % (name, detail))
    else:
        FAIL += 1
        print("[FAIL] %s %s" % (name, detail))


def skip(name, why):
    global SKIP
    SKIP += 1
    print("[SKIP] %s %s" % (name, why))


def load_conf(path):
    values = {}
    with open(path, "r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            index = line.find("=")
            if index < 1:
                continue
            values[line[:index].strip()] = line[index + 1:].rstrip("\r\n")
    return values


def post(base, path, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    merged.update(headers or {})
    request = urllib.request.Request(base + path, data=data, headers=merged, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8", "replace")


def init_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "st-mcp-probe", "version": "1"},
        },
    }


def open_session(base, path, headers=None, query=""):
    status, response_headers, body = post(base, path + query, init_payload(), headers)
    session = response_headers.get("Mcp-Session-Id") or response_headers.get("mcp-session-id")
    if status == 200 and session:
        post(base, path, {"jsonrpc": "2.0", "method": "notifications/initialized"},
             dict(headers or {}, **{"Mcp-Session-Id": session}))
    return status, session, body


def call_sql(base, path, session, sql):
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "execute_sql", "arguments": {"query": sql}}}
    status, _, body = post(base, path, payload, {"Mcp-Session-Id": session})
    return status, body


def plain_headers(host, port, user, password, database):
    return {
        "X-ST-DB-Host": host,
        "X-ST-DB-Port": str(port),
        "X-ST-DB-User": user,
        "X-ST-DB-Password": password,
        "X-ST-DB-Name": database,
    }


def blob_header(host, port, user, password, database):
    payload = {"host": host, "port": int(port), "user": user, "password": password, "database": database}
    raw = json.dumps(payload).encode("utf-8")
    return {"X-ST-DB": base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")}


def pick_host(allow):
    for item in allow.split(","):
        item = item.strip()
        if item and item != "*" and "/" not in item and not item.startswith("*."):
            return item
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--path", default="/mcp")
    parser.add_argument("--conf", required=True)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    path = args.path if args.path.startswith("/") else "/" + args.path
    conf = load_conf(args.conf)

    allow = conf.get("ST_DYNAMIC_ALLOW", "")
    host = pick_host(allow) or "127.0.0.1"
    port = int(conf.get("ST_DYNAMIC_DEFAULT_PORT") or 2003)
    database = conf.get("ST_DYNAMIC_DEFAULT_DB") or "OSRDB"
    user = conf.get("ST_USER") or "SYSDBA"
    password = conf.get("ST_PASSWORD") or ""

    try:
        with urllib.request.urlopen(base + "/healthz", timeout=5) as response:
            health = json.loads(response.read().decode())
        check("healthz reachable", True, json.dumps(health))
        check("dynamic connections enabled", health.get("dynamic") is True, "")
    except Exception as exc:
        check("healthz reachable", False, str(exc))
        print("\n===== probe: %d PASS / %d FAIL / %d SKIP =====" % (PASS, FAIL, SKIP))
        return 1

    status, _, _ = open_session(base, path)
    check("request without target rejected", status == 401, "HTTP %s" % status)

    if allow == "*":
        skip("disallowed host rejected", "allow-list is '*'")
    else:
        status, _, _ = open_session(base, path, plain_headers("203.0.113.9", port, user, "probe-only", database))
        check("host outside allow-list rejected", status == 403, "HTTP %s" % status)

    status, session, body = open_session(base, path, plain_headers(host, port, user, "probe-only", database))
    check("plain X-ST-DB-* headers accepted", status == 200 and session is not None, "HTTP %s" % status)

    status, session_blob, _ = open_session(base, path, blob_header(host, port, user, "probe-only", database))
    check("single X-ST-DB blob accepted", status == 200 and session_blob is not None, "HTTP %s" % status)

    query = "?" + urllib.parse.urlencode({
        "st_host": host, "st_port": port, "st_user": user,
        "st_password": "probe-only", "st_db": database,
    })
    status, _, _ = open_session(base, path, None, query)
    check("URL query target accepted", status == 200, "HTTP %s" % status)

    try:
        import STPython  # noqa: F401
        driver_ok = True
    except Exception as exc:
        driver_ok = False
        driver_why = str(exc).splitlines()[0][:120]

    if not driver_ok:
        skip("database query", "STPython not importable: " + driver_why)
        skip("session binding", "depends on database query")
    elif not password:
        skip("database query", "ST_PASSWORD is empty in config")
        skip("session binding", "depends on database query")
    else:
        headers = plain_headers(host, port, user, password, database)
        if any(ord(ch) > 127 for ch in password + user + host + database):
            headers = blob_header(host, port, user, password, database)
        status, session, _ = open_session(base, path, headers)
        if session:
            status, body = call_sql(base, path, session, "SELECT USER FROM DUAL")
            check("database query as configured user",
                  status == 200 and "Error:" not in body and user.upper() in body.upper(), body[:160])
            status, body = call_sql(base, path, session, "SELECT USER FROM DUAL")
            check("session binding without headers",
                  status == 200 and "Error:" not in body and user.upper() in body.upper(), body[:160])
        else:
            check("database query as configured user", False, "HTTP %s" % status)

    print("\n===== probe: %d PASS / %d FAIL / %d SKIP =====" % (PASS, FAIL, SKIP))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
