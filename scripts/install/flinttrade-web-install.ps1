# FlintTrade one-line web-app installer (Windows 10/11)
#
# Installs the FlintTrade web app on a bare machine with no prerequisites at
# all: no uv, no Python, no Node, no pnpm, no git and no make. Every tool is
# downloaded from its pinned URL, SHA-256 verified against the repository's own
# bootstrap tool manifest, and confined to ~\.flinttrade\tools. The build itself
# is delegated to the repository's packaged bootstrap entrypoint so this
# installer never duplicates the uv/pnpm build behaviour.
#
#   irm https://flinttrade.vercel.app/web-install.ps1 | iex
#
# Uninstall:
#   irm https://flinttrade.vercel.app/uninstall.ps1 | iex
#
# Written for stock Windows PowerShell 5.1: no '&&', no ternary, no '??'.

param(
    [string]$Ref = $env:FLINTTRADE_REF,
    [string]$SrcDir = "",
    [switch]$Yes = ($env:FLINTTRADE_YES -eq "1"),
    [switch]$DryRun = ($env:FLINTTRADE_DRY_RUN -eq "1"),
    [switch]$NoLaunch = ($env:FLINTTRADE_NO_LAUNCH -eq "1"),
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoSlug = "navaneeshnagarajan/FlintTrade"
$RepoUrl = "https://github.com/$RepoSlug.git"
$ArchiveBaseUrl = "https://codeload.github.com/$RepoSlug/zip"
$DefaultBranch = "main"
$PinnedPnpmVersion = "9.15.0"
$BackendUrl = "http://127.0.0.1:5100"
$UninstallCommand = "irm https://flinttrade.vercel.app/uninstall.ps1 | iex"
$ManagedRoot = Join-Path $HOME ".flinttrade"
$ToolsRoot = Join-Path $ManagedRoot "tools"
# The Electron desktop shell resolves exactly these two paths
# (packages\apps\desktop\electron\paths.ts) and guards every mutation of the
# active source with an operation lease directory created by its bootstrap
# (packages\apps\desktop\electron\bootstrap.ts).
$DesktopSourceRoot = Join-Path $ManagedRoot "src"
$DesktopActiveSource = Join-Path $DesktopSourceRoot "FlintTrade"
$DesktopOperationLease = Join-Path $DesktopSourceRoot ".flinttrade-bootstrap-operation.lock"
$ManifestRelative = "packages\apps\desktop\resources\bootstrap\tool-manifest.json"
$BootstrapRelative = "packages\apps\desktop\resources\bootstrap\flinttrade-bootstrap.ps1"
$LocalAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$RoamingAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
$ShimDir = Join-Path $LocalAppDataRoot "Programs\FlintTrade"
$ShimPath = Join-Path $ShimDir "flinttrade.cmd"
$StartMenuDir = Join-Path $RoamingAppDataRoot "Microsoft\Windows\Start Menu\Programs\FlintTrade"
$StartMenuShortcut = Join-Path $StartMenuDir "FlintTrade.lnk"
# Owner-private receipt for everything this installer writes outside the managed
# root. The uninstaller may only delete what an installer proved it created.
$WebReceiptDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "flinttrade-web" } else { "" }
$WebReceiptPath = if ($WebReceiptDir) { Join-Path $WebReceiptDir "web-install.receipt" } else { "" }

# The allow-list constrains every URL this installer requests. GitHub redirects
# release assets on to its own object CDN, so integrity is enforced by the
# SHA-256 verification below rather than by the redirect target's hostname.
$AllowedHosts = @(
    "codeload.github.com",
    "github.com",
    "api.github.com",
    "nodejs.org",
    "registry.npmjs.org"
)

$script:Target = ""
$script:SrcDir = ""
$script:SrcDirSource = "default"
$script:HostGitVersion = ""
$script:HostUvVersion = ""
$script:HostNodeVersion = ""
$script:HostPnpmVersion = ""
$script:HostPythonVersion = ""
$script:ReuseUv = ""
$script:ReuseNode = ""
$script:ReuseCorepackJs = ""

