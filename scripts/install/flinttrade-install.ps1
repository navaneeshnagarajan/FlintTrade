# =============================================================================
# FlintTrade — bootstrap installer / updater (Windows)
# =============================================================================
#
# Fetches the latest FlintTrade release tag from GitHub, builds the native
# desktop app ON THIS MACHINE (backend sidecar + Tauri bundle), and runs the
# resulting installer. Because the binary is built locally there is no
# unsigned-installer warning and nothing to trust beyond readable source.
#
#   irm https://flinttrade.vercel.app/install.ps1 | iex
#
# Re-running the same command updates an existing install (fetch newest tag,
# rebuild in the same source workspace). The in-app updater calls this too.
#
# Parameters (set as environment variables when piping through iex):
#   $env:FLINTTRADE_REF       build a specific tag/branch (default: newest v*)
#   $env:FLINTTRADE_SRC_DIR   source workspace (default: ~\.flinttrade\src\FlintTrade)
#   $env:FLINTTRADE_YES       "1" = consent to auto-installing uv/pnpm (user-local)
#   $env:FLINTTRADE_NO_LAUNCH "1" = do not run the built installer at the end
#   $env:FLINTTRADE_SKIP_IF_CURRENT "1" = exit early when already on the newest tag
#
# It never elevates silently and never installs system packages without
# printing exactly what it would run. First build: ~10-20 min, ~4 GB of
# toolchain + build artefacts.
# =============================================================================

$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/navaneeshnagarajan/FlintTrade.git'
$SrcDir  = if ($env:FLINTTRADE_SRC_DIR) { $env:FLINTTRADE_SRC_DIR } else { Join-Path $HOME '.flinttrade\src\FlintTrade' }
$Ref     = $env:FLINTTRADE_REF
$Yes     = $env:FLINTTRADE_YES -eq '1'

function Say([string]$msg)  { Write-Host "[flinttrade] $msg" -ForegroundColor Cyan }
function Warn([string]$msg) { Write-Host "[flinttrade] $msg" -ForegroundColor Yellow }
function Fail([string]$msg) { Write-Host "[flinttrade] ERROR: $msg" -ForegroundColor Red; exit 1 }

function Have([string]$cmd) { $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Consent([string]$question) {
    if ($Yes) { return $true }
    if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        $answer = Read-Host "$question [y/N]"
        return $answer -eq 'y' -or $answer -eq 'Y'
    }
    return $false
}

# --- prerequisites -----------------------------------------------------------
Say 'Checking build prerequisites...'
$missing = @()

if (-not (Have git))  { $missing += 'git — winget install Git.Git' }
if (-not (Have cargo)) { $missing += 'Rust (stable, MSVC) — winget install Rustlang.Rustup ; rustup default stable-msvc. Rust on Windows also needs the Visual Studio Build Tools C++ workload: winget install Microsoft.VisualStudio.2022.BuildTools' }

if (Have node) {
    $nodeMajor = [int]((node --version).TrimStart('v').Split('.')[0])
    if ($nodeMajor -lt 22) { $missing += "Node.js >= 22 (found $(node --version)) — winget install OpenJS.NodeJS" }
} else {
    $missing += 'Node.js >= 22 — winget install OpenJS.NodeJS'
}

if (-not (Have uv)) {
    if (Consent 'uv (Python package manager) is missing. Install it now (user-local, from astral.sh)?') {
        Say 'Installing uv...'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $env:Path = "$HOME\.local\bin;$env:Path"
        if (-not (Have uv)) { Fail 'uv installed but not on PATH — restart the terminal and re-run.' }
    } else {
        $missing += 'uv — irm https://astral.sh/uv/install.ps1 | iex   (or set FLINTTRADE_YES=1)'
    }
}

