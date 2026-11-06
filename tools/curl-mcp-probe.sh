#!/bin/sh
# 用纯 curl 走一遍 streamable-http 的 MCP 调用链（无 python 依赖，现场可用）
# 用法：sh curl-mcp-probe.sh <URL前缀>   例：sh curl-mcp-probe.sh http://127.0.0.1:8000/mcp
set -u
U=${1:-http://127.0.0.1:8100/mcp}
H1='Content-Type: application/json'
H2='Accept: application/json, text/event-stream'

echo "===== [1] initialize ====="
curl -s -D /tmp/mcp-h.txt -o /tmp/mcp-b.txt -X POST "$U" -H "$H1" -H "$H2" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
echo "http 头里的 session："
grep -i '^mcp-session-id' /tmp/mcp-h.txt || echo "(没有 mcp-session-id 头)"
echo "响应体前 300 字节："
head -c 300 /tmp/mcp-b.txt; echo

SID=$(grep -i '^mcp-session-id' /tmp/mcp-h.txt | tr -d '\r\n' | awk '{print $2}')
[ -n "$SID" ] || { echo "PROBE_FAIL: 拿不到 session id"; exit 1; }
echo "SID=$SID"

echo "===== [2] notifications/initialized ====="
curl -s -o /tmp/mcp-n.txt -w 'HTTP %{http_code}\n' -X POST "$U" -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

echo "===== [3] tools/list ====="
curl -s -o /tmp/mcp-t.txt -w 'HTTP %{http_code}\n' -X POST "$U" -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
head -c 400 /tmp/mcp-t.txt; echo

echo "===== [4] tools/call execute_sql ====="
curl -s -o /tmp/mcp-s.txt -w 'HTTP %{http_code}\n' --max-time 60 -X POST "$U" -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"execute_sql","arguments":{"query":"SELECT VERSION()"}}}'
head -c 700 /tmp/mcp-s.txt; echo
