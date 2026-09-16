# 构建"可以直接发给别人"的干净分发包。
#   .\build-dist.ps1              先构建再打包
#   .\build-dist.ps1 -SkipBuild   直接用现有 dist\WhalePet.exe 打包
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$DistDir = Join-Path $Root 'dist'

if (-not $SkipBuild) {
    & (Join-Path $Root 'build.ps1') -SkipDeps
}

$exe = Join-Path $DistDir 'WhalePet.exe'
if (-not (Test-Path $exe)) { throw '找不到 dist\WhalePet.exe，先跑 build.ps1' }

Write-Host '==> 校验产物（不含个人数据/密钥）'
& $Python (Join-Path $Root 'scripts\verify_dist.py')
if ($LASTEXITCODE -ne 0) { throw '分发校验未通过，已中止' }

$version = (& $Python -c "import sys; sys.path.insert(0, r'$Root\src'); from whalepet import APP_VERSION; print(APP_VERSION)").Trim()
$staging = Join-Path $Root "build\dist-$version"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

Copy-Item $exe (Join-Path $staging 'WhalePet.exe')
Copy-Item (Join-Path $Root 'README.md') (Join-Path $staging 'README.md')
Copy-Item (Join-Path $Root 'scripts\quickstart.txt') (Join-Path $staging '使用说明.txt')
Copy-Item (Join-Path $Root 'vendor\dsh-whale-widget\LICENSE') (Join-Path $staging 'LICENSE-dsh-whale-widget.txt')

$zip = Join-Path $DistDir "WhalePet-$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zip -CompressionLevel Optimal

$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "==> 分发包：$zip（$size MB）"
Write-Host '    内容：WhalePet.exe / 使用说明.txt / README.md / LICENSE-dsh-whale-widget.txt'
