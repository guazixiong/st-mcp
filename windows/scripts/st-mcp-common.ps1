# 公共函数：读配置、定位便携运行时、设置环境变量、探测神通客户端目录。
# 由 start-server.ps1 / verify.ps1 dot-source 引用。

$script:StMcpRoot = Split-Path -Parent $PSScriptRoot

function Get-StMcpConf {
    param([string]$Path = (Join-Path $script:StMcpRoot 'config\st-mcp.conf'))
    if (-not (Test-Path -LiteralPath $Path)) { throw "缺少配置文件 $Path" }
    $table = [ordered]@{}
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*$' -or $line -match '^\s*#') { continue }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { continue }
        $key = $line.Substring(0, $i).Trim()
        # 值原样保留：不剥引号、不在 # 处截断、不 trim 空格（口令可能含这些字符）
        $table[$key] = $line.Substring($i + 1)
    }
    return $table
}

function Get-StMcpPython {
    $py = Join-Path $script:StMcpRoot 'env\python.exe'
    if (-not (Test-Path -LiteralPath $py)) { throw "缺少便携 Python：$py" }
    return $py
}

function Get-StMcpExe {
    $exe = Join-Path $script:StMcpRoot 'env\Scripts\st-mcp.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw "缺少 st-mcp 命令：$exe" }
    return $exe
}

function Find-StMcpAciDll {
    param([string]$Preferred)
    $candidates = @()
    if ($Preferred) { $candidates += $Preferred }
    $candidates += @(
        'C:\ShentongDB\bin',
        'D:\ShentongDB\bin',
        'C:\OSCAR\bin',
        'C:\Program Files\ShentongDB\bin',
        'C:\Program Files (x86)\ShentongDB\bin',
        (Join-Path $script:StMcpRoot 'vendor-bin')
    )
    foreach ($dir in $candidates) {
        if ($dir -and (Test-Path -LiteralPath (Join-Path $dir 'ACI.dll'))) { return $dir }
    }
    foreach ($dir in (($env:PATH -split ';') | Where-Object { $_ })) {
        if (Test-Path -LiteralPath (Join-Path $dir 'ACI.dll')) { return $dir }
    }
    return $null
}

function Set-StMcpConfEnv {
    # 把配置里的每个键都导出成进程环境变量，子进程（st-mcp.exe）直接继承。
    param($Conf)
    foreach ($key in $Conf.Keys) {
        if ($key -eq 'ST_BIN_DIR') { continue }
        Set-Item -Path "Env:$key" -Value ([string]$Conf[$key])
    }
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
}

function Invoke-StMcpPython {
    # 运行一小段 Python 并收集 stdout/stderr。原生程序写 stderr 时
    # PowerShell 5.1 在 $ErrorActionPreference='Stop' 下会抛 NativeCommandError，
    # 这里临时降级成 Continue，让调用方按退出码判断。
    param([string]$Code)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & (Get-StMcpPython) -c $Code 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    return @{ Output = (($output | ForEach-Object { "$_" }) -join "`n").Trim(); Code = $code }
}

function Get-StMcpLanAddresses {    $list = @()
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            ForEach-Object { $list += $_.IPAddress }
    } catch {
        try {
            [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
                Where-Object { $_.AddressFamily -eq 'InterNetwork' -and -not $_.IPAddressToString.StartsWith('127.') } |
                ForEach-Object { $list += $_.IPAddressToString }
        } catch { }
    }
    return ($list | Select-Object -Unique)
}
