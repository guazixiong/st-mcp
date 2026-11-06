param(
    [int]$Port = 0,
    [switch]$NoBanner
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'st-mcp-common.ps1')

$conf = Get-StMcpConf
Set-StMcpConfEnv $conf

$aci = Find-StMcpAciDll ([string]$conf['ST_BIN_DIR'])
if ($aci -and (($env:PATH -split ';') -notcontains $aci)) {
    $env:PATH = "$aci;$env:PATH"
}

$py = Get-StMcpPython
$exe = Get-StMcpExe
$hostAddr = [string]$conf['SSE_HOST']; if (-not $hostAddr) { $hostAddr = '0.0.0.0' }
$listenPort = if ($Port -gt 0) { $Port } elseif ($conf['SSE_PORT']) { [int][string]$conf['SSE_PORT'] } else { 8100 }
$mcpPath = [string]$conf['MCP_PATH']; if (-not $mcpPath) { $mcpPath = '/mcp' }
$logLevel = [string]$conf['LOG_LEVEL']; if (-not $logLevel) { $logLevel = 'INFO' }

if (-not $NoBanner) {
    $driverProbe = Invoke-StMcpPython "import STPython"
    $driverOk = ($driverProbe.Code -eq 0)

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '  ST-MCP 神通数据库 MCP 服务（动态连接版）' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ("  监听端口 : {0}" -f $listenPort)
    Write-Host ("  端点路径 : {0}" -f $mcpPath)
    Write-Host ("  动态白名单: {0}（端口 {1}）" -f $conf['ST_DYNAMIC_ALLOW'], $conf['ST_DYNAMIC_ALLOW_PORTS'])
    if ($aci) {
        Write-Host ("  神通客户端: {0}" -f $aci) -ForegroundColor Green
    } else {
        Write-Host '  神通客户端: 未找到 ACI.dll（服务可启动，执行 SQL 前请安装神通客户端或填 ST_BIN_DIR）' -ForegroundColor Yellow
    }
    if (-not $driverOk) {
        Write-Host '  STPython  : 当前不可用（与上一行同因）' -ForegroundColor Yellow
    }
    Write-Host ''
    Write-Host '  本机客户端填：'
    Write-Host ("    http://127.0.0.1:{0}{1}" -f $listenPort, $mcpPath)
    foreach ($ip in (Get-StMcpLanAddresses)) {
        Write-Host ("    http://{0}:{1}{2}" -f $ip, $listenPort, $mcpPath)
    }
    Write-Host ''
    Write-Host '  目标库信息两种带法（示例）：'
    Write-Host '    请求头  X-ST-DB-Host / X-ST-DB-Port / X-ST-DB-User / X-ST-DB-Password / X-ST-DB-Name'
    Write-Host '    或单头  X-ST-DB: base64url(JSON)  —— 口令含中文时用这个'
    Write-Host '    或 URL  ?st_host=...&st_port=2003&st_user=...&st_password=...&st_db=OSRDB'
    Write-Host ''
    Write-Host '  按 Ctrl+C 停止服务。' -ForegroundColor DarkGray
    Write-Host ''
}

# 前台运行：窗口里直接看到访问日志；关闭窗口即停止。
& $exe --transport streamable-http --sse-host $hostAddr --sse-port $listenPort --mcp-path $mcpPath --log-level $logLevel
exit $LASTEXITCODE