if (-not (Have pnpm)) {
    if ((Have corepack) -and (Consent 'pnpm is missing. Enable it via Node''s corepack (user-local)?')) {
        Say 'Enabling pnpm via corepack...'
        corepack enable pnpm
        if (-not (Have pnpm)) { $missing += 'pnpm — corepack did not expose it; see https://pnpm.io/installation' }
    } else {
        $missing += 'pnpm — corepack enable pnpm   (ships with Node 22; or set FLINTTRADE_YES=1)'
    }
}

# Git Bash is required by packaging/build-backend.sh; it ships with Git for Windows.
$gitBash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
if (-not (Test-Path $gitBash)) {
    $gitBashAlt = Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe'
    if (Test-Path $gitBashAlt) { $gitBash = $gitBashAlt }
    else { $missing += 'Git Bash (ships with Git for Windows) — winget install Git.Git' }
}

if ($missing.Count -gt 0) {
    Warn 'Missing prerequisites:'
    $missing | ForEach-Object { Warn "  - $_" }
    Fail 'Install the tools above, then re-run this command.'
}
Say 'All prerequisites present.'

# --- resolve version -----------------------------------------------------------
if (-not $Ref) {
    Say 'Resolving the newest release tag from GitHub...'
    $tags = git ls-remote --tags --refs $RepoUrl 'v*' |
        ForEach-Object { ($_ -split '/')[-1] } |
        Sort-Object { [version]((($_ -replace '^v', '') -split '-')[0]) }, { $_ }
    $Ref = $tags | Select-Object -Last 1
    if (-not $Ref) { Fail "Could not resolve a release tag from $RepoUrl" }
}
Say "Target version: $Ref"

# --- clone or update -----------------------------------------------------------
if (Test-Path (Join-Path $SrcDir '.git')) {
    Say "Updating existing source workspace at $SrcDir..."
    git -C $SrcDir fetch --tags origin
    $current = git -C $SrcDir describe --tags --exact-match 2>$null
    if ($current -eq $Ref) {
        if ($env:FLINTTRADE_SKIP_IF_CURRENT -eq '1') { Say "Already on $Ref — nothing to update."; exit 0 }
        Say "Source already at $Ref — rebuilding (a rebuild is idempotent)."
    }
    git -C $SrcDir checkout --quiet $Ref
} else {
    Say "Cloning FlintTrade ($Ref) into $SrcDir..."
    New-Item -ItemType Directory -Force -Path (Split-Path $SrcDir) | Out-Null
    git clone --branch $Ref --depth 1 $RepoUrl $SrcDir
}
Set-Location $SrcDir

# --- build ---------------------------------------------------------------------
Say 'Installing Python dependencies (uv sync)...'
uv sync
Say 'Ensuring PyInstaller is available...'
uv pip install pyinstaller
Say 'Installing JS workspace dependencies (pnpm)...'
pnpm install --frozen-lockfile
Say 'Freezing the backend sidecar (via Git Bash)...'
& $gitBash 'packaging/build-backend.sh'
if ($LASTEXITCODE -ne 0) { Fail 'Backend sidecar build failed — see the output above.' }
Say 'Building the Tauri bundle — this is the long step...'
Push-Location 'packages\apps\desktop'
pnpm tauri build
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail 'Tauri build failed — see the output above.' }
Pop-Location

# --- install -------------------------------------------------------------------
$bundle = Join-Path $SrcDir 'packages\apps\desktop\src-tauri\target\release\bundle\nsis'
$installer = Get-ChildItem -Path $bundle -Filter '*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installer) { Fail "Build finished but no NSIS installer found under $bundle" }

Say "Built: $($installer.FullName) ($Ref)"
if ($env:FLINTTRADE_NO_LAUNCH -eq '1') {
    Say 'Skipping installer launch (FLINTTRADE_NO_LAUNCH=1). Run it yourself when ready.'
} else {
    Say 'Running the installer...'
    Start-Process -FilePath $installer.FullName -Wait
}

Say 'Done. To update later, re-run the same command — it fetches the newest'
Say "tag into $SrcDir and rebuilds."
