# 用上游仓库最新插件替换 vendor\dsh-whale-widget（以后升级插件只需跑这个再重新构建）。
param(
    [string]$Ref = 'main',
    [string]$Repo = 'MeteorNOX/DeepSeek-Balance-Whale-Widget'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Vendor = Join-Path $Root 'vendor\dsh-whale-widget'
$Temp = Join-Path $env:TEMP ("whalepet-plugin-{0}" -f ([guid]::NewGuid().ToString('N').Substring(0, 8)))
New-Item -ItemType Directory -Force -Path $Temp | Out-Null
$tarball = Join-Path $Temp 'plugin.tar.gz'
$ProgressPreference = 'SilentlyContinue'

$urls = @(
    "https://ghfast.top/https://codeload.github.com/$Repo/tar.gz/refs/heads/$Ref",
    "https://codeload.github.com/$Repo/tar.gz/refs/heads/$Ref"
)
$ok = $false
foreach ($url in $urls) {
    try {
        Write-Host "==> 下载 $url"
        Invoke-WebRequest $url -OutFile $tarball -UseBasicParsing -TimeoutSec 300
        $ok = $true
        break
    } catch {
        Write-Host "    失败：$($_.Exception.Message)"
    }
}
if (-not $ok) { throw '插件下载失败' }

# 解包只用标准库，任何 Python 3.8+ 都行：优先仓库 venv，其次系统 python
$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $found = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $found) { $found = (Get-Command py -ErrorAction SilentlyContinue).Source }
    if (-not $found) { throw '需要 Python 3.8+ 解包插件：请先装 Python，或先跑 build.ps1 创建 .venv' }
    $python = $found
}
& $python (Join-Path $Root 'scripts\extract_plugin.py') $tarball $Vendor
$pkg = Get-Content (Join-Path $Vendor 'package.json') -Raw | ConvertFrom-Json
Write-Host "==> 当前插件版本：$($pkg.version)"
Write-Host '==> 记得同步 src\whalepet\__init__.py 的 PLUGIN_VERSION，再重跑 build.ps1 / build-dist.ps1'
