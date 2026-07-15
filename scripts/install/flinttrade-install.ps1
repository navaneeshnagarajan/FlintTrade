# FlintTrade desktop installer / updater (Windows)
#
# Default mode downloads and runs the published FlintTrade NSIS setup.exe for
# Windows x64. Source builds remain available with -BuildFromSource for
# contributors who intentionally want the Git/Rust/Node/Python/Tauri toolchain.
#
#   irm https://flinttrade.vercel.app/install.ps1 | iex
#   $env:FLINTTRADE_BUILD_FROM_SOURCE = "1"; irm https://flinttrade.vercel.app/install.ps1 | iex

param(
    [string]$Channel = $(if ($env:FLINTTRADE_CHANNEL) { $env:FLINTTRADE_CHANNEL } else { "beta" }),
    [string]$Ref = $env:FLINTTRADE_REF,
    [string]$SrcDir = $(if ($env:FLINTTRADE_SRC_DIR) { $env:FLINTTRADE_SRC_DIR } else { Join-Path $HOME ".flinttrade\src\FlintTrade" }),
    [switch]$BuildFromSource = ($env:FLINTTRADE_BUILD_FROM_SOURCE -eq "1"),
    [switch]$NoLaunch = ($env:FLINTTRADE_NO_LAUNCH -eq "1"),
    [switch]$Yes = ($env:FLINTTRADE_YES -eq "1"),
    [switch]$DryRun = ($env:FLINTTRADE_DRY_RUN -eq "1")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoUrl = "https://github.com/navaneeshnagarajan/FlintTrade.git"
$PinnedPnpmVersion = if ($env:FLINTTRADE_PNPM_VERSION) { $env:FLINTTRADE_PNPM_VERSION } else { "9.15.0" }
# Release metadata comes straight from the official GitHub release-download
# path: every release ships a flinttrade-desktop-manifest.json asset, and the
# rolling updater-beta / updater-stable releases always point at the newest
# release of that channel. FLINTTRADE_DESKTOP_RELEASE_API is a test/advanced
# override used verbatim as the manifest URL.
$ReleaseDownloadBase = "https://github.com/navaneeshnagarajan/FlintTrade/releases/download"
$ManifestAssetName = "flinttrade-desktop-manifest.json"
$ManifestOverrideUrl = $env:FLINTTRADE_DESKTOP_RELEASE_API

function Say([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "[flinttrade] ERROR: $Message" -ForegroundColor Red; exit 1 }
function Have([string]$Command) { $null -ne (Get-Command $Command -ErrorAction SilentlyContinue) }

function Invoke-Pnpm {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )
    if (Have corepack) {
        & corepack pnpm @Args
        return
    }
    if (Have pnpm) {
        $version = (pnpm --version 2>$null).Trim()
        if ($version -eq $PinnedPnpmVersion) {
            & pnpm @Args
            return
        }
    }
    if (Have npx) {
        & npx --yes "pnpm@$PinnedPnpmVersion" @Args
        return
    }
    Fail "pnpm $PinnedPnpmVersion is required. Install Node's npx/corepack or a matching pnpm binary."
}

function Consent([string]$Question) {
    if ($Yes) { return $true }
    if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        $answer = Read-Host "$Question [y/N]"
        return $answer -eq "y" -or $answer -eq "Y"
    }
    return $false
}

function Invoke-OrDryRun {
    param(
        [string]$Description,
        [scriptblock]$Action
    )
    if ($DryRun) {
        Say "DRY-RUN: $Description"
    } else {
        & $Action
    }
}

function Get-WindowsArch {
    try {
        $proc = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
        switch ([int]$proc.Architecture) {
            12 { return "arm64" }
            9 { return "x64" }
            0 { return "x86" }
        }
    } catch {
        # Fall back below.
    }
    switch ($env:PROCESSOR_ARCHITEW6432) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
    }
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "ARM64" { return "arm64" }
        "AMD64" { return "x64" }
        "x86" { return "x86" }
        default { if ([Environment]::Is64BitOperatingSystem) { return "x64" } else { return "x86" } }
    }
}

