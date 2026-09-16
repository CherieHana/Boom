# 下载 Node LTS（win-x64）并抽出 node.exe 到 runtime\node\node.exe
param(
    [string]$Version = 'v22.20.0'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Target = Join-Path $Root 'runtime\node'
$Zip = Join-Path $Root ("runtime\node-{0}-win-x64.zip" -f $Version)
$Url = "https://registry.npmmirror.com/-/binary/node/{0}/node-{0}-win-x64.zip" -f $Version

New-Item -ItemType Directory -Force -Path $Target | Out-Null
if (Test-Path (Join-Path $Target 'node.exe')) {
    Write-Host "==> 已存在：$(Join-Path $Target 'node.exe')"
    exit 0
}

Write-Host "==> 下载 $Url"
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest $Url -OutFile $Zip -UseBasicParsing -TimeoutSec 600

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($Zip)
try {
    $entry = $archive.Entries | Where-Object { $_.FullName -eq "node-$Version-win-x64/node.exe" }
    if (-not $entry) { throw '压缩包里没有 node.exe' }
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $Target 'node.exe'), $true)
} finally {
    $archive.Dispose()
}
Remove-Item $Zip -Force -ErrorAction SilentlyContinue
Write-Host "==> 完成：$(Join-Path $Target 'node.exe')"
