#!/usr/bin/env python3
"""Protocol probe for ST-MCP dynamic connections (stdlib only).

Usage:
    python3 scripts/probe-dynamic.py --base http://127.0.0.1:8100 \
        --host 10.0.0.21 --user APP --db OSRDB

The password is read from stdin (prompted) or from $ST_PASSWORD; it is never
taken from argv, so it does not show up in the process list.
"""

import argparse
import base64
import getpass
import json
import os
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
    status, response_headers, _ = post(base, path + query, init_payload(), headers)
    session = response_headers.get("Mcp-Session-Id") or response_headers.get("mcp-session-id")
    if status == 200 and session:
        post(base, path, {"jsonrpc": "2.0", "method": "notifications/initialized"},
             dict(headers or {}, **{"Mcp-Session-Id": session}))
    return status, session


def call_sql(base, path, session, sql):
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "execute_sql", "arguments": {"query": sql}}}
    status, _, body = post(base, path, payload, {"Mcp-Session-Id": session})
    return status, body


def field_headers(host, port, user, password, database):
    return {
        "X-ST-DB-Host": host,
        "X-ST-DB-Port": str(port),
        "X-ST-DB-User": user,
        "X-ST-DB-Password": password,
        "X-ST-DB-Name": database,
    }


def blob_header(host, port, user, password, database):
    payload = {"host": host, "port": int(port), "user": user, "password": password, "database": database}
    blob = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return {"X-ST-DB": blob}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--path", default="/mcp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2003)
    parser.add_argument("--user", default="SYSDBA")
    parser.add_argument("--db", default="OSRDB")
    parser.add_argument("--no-query", action="store_true", help="skip the legs that execute SQL")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    path = args.path if args.path.startswith("/") else "/" + args.path

    try:
        with urllib.request.urlopen(base + "/healthz", timeout=5) as response:
            health = json.loads(response.read().decode())
        check("healthz reachable", True, json.dumps(health))
        check("dynamic connections enabled", health.get("dynamic") is True, "")
    except Exception as exc:
        check("healthz reachable", False, str(exc))
        return finish()

    status, _ = open_session(base, path)
    check("request without target rejected", status == 401, "HTTP %s" % status)

    status, _ = open_session(base, path, field_headers("203.0.113.9", args.port, args.user, "probe-only", args.db))
    check("host outside allow-list rejected", status == 403, "HTTP %s" % status)

    status, _ = open_session(base, path, field_headers(args.host, args.port, args.user, "probe-only", args.db))
    check("plain X-ST-DB-* headers accepted", status == 200, "HTTP %s" % status)

    status, session = open_session(base, path, blob_header(args.host, args.port, args.user, "probe-only", args.db))
    check("single X-ST-DB blob accepted", status == 200, "HTTP %s" % status)

    query = "?" + urllib.parse.urlencode({
        "st_host": args.host, "st_port": args.port, "st_user": args.user,
        "st_password": "probe-only", "st_db": args.db,
    })
    status, _ = open_session(base, path, None, query)
    check("URL query target accepted", status == 200, "HTTP %s" % status)

    if args.no_query:
        skip("database query", "--no-query")
        return finish()

    password = os.environ.get("ST_PASSWORD") or ""
    if not password and sys.stdin.isatty():
        password = getpass.getpass("database password for %s (blank = skip): " % args.user)
    if not password:
        skip("database query", "no password (set ST_PASSWORD or run interactively)")
        return finish()

    # Non-ASCII passwords cannot travel in a latin-1 header value.
    ascii_safe = all(ord(ch) < 128 for ch in password + args.user + args.host + args.db)
    headers = (field_headers(args.host, args.port, args.user, password, args.db)
               if ascii_safe else blob_header(args.host, args.port, args.user, password, args.db))
    status, session = open_session(base, path, headers)
    if not session:
        check("database query", False, "HTTP %s" % status)
        return finish()

    status, body = call_sql(base, path, session, "SELECT USER FROM DUAL")
    check("database query as %s" % args.user,
          status == 200 and "Error:" not in body and args.user.upper() in body.upper(), body[:160])

    status, body = call_sql(base, path, session, "SELECT USER FROM DUAL")
    check("session binding without headers",
          status == 200 and "Error:" not in body and args.user.upper() in body.upper(), body[:160])
    return finish()


def finish():
    print("\n===== probe: %d PASS / %d FAIL / %d SKIP =====" % (PASS, FAIL, SKIP))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