function Say([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Yellow }
function Fail([string]$Message) {
    Write-Host "[flinttrade] ERROR: $Message" -ForegroundColor Red
    throw "[flinttrade] $Message"
}
function Have([string]$Command) { return ($null -ne (Get-Command $Command -ErrorAction SilentlyContinue)) }

function Show-Usage {
    Write-Host @"
FlintTrade one-line web-app installer (Windows 10/11)

Provisions a verified uv + Node toolchain, builds FlintTrade from a managed
source checkout, and installs a 'flinttrade' launcher. No prior tooling needed.

Flags:
  -Ref <git-ref>   Branch, tag or commit to install (default: main)
  -SrcDir <dir>    Managed WEB source checkout (default:
                   %USERPROFILE%\.flinttrade\src\FlintTrade). This is not the
                   contributor source-build checkout that flinttrade-install.ps1
                   manages at %USERPROFILE%\.flinttrade\source-build\FlintTrade.
  -Yes             Answer every confirmation with yes
  -NoLaunch        Do not offer to start FlintTrade after installing
  -DryRun          Report the plan without downloading, building or installing
  -Help            Show this help and exit

Environment overrides:
  FLINTTRADE_REF, FLINTTRADE_WEB_SRC_DIR, FLINTTRADE_YES,
  FLINTTRADE_DRY_RUN, FLINTTRADE_NO_LAUNCH

  FLINTTRADE_SRC_DIR is a deprecated fallback for FLINTTRADE_WEB_SRC_DIR here.
  flinttrade-install.ps1 reads it as the contributor source-build checkout, so
  this installer warns and asks for confirmation before managing a directory
  that only that variable supplied.

Uninstall:
  irm https://flinttrade.vercel.app/uninstall.ps1 | iex
"@
}

function Get-WorkspaceDir {
    if ($env:FLINTTRADE_WORKSPACE_DIR) { return $env:FLINTTRADE_WORKSPACE_DIR }
    if ($env:FLINTTRADE_HOME) { return $env:FLINTTRADE_HOME }
    return (Join-Path $RoamingAppDataRoot "flinttrade")
}

# ---------------------------------------------------------------------------
# 1. Operating system and CPU architecture detection
# ---------------------------------------------------------------------------

function Get-WindowsArch {
    try {
        $processor = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
        switch ([int]$processor.Architecture) {
            12 { return "arm64" }
            9 { return "x64" }
            0 { return "x86" }
        }
    } catch {
        # Fall through to environment detection.
    }
    if ($env:PROCESSOR_ARCHITEW6432 -eq "ARM64" -or $env:PROCESSOR_ARCHITECTURE -eq "ARM64") { return "arm64" }
    if ($env:PROCESSOR_ARCHITEW6432 -eq "AMD64" -or $env:PROCESSOR_ARCHITECTURE -eq "AMD64") { return "x64" }
    if ([Environment]::Is64BitOperatingSystem) { return "x64" }
    return "x86"
}

function Get-BootstrapTarget {
    $arch = Get-WindowsArch
    if ($arch -eq "x64") { return "win32-x64" }
    if ($arch -eq "arm64") {
        Fail ("The bootstrap tool manifest pins no win32-arm64 toolchain. On a Windows on ARM device, " +
              "run this installer from an x64 PowerShell session so Windows provides x64 emulation, " +
              "and it will provision the verified win32-x64 tools.")
    }
    Fail "Unsupported Windows CPU architecture '$arch'. FlintTrade requires Windows 10/11 on x64."
}

# ---------------------------------------------------------------------------
# Network guards
# ---------------------------------------------------------------------------

function Assert-TrustedUrl([string]$Url) {
    $uri = $null
    if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri)) {
        Fail "Refusing a malformed URL: $Url"
    }
    if ($uri.Scheme -ne "https") { Fail "Refusing a non-HTTPS URL: $Url" }
    if (-not ($AllowedHosts -contains $uri.Host.ToLowerInvariant())) {
        Fail "Refusing to contact '$($uri.Host)'. This installer only ever contacts: $($AllowedHosts -join ', ')"
    }
}

function Assert-Sha256Shape([string]$Value) {
    if ($Value -notmatch '^[0-9a-f]{64}$') {
        Fail "The bootstrap tool manifest holds a malformed SHA-256 digest."
    }
}

function Assert-ConfinedRelativePath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail "The bootstrap tool manifest holds an empty executable path."
    }
    if ($Value.Contains("..") -or [System.IO.Path]::IsPathRooted($Value)) {
        Fail "The bootstrap tool manifest holds an unconfined executable path: $Value"
    }
}

function Save-TrustedFile([string]$Url, [string]$Destination) {
    Assert-TrustedUrl $Url
    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    } catch {
        Fail "Download failed for ${Url}: $($_.Exception.Message)"
    }
}

function Assert-FileSha256([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        Fail "SHA-256 mismatch for $(Split-Path -Leaf $Path): expected $Expected, got $actual. The download was deleted."
    }
}

function Expand-VerifiedArchive([string]$Archive, [string]$Kind, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    }
    if ($Kind -eq "zip") {
        Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
        return
    }
    if ($Kind -eq "tar.gz") {
        if (-not (Have tar)) {
            Fail "tar.exe is required to extract $Archive on this machine."
        }
        & tar -xzf $Archive -C $Destination
        if ($LASTEXITCODE -ne 0) { Fail "Could not extract $Archive." }
        return
    }
    Fail "The bootstrap tool manifest requested an unrecognised archive kind: $Kind"
}

function Confirm-Step([string]$Prompt) {
    if ($Yes) { return $true }
    if (-not [Environment]::UserInteractive) {
        Fail "Non-interactive session: cannot ask '$Prompt'. Re-run with -Yes (or FLINTTRADE_YES=1) to confirm every step."
    }
    $answer = ""
    try {
        $answer = Read-Host "[flinttrade] $Prompt [Y/n]"
    } catch {
        Fail "Could not read a confirmation for '$Prompt'. Re-run with -Yes (or FLINTTRADE_YES=1) to confirm every step."
    }
    if ([string]::IsNullOrWhiteSpace($answer)) { return $true }
    $normalised = $answer.Trim().ToLowerInvariant()
    if ($normalised -eq "y" -or $normalised -eq "yes") { return $true }
    return $false
}

