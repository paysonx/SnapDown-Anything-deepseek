# 注意：本文件必须保存为「UTF-8 带 BOM」。Windows PowerShell 5.1 会按系统 ANSI 代码页
#       读取无 BOM 的脚本，中文字符会被拆坏，报 "Unexpected token" / "字符串缺少终止符"。
#
# SnapDown-Anything 一键启动：建 venv → 装依赖 → 构建前端 → 启动服务
#
# 用法：
#   .\run.ps1                       # 默认 http://127.0.0.1:8787
#   .\run.ps1 -Port 9000            # 换端口
#   .\run.ps1 -Rebuild              # 强制重新构建前端
#   .\run.ps1 -SkipInstall          # 跳过依赖安装（已装好时更快）
#
# 若提示「未对文件进行数字签名 … 无法在当前系统上运行该脚本」，用下面任一方式：
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#   Set-ExecutionPolicy -Scope Process Bypass    # 仅对当前终端会话生效
[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8787,
    [switch]$Rebuild,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Write-Step($text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

# 1. 虚拟环境
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Step "创建虚拟环境 .venv"
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "未找到 python，请安装 Python 3.11+ 并加入 PATH"
    }
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败（退出码 $LASTEXITCODE）" }
}

# 2. 依赖
if (-not $SkipInstall) {
    Write-Step "安装 Python 依赖"
    & $python -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败（退出码 $LASTEXITCODE）" }
}

# 3. 前端：产物缺失或显式要求时才构建
$dist = Join-Path $root "web\dist\index.html"
if ($Rebuild -or -not (Test-Path $dist)) {
    Write-Step "构建前端（web/dist）"
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        throw "未找到 pnpm，请安装 Node.js 20+ 后执行：npm i -g pnpm"
    }
    Push-Location (Join-Path $root "web")
    try {
        & pnpm install
        if ($LASTEXITCODE -ne 0) { throw "pnpm install 失败（退出码 $LASTEXITCODE）" }
        & pnpm build
        if ($LASTEXITCODE -ne 0) { throw "pnpm build 失败（退出码 $LASTEXITCODE）" }
    }
    finally {
        Pop-Location
    }
}

# 4. 启动（前台运行，Ctrl+C 停止）
Write-Step "启动服务：http://${HostAddress}:${Port}"
$env:HOST = $HostAddress
$env:PORT = "$Port"
# Windows 控制台默认不是 UTF-8，中文日志会乱码
$env:PYTHONUTF8 = "1"
& $python -m uvicorn app.main:app --host $HostAddress --port $Port
