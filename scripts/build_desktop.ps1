<#
.SYNOPSIS
    Build RAG Simple desktop executable (PyInstaller + PyWebView)

.DESCRIPTION
    Package RAG Simple as rag-simple.exe with a native Windows window.
    Frontend is built via npm first, then bundled with Python backend.

    Usage:
        .\scripts\build_desktop.ps1           # full build
        .\scripts\build_desktop.ps1 -NoBuild   # skip frontend build

    Output: build/rag-simple/
#>

param(
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Get-Item $PSScriptRoot).Parent.FullName
$DistDir = Join-Path $ProjectRoot "dist"
$OutDir = Join-Path $ProjectRoot "build/rag-simple"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  RAG Simple Desktop Build" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ---- detect Python ----

$python = ""
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $python = "python"
} elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $python = "python3"
} else {
    throw "Python not found, please install Python 3.11+"
}

Write-Host "[1/4] Checking environment..." -ForegroundColor Yellow
& $python --version

$uvExists = $null -ne (Get-Command "uv" -ErrorAction SilentlyContinue)

# ---- frontend build ----

if (-not $NoBuild) {
    Write-Host "[2/4] Building frontend..." -ForegroundColor Yellow
    $webDir = Join-Path $ProjectRoot "web"
    if (Test-Path (Join-Path $webDir "package.json")) {
        Push-Location $webDir
        try {
            $lockPath = Join-Path $webDir "node_modules/.package-lock.json"
            if (-not (Test-Path $lockPath -PathType Leaf)) {
                Write-Host "     installing npm dependencies..."
                npm install
            }
            Write-Host "     building for production..."
            npm run build
            Write-Host "     frontend build done" -ForegroundColor Green
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "     skipped: web/package.json not found" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "[2/4] Skipping frontend build (-NoBuild)" -ForegroundColor DarkYellow
}

$indexPath = Join-Path $DistDir "index.html"
if (-not (Test-Path $indexPath)) {
    Write-Host "     [WARN] Frontend build not found at $DistDir" -ForegroundColor Red
}

# ---- check deps ----

Write-Host "[3/4] Checking build dependencies..." -ForegroundColor Yellow
$needInstall = $false
try {
    & $python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "missing PyInstaller" }
    & $python -c "import webview" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "missing webview" }
    Write-Host "     PyInstaller + PyWebView ready" -ForegroundColor Green
} catch {
    $needInstall = $true
}
if ($needInstall) {
    Write-Host "     installing PyInstaller and PyWebView..."
    if ($uvExists) {
        uv pip install pyinstaller pywebview --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    } else {
        pip install pyinstaller pywebview
    }
}

# ---- generate icon (已存在,跳过) ----

# ---- PyInstaller pack ----

Write-Host "[4/4] Running PyInstaller..." -ForegroundColor Yellow
# 先杀掉残留的 rag-simple.exe 进程，释放文件锁
$prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& taskkill /f /im rag-simple.exe 2>&1 | Out-Null
$ErrorActionPreference = $prev
Start-Sleep -Seconds 1
# 清理旧的构建目录（避免 Junction 导致权限问题）
$oldBuild = Join-Path $ProjectRoot "build/rag-simple"
if (Test-Path $oldBuild) { Remove-Item $oldBuild -Recurse -Force }
Push-Location $ProjectRoot
try {
    & $python -m PyInstaller --clean --noconfirm --distpath build desktop.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed (exit code: $LASTEXITCODE)"
    }
    # 复制配置/提示词到 exe 同目录
    Copy-Item (Join-Path $ProjectRoot "config.ini") (Join-Path $OutDir "config.ini") -Force
    Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $OutDir ".env.example") -Force
    Copy-Item (Join-Path $ProjectRoot "prompts") (Join-Path $OutDir "prompts") -Recurse -Force
    # 前端构建产物：直接放 exe 同级（不套 dist/ 层级）
    Copy-Item (Join-Path $ProjectRoot "dist/index.html") (Join-Path $OutDir "index.html") -Force
    Copy-Item (Join-Path $ProjectRoot "dist/assets") (Join-Path $OutDir "assets") -Recurse -Force
    Copy-Item (Join-Path $ProjectRoot "dist/favicon.*") (Join-Path $OutDir "") -Force
    # _internal/dist 放一份前端文件副本，app.py 的 os.path.dirname(__file__) 相对路径找资源用
    $internalDist = Join-Path $OutDir "_internal/dist"
    if (Test-Path $internalDist) { Remove-Item $internalDist -Recurse -Force }
    New-Item -ItemType Directory -Path $internalDist -Force | Out-Null
    Copy-Item (Join-Path $OutDir "index.html") (Join-Path $internalDist "index.html") -Force
    Copy-Item (Join-Path $OutDir "assets") (Join-Path $internalDist "assets") -Recurse -Force
    Copy-Item (Join-Path $OutDir "favicon.*") (Join-Path $internalDist "") -Force
    # _internal/ 里的模块通过 __file__ 找同级目录文件
    Copy-Item (Join-Path $ProjectRoot "config.ini") (Join-Path $OutDir "_internal/config.ini") -Force
    Copy-Item (Join-Path $ProjectRoot "prompts") (Join-Path $OutDir "_internal/prompts") -Recurse -Force
    $exePath = Join-Path $OutDir "rag-simple.exe"
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "  BUILD SUCCESSFUL" -ForegroundColor Green
    Write-Host "  Output: $exePath" -ForegroundColor Green
    if (Test-Path $exePath) {
        $size = (Get-ChildItem $exePath).Length / 1MB
        Write-Host ("  Size: {0:N1} MB" -f $size) -ForegroundColor Green
    }
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "To distribute:" -ForegroundColor White
    Write-Host "  1. Copy build/rag-simple/ to target machine" -ForegroundColor White
    Write-Host "  2. Place config.ini next to rag-simple.exe" -ForegroundColor White
    Write-Host "  3. Double-click rag-simple.exe to start" -ForegroundColor White
} catch {
    Write-Host ("Build FAILED: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