function Write-OemText([string]$Path, [string]$Content) {
    $encoding = $null
    try {
        $encoding = [System.Text.Encoding]::GetEncoding([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
    } catch {
        $encoding = [System.Text.Encoding]::ASCII
    }
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

# ---------------------------------------------------------------------------
# 2. Preflight - what is already on this machine?
# ---------------------------------------------------------------------------

function Get-ToolVersion([string]$Command, [string[]]$VersionArgs) {
    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $resolved) { return "" }
    $source = [string]$resolved.Source
    if ($source -and $source -like "*\WindowsApps\*") {
        return "Microsoft Store alias (not a usable interpreter)"
    }
    try {
        $output = & $Command @VersionArgs
    } catch {
        return ""
    }
    if (-not $output) { return "" }
    return ([string](@($output)[0])).Trim()
}

function Write-PreflightReport {
    $script:HostGitVersion = Get-ToolVersion "git" @("--version")
    $script:HostUvVersion = Get-ToolVersion "uv" @("--version")
    $script:HostNodeVersion = Get-ToolVersion "node" @("--version")
    $script:HostPnpmVersion = Get-ToolVersion "pnpm" @("--version")
    $script:HostPythonVersion = Get-ToolVersion "python" @("--version")
    if (-not $script:HostPythonVersion) {
        $script:HostPythonVersion = Get-ToolVersion "py" @("-3", "--version")
    }
    Say "Preflight - tools already present on this machine:"
    Say ("  git    : " + $(if ($script:HostGitVersion) { $script:HostGitVersion } else { "not found" }))
    Say ("  uv     : " + $(if ($script:HostUvVersion) { $script:HostUvVersion } else { "not found" }))
    Say ("  node   : " + $(if ($script:HostNodeVersion) { $script:HostNodeVersion } else { "not found" }))
    Say ("  pnpm   : " + $(if ($script:HostPnpmVersion) { $script:HostPnpmVersion } else { "not found" }))
    Say ("  python : " + $(if ($script:HostPythonVersion) { $script:HostPythonVersion } else { "not found" }))
    Say "A host tool is reused only when it matches the pinned version exactly; anything else is provisioned privately."
}

function Get-CorepackJsForNode([string]$NodeExecutable) {
    return (Join-Path (Split-Path -Parent $NodeExecutable) "node_modules\corepack\dist\corepack.js")
}

function Resolve-HostToolReuse([string]$PinnedUv, [string]$PinnedNode) {
    $script:ReuseUv = ""
    $script:ReuseNode = ""
    $script:ReuseCorepackJs = ""
    if ($script:HostUvVersion) {
        $reported = ($script:HostUvVersion -split '\s+')[1]
        if ($reported -eq $PinnedUv) {
            $script:ReuseUv = [string](Get-Command uv -ErrorAction SilentlyContinue).Source
        }
    }
    if ($script:HostNodeVersion) {
        $reported = $script:HostNodeVersion.TrimStart('v')
        if ($reported -eq $PinnedNode) {
            $candidate = [string](Get-Command node -ErrorAction SilentlyContinue).Source
            $corepackJs = Get-CorepackJsForNode $candidate
            if (Test-Path -LiteralPath $corepackJs -PathType Leaf) {
                $script:ReuseNode = $candidate
                $script:ReuseCorepackJs = $corepackJs
            } else {
                Warn "The host Node $reported matches the pin but carries no Corepack JavaScript; provisioning the verified Node instead."
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Source acquisition
# ---------------------------------------------------------------------------

function Resolve-WebSourceDir {
    # FLINTTRADE_SRC_DIR belongs to flinttrade-install.ps1, where it names the
    # contributor source-build checkout. This installer fetches, hard-resets and
    # can replace whatever directory it is given, so it owns
    # FLINTTRADE_WEB_SRC_DIR instead and only falls back to the older name
    # behind a loud warning.
    if ($SrcDir) {
        $script:SrcDir = $SrcDir
        $script:SrcDirSource = "-SrcDir"
        return
    }
    if ($env:FLINTTRADE_WEB_SRC_DIR) {
        $script:SrcDir = $env:FLINTTRADE_WEB_SRC_DIR
        $script:SrcDirSource = "FLINTTRADE_WEB_SRC_DIR"
        return
    }
    if ($env:FLINTTRADE_SRC_DIR) {
        $script:SrcDir = $env:FLINTTRADE_SRC_DIR
        $script:SrcDirSource = "FLINTTRADE_SRC_DIR"
        return
    }
    $script:SrcDir = $DesktopActiveSource
    $script:SrcDirSource = "default"
}

function Confirm-SourceDirProvenance {
    if ($script:SrcDirSource -ne "FLINTTRADE_SRC_DIR") { return }
    Warn "FLINTTRADE_SRC_DIR is set, so this installer would manage $($script:SrcDir) as its web source checkout."
    Warn "flinttrade-install.ps1 reads that same variable as the CONTRIBUTOR source-build checkout"
    Warn "(default $(Join-Path $ManagedRoot 'source-build\FlintTrade')). This installer fetches, hard-resets"
    Warn "and can replace the directory it is given - including a multi-gigabyte built checkout."
    Warn "Set FLINTTRADE_WEB_SRC_DIR, or pass -SrcDir, to choose the web source checkout explicitly."
    if ($DryRun) { return }
    if (-not (Confirm-Step "Continue with $($script:SrcDir) as the managed web source checkout?")) {
        Fail "Cancelled at the source-checkout confirmation; nothing was changed."
    }
}

function Assert-DesktopNotOperating {
    $active = ([string]$DesktopActiveSource).TrimEnd('\')
    $candidate = ([string]$script:SrcDir).TrimEnd('\')
    $inside = $candidate.Equals($active, [StringComparison]::OrdinalIgnoreCase) -or
        $candidate.StartsWith($active + '\', [StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) { return }
    if (-not (Test-Path -LiteralPath $DesktopOperationLease)) { return }
    Warn "FlintTrade Desktop holds its bootstrap source-operation lease at $DesktopOperationLease."
    Warn "That lease guards every mutation of $($script:SrcDir), which the desktop shell treats as its active source."
    if ($DryRun) {
        Warn "DRY-RUN: a real run would refuse to touch that checkout until the desktop shell has quit."
        return
    }
    Fail "Quit FlintTrade Desktop and re-run; this installer never takes the desktop's lease itself."
}

function Assert-SourceDirSafe {
    if (-not (Test-Path -LiteralPath $script:SrcDir)) { return }
    $item = Get-Item -LiteralPath $script:SrcDir -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Fail "Refusing a reparse-point managed source path: $($script:SrcDir)"
    }
    if (-not ($item.PSIsContainer)) {
        Fail "Refusing a non-directory managed source path: $($script:SrcDir)"
    }
    $children = @(Get-ChildItem -LiteralPath $script:SrcDir -Force -ErrorAction SilentlyContinue)
    if ($children.Count -eq 0) { return }
    $hasPackageJson = Test-Path -LiteralPath (Join-Path $script:SrcDir "package.json") -PathType Leaf
    $hasPyproject = Test-Path -LiteralPath (Join-Path $script:SrcDir "pyproject.toml") -PathType Leaf
    if ($hasPackageJson -and $hasPyproject) { return }
    Fail "Refusing to overwrite $($script:SrcDir) because it is not an empty directory or a FlintTrade checkout."
}

function Assert-SourceOriginTrusted {
    $gitDir = Join-Path $script:SrcDir ".git"
    if (-not (Test-Path -LiteralPath $gitDir)) { return }
    $origin = ""
    try {
        $origin = ([string](& git -C $script:SrcDir remote get-url origin)).Trim()
    } catch {
        $origin = ""
    }
    if (-not $origin) { return }
    $trimmed = $RepoUrl
    if ($trimmed.EndsWith(".git")) { $trimmed = $trimmed.Substring(0, $trimmed.Length - 4) }
    if ($origin -ne $RepoUrl -and $origin -ne $trimmed) {
        Fail "Refusing to update $($script:SrcDir) because its origin is not the official HTTPS FlintTrade repository."
    }
}

# A branch or tag archive cannot be hash-pinned, but it can be commit-pinned:
# resolve the ref to its commit SHA first, then download that exact commit's
# archive, so the installed bytes cannot drift between resolution and download
# and the install is reproducible from the reported SHA.
function Resolve-RefCommitSha([string]$GitRef) {
    $apiUrl = "https://api.github.com/repos/$RepoSlug/commits/$GitRef"
    Assert-TrustedUrl $apiUrl
    $response = $null
    try {
        $response = Invoke-RestMethod -Uri $apiUrl -UseBasicParsing
    } catch {
        Fail "Could not resolve '$GitRef' to a commit SHA via api.github.com: $($_.Exception.Message)"
    }
    $sha = ([string]$response.sha).ToLowerInvariant()
    if ($sha -notmatch '^[0-9a-f]{40}$') {
        Fail "api.github.com returned no well-formed commit SHA for '$GitRef'."
    }
    return $sha
}

function Invoke-GitSourceAcquisition([string]$GitRef) {
    Assert-SourceOriginTrusted
    if (Test-Path -LiteralPath (Join-Path $script:SrcDir ".git")) {
        Say "Refreshing the managed source checkout at $($script:SrcDir) (git fetch + reset)..."
        & git -C $script:SrcDir fetch --prune --tags $RepoUrl $GitRef
        if ($LASTEXITCODE -ne 0) { Fail "Could not fetch '$GitRef' from $RepoUrl." }
        & git -C $script:SrcDir reset --hard FETCH_HEAD
        if ($LASTEXITCODE -ne 0) { Fail "Could not reset the managed source checkout to '$GitRef'." }
        return
    }
    Say "Cloning FlintTrade ($GitRef) into $($script:SrcDir)..."
    $parent = Split-Path -Parent $script:SrcDir
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (Test-Path -LiteralPath $script:SrcDir) {
        Remove-Item -LiteralPath $script:SrcDir -Recurse -Force
    }
    & git clone --depth 1 --branch $GitRef $RepoUrl $script:SrcDir
    if ($LASTEXITCODE -ne 0) { Fail "Could not clone $RepoUrl at '$GitRef'." }
}

function Invoke-ArchiveSourceAcquisition([string]$GitRef) {
    Say "git is not installed; resolving '$GitRef' to an exact commit so the archive install is reproducible..."
    $sha = Resolve-RefCommitSha $GitRef
    $url = "$ArchiveBaseUrl/$sha"
    Assert-TrustedUrl $url
    Say "Downloading the source archive for commit $sha ($url)..."
    $staging = Join-Path ([System.IO.Path]::GetTempPath()) ("flinttrade-source-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    try {
        $archive = Join-Path $staging "source.zip"
        Save-TrustedFile $url $archive
        $unpacked = Join-Path $staging "unpacked"
        Expand-VerifiedArchive $archive "zip" $unpacked
        $extracted = @(Get-ChildItem -LiteralPath $unpacked -Directory) | Select-Object -First 1
        if (-not $extracted) { Fail "The downloaded source archive did not contain a checkout directory." }
        $extractedPath = [string]$extracted.FullName
        $hasPackageJson = Test-Path -LiteralPath (Join-Path $extractedPath "package.json") -PathType Leaf
        $hasPyproject = Test-Path -LiteralPath (Join-Path $extractedPath "pyproject.toml") -PathType Leaf
        if (-not ($hasPackageJson -and $hasPyproject)) {
            Fail "The downloaded source archive is not a FlintTrade checkout."
        }
        Say "Replacing $($script:SrcDir) with the downloaded checkout (a git-less refresh rebuilds dependencies)."
        $parent = Split-Path -Parent $script:SrcDir
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        if (Test-Path -LiteralPath $script:SrcDir) {
            Remove-Item -LiteralPath $script:SrcDir -Recurse -Force
        }
        Move-Item -LiteralPath $extractedPath -Destination $script:SrcDir
        Say "Installed source commit: $sha (re-run with -Ref $sha to reproduce this exact install)."
    } finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-SourceAcquisition {
    $gitRef = $DefaultBranch
    if ($Ref) { $gitRef = $Ref }
    Confirm-SourceDirProvenance
    Assert-DesktopNotOperating
    Assert-SourceDirSafe
    if ($DryRun) {
        if (Have git) {
            Say "DRY-RUN: would clone or fetch+reset $RepoUrl at '$gitRef' into $($script:SrcDir)"
        } else {
            Say "DRY-RUN: would resolve '$gitRef' to a commit SHA via api.github.com, then download that commit's archive from $ArchiveBaseUrl/<sha> and extract it into $($script:SrcDir)"
        }
        return
    }
    if (Have git) {
        Invoke-GitSourceAcquisition $gitRef
    } else {
        Invoke-ArchiveSourceAcquisition $gitRef
    }
    if (-not (Test-Path -LiteralPath (Join-Path $script:SrcDir $ManifestRelative) -PathType Leaf)) {
        Fail "The checkout at $($script:SrcDir) has no $ManifestRelative; it is not a supported FlintTrade revision."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $script:SrcDir $BootstrapRelative) -PathType Leaf)) {
        Fail "The checkout at $($script:SrcDir) has no $BootstrapRelative; it is not a supported FlintTrade revision."
    }
}

# ---------------------------------------------------------------------------
# 4/5. Manifest-pinned, SHA-256 verified tools laid out exactly like the
#      desktop bootstrap: <tools-root>\<tool>\<version>\<target>
# ---------------------------------------------------------------------------

function Read-ToolManifest {
    $manifestPath = Join-Path $script:SrcDir $ManifestRelative
    try {
        return (Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        Fail "Could not read $ManifestRelative from the checkout: $($_.Exception.Message)"
    }
}

function Get-ManifestAsset($Manifest, [string]$Tool) {
    $section = $Manifest.$Tool
    if (-not $section) { Fail "The bootstrap tool manifest has no '$Tool' section." }
    if (-not $section.version) { Fail "The bootstrap tool manifest has no '$Tool' version." }
    $asset = $section.assets.$($script:Target)
    if (-not $asset) {
        Fail "The bootstrap tool manifest pins no '$Tool' asset for $($script:Target)."
    }
    foreach ($field in @("archive", "executable", "sha256", "url")) {
        if (-not $asset.$field) {
            Fail "The bootstrap tool manifest '$Tool' asset for $($script:Target) is missing '$field'."
        }
    }
    return $asset
}

function Get-DesktopMarkerExecutableSha256([string]$MarkerPath) {
    try {
        $marker = Get-Content -LiteralPath $MarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($marker.executableSha256) { return ([string]$marker.executableSha256).ToLowerInvariant() }
    } catch {
        return ""
    }
    return ""
}

function Install-VerifiedTool([string]$Tool, $Manifest) {
    $version = [string]$Manifest.$Tool.version
    $asset = Get-ManifestAsset $Manifest $Tool
    $url = [string]$asset.url
    $sha = ([string]$asset.sha256).ToLowerInvariant()
    $archiveKind = [string]$asset.archive
    $relativeExecutable = [string]$asset.executable
    Assert-TrustedUrl $url
    Assert-Sha256Shape $sha
    Assert-ConfinedRelativePath $relativeExecutable

    $versionRoot = Join-Path (Join-Path $ToolsRoot $Tool) $version
    $installRoot = Join-Path $versionRoot $script:Target
    $marker = "$installRoot.flinttrade-web-verified"
    # The Electron bootstrap writes its verification marker INSIDE the install
    # root (packages\apps\desktop\electron\bootstrap.ts: verifiedMarker =
    # path.join(installRoot, TOOL_VERIFICATION_MARKER)). The sibling form is only
    # its legacyVerifiedMarker and nothing writes it any more, so read the real
    # one first and keep the legacy path as a fallback.
    $desktopMarker = Join-Path $installRoot ".flinttrade-tool-verified.json"
    $legacyDesktopMarker = "$installRoot.flinttrade-tool-verified.json"
    $executable = Join-Path $installRoot ($relativeExecutable -replace '/', '\')

    if ((Test-Path -LiteralPath $marker -PathType Leaf) -and (Test-Path -LiteralPath $executable -PathType Leaf)) {
        $recorded = ([string](Get-Content -LiteralPath $marker -Raw)).Trim().ToLowerInvariant()
        if ($recorded -eq $sha) {
            Say "Reusing the verified $Tool $version already provisioned at $installRoot."
            return $executable
        }
    }

    $provenMarker = ""
    if (Test-Path -LiteralPath $desktopMarker -PathType Leaf) {
        $provenMarker = $desktopMarker
    } elseif (Test-Path -LiteralPath $legacyDesktopMarker -PathType Leaf) {
        $provenMarker = $legacyDesktopMarker
    }
    if ($provenMarker) {
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            Fail "The desktop-provisioned $Tool state at $installRoot carries a verification marker but no usable executable. It was preserved; run the uninstaller or remove it yourself, then re-run."
        }
        $recorded = Get-DesktopMarkerExecutableSha256 $provenMarker
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $executable).Hash.ToLowerInvariant()
        if ($recorded -and $recorded -eq $actual) {
            Say "Reusing the desktop-provisioned $Tool $version at $installRoot."
            return $executable
        }
        Fail "Existing $Tool state at $installRoot failed verification and was preserved. Remove it or run the uninstaller, then re-run."
    }

    if ($DryRun) {
        Say "DRY-RUN: would download $url"
        Say "DRY-RUN: would verify sha256 $sha, then extract into $installRoot"
        return $executable
    }

    $downloads = Join-Path $ToolsRoot ".downloads"
    $archiveName = Split-Path -Leaf ([Uri]$url).AbsolutePath
    $archive = Join-Path $downloads $archiveName
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    Say "Downloading $Tool $version..."
    Save-TrustedFile $url $archive
    Assert-FileSha256 $archive $sha
    Say "Verified the SHA-256 digest pinned by the bootstrap tool manifest."
    Unblock-File -LiteralPath $archive -ErrorAction SilentlyContinue

    $staging = Join-Path $versionRoot (".{0}.extracting-{1}" -f $script:Target, [Guid]::NewGuid().ToString("N"))
    try {
        Expand-VerifiedArchive $archive $archiveKind $staging
        $stagedExecutable = Join-Path $staging ($relativeExecutable -replace '/', '\')
        if (-not (Test-Path -LiteralPath $stagedExecutable -PathType Leaf)) {
            Fail "The verified $Tool archive did not contain its expected executable ($relativeExecutable)."
        }
        if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force }
        if ((Test-Path -LiteralPath $desktopMarker) -or (Test-Path -LiteralPath $legacyDesktopMarker)) {
            Fail "A desktop tool-verification marker appeared at $installRoot while this installer was extracting $Tool $version; refusing to delete a verified tool root."
        }
        if (Test-Path -LiteralPath $installRoot) { Remove-Item -LiteralPath $installRoot -Recurse -Force }
        Move-Item -LiteralPath $staging -Destination $installRoot
    } finally {
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Set-Content -LiteralPath $marker -Value $sha -Encoding ascii
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        Fail "The provisioned $Tool $version is missing at $executable."
    }
    return $executable
}

# ---------------------------------------------------------------------------
# 7. Delegation to the repository's own bootstrap entrypoint
# ---------------------------------------------------------------------------

function Get-PowerShellExecutable {
    foreach ($candidate in @("pwsh.exe", "powershell.exe")) {
        $path = Join-Path $PSHOME $candidate
        if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    }
    Fail "Could not locate the PowerShell executable required to run the repository bootstrap."
}

function Invoke-RepositoryBootstrap([string]$Uv, [string]$Node, [string]$CorepackJs, [string]$PnpmVersion) {
    $bootstrap = Join-Path $script:SrcDir $BootstrapRelative
    if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
        Fail "The checkout has no bootstrap entrypoint at $bootstrap."
    }
    $powershell = Get-PowerShellExecutable
    Say "Building FlintTrade with the repository's own bootstrap entrypoint. This takes a few minutes on first run."
    & $powershell -NoProfile -ExecutionPolicy Bypass -File $bootstrap `
        -Candidate $script:SrcDir `
        -Uv $Uv `
        -Node $Node `
        -CorepackJs $CorepackJs `
        -ToolsRoot $ToolsRoot `
        -PnpmVersion $PnpmVersion
    if ($LASTEXITCODE -ne 0) {
        Fail "The FlintTrade bootstrap build failed; nothing was installed."
    }
}

# ---------------------------------------------------------------------------
# 8. Launcher shim and Start Menu shortcut
# ---------------------------------------------------------------------------

function Install-LauncherShim([string]$PythonExecutable) {
    if (-not (Test-Path -LiteralPath $ShimDir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $ShimDir | Out-Null
    }
    $lines = @(
        '@echo off',
        'rem FlintTrade launcher shim - generated by flinttrade-web-install.ps1. Do not edit.',
        'rem Re-run the web installer to regenerate it after moving the managed checkout.',
        'setlocal',
        ('cd /d "{0}"' -f $script:SrcDir),
        'if errorlevel 1 exit /b 1',
        ('"{0}" scripts\ft.py %*' -f $PythonExecutable),
        'exit /b %ERRORLEVEL%'
    )
    Write-OemText $ShimPath (($lines -join "`r`n") + "`r`n")
    Say "Installed the launcher at $ShimPath."
    $pathEntries = @(($env:PATH -split ';') | Where-Object { $_ })
    $onPath = @($pathEntries | Where-Object { $_.TrimEnd('\').Equals($ShimDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) })
    if ($onPath.Count -eq 0) {
        Warn "$ShimDir is not on PATH; add it, or run the launcher as `"$ShimPath`"."
    }
}

function Install-StartMenuShortcut {
    if (-not (Test-Path -LiteralPath $StartMenuDir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
    }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($StartMenuShortcut)
        $shortcut.TargetPath = $ShimPath
        $shortcut.Arguments = "start"
        $shortcut.WorkingDirectory = $script:SrcDir
        $shortcut.Description = "FlintTrade - open-source self-hosted trading software"
        $shortcut.Save()
        Say "Added the Start Menu shortcut at $StartMenuShortcut."
    } catch {
        Warn "Could not create the Start Menu shortcut: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
# 8b. Owner-private web-install receipt
#
# The uninstaller may only delete what an installer proved it wrote, so record
# the launcher shim (with its SHA-256), the Start Menu shortcut, the managed
# source checkout and the tools root. Mirrors the POSIX installer's receipt.
# ---------------------------------------------------------------------------

function Protect-WebReceiptDirectory([string]$Path) {
    try {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($existing in @($acl.Access)) { [void]$acl.RemoveAccessRule($existing) }
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $identity,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } catch {
        Warn "Could not restrict $Path to the current user: $($_.Exception.Message)"
    }
}

function Get-ReceiptSafeValue([string]$Value) {
    if ($Value -match "[`r`n]") { Fail "Web-install receipt values must be single-line paths." }
    return $Value
}

function Write-WebInstallReceipt {
    if (-not $WebReceiptDir) {
        Fail "Could not resolve the Windows application-data folder required for the web-install receipt."
    }
    if (-not (Test-Path -LiteralPath $ShimPath -PathType Leaf)) {
        Fail "The installed launcher is not an ordinary web-install receipt candidate."
    }
    if (-not (Test-Path -LiteralPath $WebReceiptDir -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $WebReceiptDir | Out-Null
    }
    $receiptItem = Get-Item -LiteralPath $WebReceiptDir -Force
    if ($receiptItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Fail "Refusing a reparse-point web-install receipt directory: $WebReceiptDir"
    }
    Protect-WebReceiptDirectory $WebReceiptDir
    $shim = [System.IO.Path]::GetFullPath($ShimPath)
    $shimHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $shim).Hash.ToLowerInvariant()
    $shortcut = ""
    if (Test-Path -LiteralPath $StartMenuShortcut -PathType Leaf) {
        $shortcut = [System.IO.Path]::GetFullPath($StartMenuShortcut)
    }
    $source = [System.IO.Path]::GetFullPath($script:SrcDir).TrimEnd('\')
    $tools = [System.IO.Path]::GetFullPath($ToolsRoot).TrimEnd('\')
    $lines = @(
        "format=flinttrade-web-install-v1",
        "platform=Windows",
        ("shim=" + (Get-ReceiptSafeValue $shim)),
        ("shim_sha256=" + $shimHash),
        ("shortcut=" + (Get-ReceiptSafeValue $shortcut)),
        ("source=" + (Get-ReceiptSafeValue $source)),
        ("tools=" + (Get-ReceiptSafeValue $tools))
    )
    [System.IO.File]::WriteAllText($WebReceiptPath, (($lines -join "`r`n") + "`r`n"), (New-Object System.Text.UTF8Encoding($false)))
    Say "Recorded the web-install receipt at $WebReceiptPath."
}

# ---------------------------------------------------------------------------
# 9. Report and launch
# ---------------------------------------------------------------------------

function Write-PathReport {
    Say "----------------------------------------------------------------"
    Say "Workspace and data : $(Get-WorkspaceDir)"
    Say "Verified tools     : $ToolsRoot"
    Say "Managed source     : $($script:SrcDir)"
    Say "Launcher           : $ShimPath  (also: flinttrade <subcommand>)"
    Say "Install receipt    : $WebReceiptPath  (the uninstaller removes only what this proves)"
    Say "Runner             : python scripts/ft.py <start|stop|restart|status|dev|setup|test|lint|clean|version|help|desktop-test|desktop-build|desktop-package|desktop-dev>"
    Say "Open FlintTrade at : $BackendUrl"
    Say "Uninstall          : $UninstallCommand"
    Say "                     (add -Purge to delete the workspace, tools and source too)"
    Say "----------------------------------------------------------------"
}

function Invoke-OptionalLaunch {
    if ($NoLaunch) {
        Say "Not starting FlintTrade (-NoLaunch). Start it later with: flinttrade start"
        return
    }
    if (-not (Confirm-Step "Start FlintTrade now?")) {
        Say "Not started. Start it later with: flinttrade start"
        return
    }
    Say "Starting FlintTrade - open $BackendUrl in your browser. Press Ctrl-C to stop."
    & $ShimPath start
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

function Invoke-FlintTradeWebInstall {
    if ($Help) {
        Show-Usage
        return
    }
    if ($Ref) {
        if ($Ref -notmatch '^[A-Za-z0-9._/-]+$' -or $Ref.Contains("..") -or $Ref.StartsWith("-")) {
            Fail "-Ref is not a well-formed Git reference: $Ref"
        }
    }
    if (-not $LocalAppDataRoot -or -not $RoamingAppDataRoot) {
        Fail "Could not resolve the Windows application-data folders required to install FlintTrade."
    }
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {
        Warn "Could not raise the TLS floor to 1.2; downloads may fail on this machine."
    }

    Say "FlintTrade web-app installer - no prior tooling required."
    if ($DryRun) { Say "Dry run: nothing will be downloaded, built or installed." }

    $script:Target = Get-BootstrapTarget
    Say "Detected bootstrap target: $($script:Target)"

    Resolve-WebSourceDir
    # Parity with the POSIX installer's '--src must be an absolute path' guard:
    # a relative (or drive-/root-relative) path would silently resolve against
    # the current working directory, which is never what the operator meant.
    if (-not [System.IO.Path]::IsPathRooted($script:SrcDir) -or
        ($script:SrcDir -match '^[A-Za-z]:($|[^\\/])') -or
        ($script:SrcDir -match '^[\\/](?![\\/])')) {
        Fail "-SrcDir must be an absolute path: $($script:SrcDir)"
    }
    $script:SrcDir = [System.IO.Path]::GetFullPath($script:SrcDir).TrimEnd('\')

    Write-PreflightReport

    Invoke-SourceAcquisition

    if (-not (Test-Path -LiteralPath (Join-Path $script:SrcDir $ManifestRelative) -PathType Leaf)) {
        if (-not $DryRun) { Fail "The checkout has no $ManifestRelative." }
        Say "DRY-RUN: would read the pinned tool versions and digests from $ManifestRelative in the checkout."
        Say "DRY-RUN: would delegate the build to $BootstrapRelative, then install the launcher at $ShimPath."
        Write-PathReport
        return
    }

    $manifest = Read-ToolManifest
    $pinnedUv = [string]$manifest.uv.version
    $pinnedNode = [string]$manifest.node.version
    $pinnedPnpm = [string]$manifest.pnpm.version
    if ($pinnedPnpm -ne $PinnedPnpmVersion) {
        Fail "The checkout pins pnpm $pinnedPnpm; this installer only supports the $PinnedPnpmVersion bootstrap entrypoint."
    }
    $uvAsset = Get-ManifestAsset $manifest "uv"
    $nodeAsset = Get-ManifestAsset $manifest "node"

    Resolve-HostToolReuse $pinnedUv $pinnedNode

    Say "Pinned toolchain for $($script:Target): uv $pinnedUv, Node $pinnedNode, pnpm $pinnedPnpm."
    if ($script:ReuseUv) {
        Say "  uv   : reusing the exactly-matching host uv at $($script:ReuseUv)"
    } else {
        Say "  uv   : will download $($uvAsset.url)"
    }
    if ($script:ReuseNode) {
        Say "  node : reusing the exactly-matching host Node at $($script:ReuseNode)"
    } else {
        Say "  node : will download $($nodeAsset.url)"
    }
    Say "  pnpm : provided by Corepack from the verified Node install (no separate download)"
    Say "  python 3.12 : installed by uv into $(Join-Path $ToolsRoot 'python')"
    # A dry run mutates nothing, so it never needs the download confirmation —
    # this keeps non-interactive -DryRun usable without -Yes.
    if (-not $DryRun) {
        if (-not (Confirm-Step "Proceed with the downloads above?")) {
            Fail "Cancelled at the download confirmation; nothing was changed."
        }
    }

    $uv = $script:ReuseUv
    if (-not $uv) { $uv = Install-VerifiedTool "uv" $manifest }
    $node = $script:ReuseNode
    $corepackJs = $script:ReuseCorepackJs
    if (-not $node) {
        $node = Install-VerifiedTool "node" $manifest
        $corepackJs = Get-CorepackJsForNode $node
    }

    if ($DryRun) {
        Say "DRY-RUN: would run $BootstrapRelative with the six verified bootstrap arguments."
        Say "DRY-RUN: would install the launcher at $ShimPath and a Start Menu shortcut at $StartMenuShortcut."
        Write-PathReport
        return
    }

    if (-not (Test-Path -LiteralPath $corepackJs -PathType Leaf)) {
        Fail "The verified Node install carries no Corepack JavaScript at $corepackJs."
    }

    Invoke-RepositoryBootstrap $uv $node $corepackJs $pinnedPnpm

    $venvPython = Join-Path $script:SrcDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Fail "The bootstrap completed without a managed interpreter at $venvPython."
    }
    Install-LauncherShim $venvPython
    Install-StartMenuShortcut
    Write-WebInstallReceipt

    Write-PathReport
    Invoke-OptionalLaunch
}

Invoke-FlintTradeWebInstall
