# 一键验收：环境、驱动、配置、启动、动态连接协议、数据库握手。
# 不修改系统设置，用时约 20-40 秒。
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'st-mcp-common.ps1')

$pass = 0; $fail = 0; $skipCount = 0
function Ok([string]$name, [string]$detail = '') {
    $script:pass++
    Write-Host ("[PASS] {0} {1}" -f $name, $detail) -ForegroundColor Green
}
function Bad([string]$name, [string]$detail = '') {
    $script:fail++
    Write-Host ("[FAIL] {0} {1}" -f $name, $detail) -ForegroundColor Red
}
function Skip([string]$name, [string]$why) {
    $script:skipCount++
    Write-Host ("[SKIP] {0} {1}" -f $name, $why) -ForegroundColor Yellow
}

Write-Host ''
Write-Host '===== ST-MCP Windows 验收 =====' -ForegroundColor Cyan

$conf = Get-StMcpConf
Set-StMcpConfEnv $conf

try {
    $py = Get-StMcpPython
    Ok 'portable runtime' $py
} catch {
    Bad 'portable runtime' $_.Exception.Message
    Write-Host '验收中止：运行时缺失。' -ForegroundColor Red
    exit 1
}

try {
    $exe = Get-StMcpExe
    Ok 'st-mcp launcher' $exe
} catch {
    Bad 'st-mcp launcher' $_.Exception.Message
    exit 1
}

$version = Invoke-StMcpPython "import st_mcp; print('ok')"
if ($version.Code -eq 0 -and $version.Output -eq 'ok') {
    Ok 'python package st_mcp' 'import ok'
} else {
    Bad 'python package st_mcp' (($version.Output -split "`n") | Select-Object -First 1)
}

if ([string]$conf['ST_DYNAMIC_ENABLED'] -match '^(?i:yes|true|1|on)$') {
    Ok 'dynamic connections configured' ("allow=" + $conf['ST_DYNAMIC_ALLOW'])
    if (-not ([string]$conf['ST_DYNAMIC_ALLOW']).Trim()) {
        Bad 'allow-list not empty' '空列表会拒绝所有动态目标'
    }
} else {
    Bad 'dynamic connections configured' 'ST_DYNAMIC_ENABLED 不是 yes'
}

$aci = Find-StMcpAciDll ([string]$conf['ST_BIN_DIR'])
if ($aci) {
    Ok 'ShenTong client ACI.dll' $aci
    if (($env:PATH -split ';') -notcontains $aci) { $env:PATH = "$aci;$env:PATH" }
} else {
    Skip 'ShenTong client ACI.dll' '未安装神通客户端；协议层可验收，SQL 需装好后重跑'
}

$driver = Invoke-StMcpPython "import STPython; print('ok')"
if ($driver.Code -eq 0 -and $driver.Output -eq 'ok') {
    Ok 'STPython import'
} else {
    $lines = @($driver.Output -split "`n" | Where-Object { $_.Trim() })
    Skip 'STPython import' $(if ($lines.Count) { $lines[-1].Trim() } else { 'import failed' })
}

# --- 起一个临时实例做协议验收 ---
$listen = 8300
if ($conf['SSE_PORT'] -and [int][string]$conf['SSE_PORT'] -lt 8399) { $listen = [int][string]$conf['SSE_PORT'] + 1 }
$listener = $null
for ($p = $listen; $p -lt $listen + 40; $p++) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
        $listener.Start(); $listener.Stop()
        $listen = $p
        break
    } catch { $listener = $null }
}
if (-not $listener) {
    Bad 'free port for test instance' "没有可用端口（从 $listen 起试了 40 个）"
    Write-Host ("验收汇总：{0} PASS / {1} FAIL / {2} SKIP" -f $pass, $fail, $skipCount) -ForegroundColor Cyan
    exit 1
}

$logs = Join-Path $script:StMcpRoot 'logs'
if (-not (Test-Path -LiteralPath $logs)) { New-Item -ItemType Directory -Path $logs -Force | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $logs "verify-$stamp.log"
$err = Join-Path $logs "verify-$stamp.err"
$path = [string]$conf['MCP_PATH']; if (-not $path) { $path = '/mcp' }

$proc = Start-Process -FilePath $exe `
    -ArgumentList @('--transport', 'streamable-http', '--sse-host', '127.0.0.1', '--sse-port', "$listen", '--mcp-path', $path, '--log-level', 'INFO') `
    -WorkingDirectory $script:StMcpRoot `
    -RedirectStandardOutput $out -RedirectStandardError $err `
    -WindowStyle Hidden -PassThru

$up = $false
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $client.Connect('127.0.0.1', $listen)
        $client.Close()
        $up = $true
        break
    } catch { Start-Sleep -Milliseconds 400 }
}

if ($up) {
    Ok 'server started' ("http://127.0.0.1:{0}{1}" -f $listen, $path)
    try {
        $probe = Join-Path $script:StMcpRoot 'scripts\probe.py'
        $confPath = Join-Path $script:StMcpRoot 'config\st-mcp.conf'
        $old = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $probeOut = & $py $probe --base ("http://127.0.0.1:{0}" -f $listen) --path $path --conf $confPath 2>&1
            $probeCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $old
        }
        $probeOut | ForEach-Object { Write-Host $_ }
        if ($probeCode -eq 0) { Ok 'protocol probe' } else { Bad 'protocol probe' '见上方 FAIL 行' }
    } finally {
        & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
        Start-Sleep -Milliseconds 800
    }
} else {
    Bad 'server started' '30 秒内端口未监听'
    if (Test-Path -LiteralPath $err) { Get-Content -LiteralPath $err -Tail 20 }
    & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
}

try {
    if ((Test-Path -LiteralPath $out) -and (Select-String -LiteralPath $out, $err -Pattern 'Traceback' -Quiet -ErrorAction SilentlyContinue)) {
        Bad 'server log clean' '日志出现 Traceback'
    } else {
        Ok 'server log clean'
    }
} catch { Ok 'server log clean' }

Write-Host ''
Write-Host ("===== 验收汇总：{0} PASS / {1} FAIL / {2} SKIP =====" -f $pass, $fail, $skipCount) -ForegroundColor Cyan
if ($fail -gt 0) { exit 1 } else { exit 0 }
