# 构建 WhalePet.exe（单文件、无控制台）。
#   .\build.ps1              正常构建
#   .\build.ps1 -SkipDeps    跳过依赖安装
param(
    [switch]$SkipDeps
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'

Write-Host "==> 项目目录：$Root"

if (-not (Test-Path $Python)) {
    Write-Host '==> 创建虚拟环境 .venv'
    $base = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $base) { $base = (Get-Command py -ErrorAction SilentlyContinue).Source }
    if (-not $base) { throw '需要 Python 3.12+ 来创建构建环境：请先安装 Python 并确保 python 在 PATH 里' }
    & $base -m venv (Join-Path $Root '.venv')
}

if (-not $SkipDeps) {
    Write-Host '==> 安装依赖（PySide6 / PyInstaller / pytest）'
    & $Python -m pip install --quiet --disable-pip-version-check --index-url $Mirror `
        --trusted-host pypi.tuna.tsinghua.edu.cn 'PySide6==6.11.2' 'pyinstaller==6.22.3' pytest requests
}

if (-not (Test-Path (Join-Path $Root 'runtime\node\node.exe'))) {
    throw '缺少 runtime\node\node.exe：请先跑 scripts\fetch_node.ps1 下载 Node LTS'
}

if (-not (Test-Path (Join-Path $Root 'vendor\dsh-whale-widget\lib\index.js'))) {
    throw '缺少插件本体（vendor\dsh-whale-widget）：请先跑 scripts\sync-plugin.ps1 从上游拉取'
}

Write-Host '==> 生成版本资源'
& $Python (Join-Path $Root 'scripts\make_version_info.py')

Write-Host '==> 生成图标'
& $Python (Join-Path $Root 'scripts\make_icon.py')

Write-Host '==> 打 payload.zip（node + 插件本体）'
& $Python (Join-Path $Root 'scripts\make_payload.py')

Write-Host '==> PyInstaller 打包'
Push-Location $Root
try {
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $Root 'WhalePet.spec')
} finally {
    Pop-Location
}

$exe = Join-Path $Root 'dist\WhalePet.exe'
if (-not (Test-Path $exe)) { throw '打包失败：没有生成 dist\WhalePet.exe' }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "==> 完成：$exe（$size MB）"