function Get-ManifestUrl {
    if ($ManifestOverrideUrl) {
        return $ManifestOverrideUrl
    }
    if ($Ref) {
        return "$ReleaseDownloadBase/$Ref/$ManifestAssetName"
    }
    return "$ReleaseDownloadBase/updater-$Channel/$ManifestAssetName"
}

function Get-ReleaseAsset {
    $arch = Get-WindowsArch
    if ($arch -ne "x64") {
        Fail "The current release publishes Windows x64 installers only. Detected: $arch."
    }
    $url = Get-ManifestUrl
    Say "Resolving FlintTrade desktop release ($url)..."
    try {
        $manifest = Invoke-RestMethod -Uri $url -Headers @{ Accept = "application/json" }
    } catch {
        Fail "Could not fetch the desktop release manifest: $($_.Exception.Message)"
    }
    if ($manifest.PSObject.Properties.Name -contains "warning") {
        Fail "The release manifest endpoint returned a fallback warning; refusing to install from stale metadata."
    }
    if ($manifest.PSObject.Properties.Name -contains "error") {
        Fail "The release manifest endpoint returned an error; refusing to install."
    }
    $asset = $manifest.assets | Where-Object {
        $_.os -eq "windows" -and $_.arch -eq "x64" -and $_.kind -eq "nsis"
    } | Select-Object -First 1
    if (-not $asset) {
        Fail "No Windows x64 setup.exe installer was found in the selected release."
    }
    return $asset
}

function Install-BinaryRelease {
    if ($Channel -ne "beta" -and $Channel -ne "stable") {
        Fail "-Channel must be beta or stable."
    }
    $asset = Get-ReleaseAsset
    # The downloaded file is executed, so it MUST come from the official
    # repository's release-download path — never a host a tampered manifest chose.
    $trustedPrefix = "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/"
    if (-not ([string]$asset.url).StartsWith($trustedPrefix)) {
        Fail "Refusing asset URL outside the official release path: $($asset.url)"
    }
    $installer = Join-Path ([System.IO.Path]::GetTempPath()) $asset.name
    if ($DryRun) {
        Say "DRY-RUN: would download $($asset.name)"
        Say "DRY-RUN: $($asset.url)"
        if ($asset.sha256) { Say "DRY-RUN: would verify sha256 $($asset.sha256)" }
        Say "DRY-RUN: would run $installer"
        return
    }
    Say "Downloading $($asset.name)..."
    Invoke-WebRequest -Uri $asset.url -OutFile $installer -UseBasicParsing
    if ($asset.sha256) {
        $actualHash = (Get-FileHash -Algorithm SHA256 -Path $installer).Hash.ToLowerInvariant()
        $expectedHash = ([string]$asset.sha256).ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            Fail "Checksum mismatch for $($asset.name). Expected $expectedHash, got $actualHash."
        }
        Say "Verified SHA-256 checksum."
    }
    Say "Running FlintTrade setup..."
    if ($NoLaunch) {
        Start-Process -FilePath $installer -ArgumentList "/S" -Wait
    } else {
        Start-Process -FilePath $installer -Wait
    }
    Say "Done. To update later, rerun this installer or use Settings -> Updates."
}

function Build-FromSource {
    Say "Source-build mode enabled. Checking build prerequisites..."
    $missing = @()

    if (-not (Have git)) { $missing += "git - winget install Git.Git" }
    if (-not (Have cargo)) {
        $missing += "Rust stable (MSVC) - winget install Rustlang.Rustup; install Visual Studio Build Tools C++ workload"
    }
    if (Have node) {
        $nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
        if ($nodeMajor -lt 22) { $missing += "Node.js >= 22 (found $(node --version)) - winget install OpenJS.NodeJS" }
    } else {
        $missing += "Node.js >= 22 - winget install OpenJS.NodeJS"
    }
    if (-not (Have uv)) {
        if (Consent "uv is missing. Install it now (user-local, from astral.sh)?") {
            Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
            $env:Path = "$HOME\.local\bin;$env:Path"
            if (-not (Have uv)) { Fail "uv installed but is not on PATH. Restart the terminal and rerun." }
        } else {
            $missing += "uv - irm https://astral.sh/uv/install.ps1 | iex"
        }
    }
    $hasPinnedPnpm = $false
    if (Have pnpm) {
        $hasPinnedPnpm = ((pnpm --version 2>$null).Trim() -eq $PinnedPnpmVersion)
    }
    if (-not (Have corepack) -and -not (Have npx) -and -not $hasPinnedPnpm) {
        $missing += "pnpm $PinnedPnpmVersion - install Node's npx/corepack or a matching pnpm binary"
    }

    $gitBash = Join-Path $env:ProgramFiles "Git\bin\bash.exe"
    if (-not (Test-Path $gitBash)) {
        $gitBashAlt = Join-Path ${env:ProgramFiles(x86)} "Git\bin\bash.exe"
        if (Test-Path $gitBashAlt) { $gitBash = $gitBashAlt } else { $missing += "Git Bash - winget install Git.Git" }
    }

    if ($missing.Count -gt 0) {
        Warn "Missing source-build prerequisites:"
        $missing | ForEach-Object { Warn "  - $_" }
        Fail "Install the tools above, then rerun with -BuildFromSource."
    }

    if ($DryRun) {
        $target = if ($Ref) { $Ref } else { "latest release tag" }
        Say "DRY-RUN: source build would clone/update $RepoUrl at $target"
        Say "DRY-RUN: source build would run uv sync, install PyInstaller, pnpm $PinnedPnpmVersion install, build the backend sidecar, and build the Tauri bundle"
        return
    }

    if (-not $Ref) {
        Say "Resolving newest release tag from GitHub..."
        # Newest by version core, then a STABLE release must outrank its own
        # prerelease at the same version (v1.2.3 > v1.2.3-beta.1). PowerShell's
        # Sort-Object is ordinary string comparison, so the sh script's '~' trick
        # (filevercmp-specific) does NOT apply here; instead a secondary boolean
        # key sorts stable ($true) last. A newer prerelease still beats an older
        # stable because the version core is the primary key.
        $tags = git ls-remote --tags --refs $RepoUrl "v*" |
            ForEach-Object { ($_ -split "/")[-1] } |
            Sort-Object `
                { [version]((($_ -replace "^v", "") -split "-", 2)[0]) }, `
                { -not ($_ -match "-") }, `
                { $_ }
        $script:Ref = $tags | Select-Object -Last 1
        if (-not $Ref) { Fail "Could not resolve a release tag from $RepoUrl" }
    }
    Say "Target version: $Ref"

    if (Test-Path (Join-Path $SrcDir ".git")) {
        Say "Updating source workspace at $SrcDir..."
        git -C $SrcDir fetch --tags origin
        git -C $SrcDir checkout --quiet $Ref
    } else {
        Say "Cloning FlintTrade ($Ref) into $SrcDir..."
        New-Item -ItemType Directory -Force -Path (Split-Path $SrcDir) | Out-Null
        git clone --branch $Ref --depth 1 $RepoUrl $SrcDir
    }
    Set-Location $SrcDir

    Say "Installing Python dependencies..."
    uv sync
    uv pip install pyinstaller
    Say "Installing JS workspace dependencies..."
    Invoke-Pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { Fail "pnpm install failed." }
    Say "Freezing backend sidecar..."
    & $gitBash "packaging/build-backend.sh"
    if ($LASTEXITCODE -ne 0) { Fail "Backend sidecar build failed." }
    Say "Building the Tauri bundle..."
    Push-Location "packages\apps\desktop"
    Invoke-Pnpm tauri build
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Tauri build failed." }
    Pop-Location

    $bundle = Join-Path $SrcDir "packages\apps\desktop\src-tauri\target\release\bundle\nsis"
    $installer = Get-ChildItem -Path $bundle -Filter "*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $installer) { Fail "Build finished but no NSIS installer found under $bundle" }
    Say "Built: $($installer.FullName)"
    if (-not $NoLaunch) {
        Start-Process -FilePath $installer.FullName -Wait
    }
}

if ($BuildFromSource) {
    Build-FromSource
} else {
    Install-BinaryRelease
}
