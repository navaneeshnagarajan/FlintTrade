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
# active source with an operation-lease DIRECTORY created by its bootstrap
# (packages\apps\desktop\electron\bootstrap.ts, acquireOperationLease in
# bootstrap-io.ts).
#
# That lease is deliberately NOT a mutual-exclusion primitive an outside process
# can hold: on acquisition the desktop treats any lease it finds as recoverable
# stale evidence, waits only for the process records INSIDE it, then quarantines
# and deletes it. A lease carrying nothing but an owner.json is therefore stolen
# immediately, and the only records the desktop respects are POSIX
# process-group / Windows supervisor files bound to a containment token minted
# by the Electron singleton, which this installer cannot mint.
#
# So this installer never shares the desktop's active source tree. It keeps its
# own checkout under $WebSourceRoot and refuses a -SrcDir that would aim it at
# the desktop's, which is what makes both installers safe in either order.
$DesktopSourceRoot = Join-Path $ManagedRoot "src"
$DesktopActiveSource = Join-Path $DesktopSourceRoot "FlintTrade"
$DesktopOperationLease = Join-Path $DesktopSourceRoot ".flinttrade-bootstrap-operation.lock"
$WebSourceRoot = Join-Path $ManagedRoot "web-src"
$WebActiveSource = Join-Path $WebSourceRoot "FlintTrade"
$ManifestRelative = "packages\apps\desktop\resources\bootstrap\tool-manifest.json"
$BootstrapRelative = "packages\apps\desktop\resources\bootstrap\flinttrade-bootstrap.ps1"
$LocalAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$RoamingAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
# %LOCALAPPDATA%\Programs\FlintTrade is the electron-builder per-user install
# directory, and flinttrade-install.ps1's Assert-WindowsFreshInstallAdmission
# refuses a fresh desktop install whenever that directory exists without exactly
# one proven FlintTrade uninstall-registry identity. A web launcher dropped in
# there therefore locked the documented desktop installer out of the machine
# permanently, so the web launcher gets its own directory and its own name — and
# its own Start Menu folder, which the desktop uninstaller's shortcut sweep
# would otherwise report as non-empty residue.
#
# Each is guarded on its root: Join-Path throws a raw binder error on an empty
# Path, which would pre-empt the friendly "could not resolve the Windows
# application-data folders" failure below on a machine whose profile folders do
# not resolve.
$ShimDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "Programs\FlintTradeWeb" } else { "" }
$ShimPath = if ($ShimDir) { Join-Path $ShimDir "flinttrade-web.cmd" } else { "" }
$StartMenuRoot = if ($RoamingAppDataRoot) { Join-Path $RoamingAppDataRoot "Microsoft\Windows\Start Menu\Programs" } else { "" }
$StartMenuDir = if ($StartMenuRoot) { Join-Path $StartMenuRoot "FlintTrade Web" } else { "" }
$StartMenuShortcut = if ($StartMenuDir) { Join-Path $StartMenuDir "FlintTrade Web.lnk" } else { "" }
# Where earlier revisions of this installer wrote both. Kept only so a re-run
# can retire what its own receipt still proves it created.
$LegacyShimDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "Programs\FlintTrade" } else { "" }
$LegacyShimPath = if ($LegacyShimDir) { Join-Path $LegacyShimDir "flinttrade.cmd" } else { "" }
$LegacyStartMenuDir = if ($StartMenuRoot) { Join-Path $StartMenuRoot "FlintTrade" } else { "" }
$LegacyStartMenuShortcut = if ($LegacyStartMenuDir) { Join-Path $LegacyStartMenuDir "FlintTrade.lnk" } else { "" }
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

# param(...) declares $SrcDir in the SCRIPT scope, so the $script:SrcDir reset
# below overwrote the operator's -SrcDir before Resolve-WebSourceDir could read
# it: the flag was silently ignored and the default managed checkout used
# instead. Capture the supplied value first.
$SrcDirParameter = $SrcDir
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
# Set when repository markers - which every contributor clone carries - are the
# only identity proof for the managed source. They authorise an in-place
# 'git fetch + reset' and never the recursive replacement a git-less refresh
# performs.
$script:SourceUpdateOnly = $false
# Set to the destination when this run moved a legacy web checkout out of the
# desktop shell's source root; the receipt keeps naming the old path until it is
# rewritten at the end of the run.
$script:MigratedWebSource = ""
# Set by Get-CanonicalOverlapPath when a path traverses a reparse point whose
# target could not be read, so the caller can refuse rather than compare a path
# it could not canonicalise.
$script:OverlapPathUnresolved = $false

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
source checkout, and installs a 'flinttrade-web' launcher. No prior tooling
needed. The FlintTrade Desktop shell is a separate install with its own
launcher, Start Menu entry, source checkout and uninstall receipt; neither one
touches the other's files, so the two can be installed in either order.

Flags:
  -Ref <git-ref>   Branch, tag or commit to install (default: main)
  -SrcDir <dir>    Managed WEB source checkout (default:
                   %USERPROFILE%\.flinttrade\web-src\FlintTrade). This is
                   neither the contributor source-build checkout that
                   flinttrade-install.ps1 manages at
                   %USERPROFILE%\.flinttrade\source-build\FlintTrade nor the
                   desktop shell's active source at
                   %USERPROFILE%\.flinttrade\src\FlintTrade, which is refused.
                   An existing directory is REPLACED only when this installer's
                   own receipt names it. A clean FlintTrade Git checkout it
                   cannot claim is updated in place instead; anything else is
                   refused, so a typo cannot destroy unrelated source.
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
    if ($SrcDirParameter) {
        $script:SrcDir = $SrcDirParameter
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
    $script:SrcDir = $WebActiveSource
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

# The desktop's active source may never be this installer's source, at any point
# in the run.
#
# Probing the lease once and then proceeding was not a guard at all: the fetch,
# the hard reset and the multi-minute dependency build all run afterwards, and
# FlintTrade Desktop launched at any moment in that window acquires its own
# lease and mutates the very same checkout. Nor can this installer hold the
# lease for the whole build - see the $DesktopOperationLease note at the top of
# this file for why a lease written by a script is one the desktop quarantines
# rather than respects. The only safe answer is separate trees.
# Canonicalise a path whose parents need not exist yet, so the overlap guard
# below compares trees rather than spellings: '.', '..', mixed separators and a
# trailing separator are normalised, and every existing component that is a
# reparse point is replaced by its target. A path whose reparse point cannot be
# read leaves $script:OverlapPathUnresolved set, because a path this installer
# could not canonicalise is one it cannot prove is not the desktop's own.
function Get-CanonicalOverlapPath([string]$Value) {
    $script:OverlapPathUnresolved = $false
    if (-not $Value) { return "" }
    $full = ""
    try {
        $full = ([System.IO.Path]::GetFullPath($Value)).TrimEnd('\', '/')
    } catch {
        $script:OverlapPathUnresolved = $true
        return ""
    }
    $root = [System.IO.Path]::GetPathRoot($full)
    if (-not $root) { return $full }
    $relative = $full.Substring($root.Length).TrimStart('\', '/')
    $current = $root
    foreach ($component in @($relative -split '[\\/]' | Where-Object { $_ })) {
        $current = Join-Path $current $component
        if (-not (Test-Path -LiteralPath $current)) { continue }
        $item = $null
        try {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
        } catch {
            $script:OverlapPathUnresolved = $true
            continue
        }
        if (-not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { continue }
        $target = ""
        try {
            $target = [string](@($item.Target) | Select-Object -First 1)
        } catch {
            $target = ""
        }
        if (-not $target) {
            $script:OverlapPathUnresolved = $true
            continue
        }
        if (-not [System.IO.Path]::IsPathRooted($target)) {
            $target = Join-Path (Split-Path -Parent $current) $target
        }
        try {
            $current = ([System.IO.Path]::GetFullPath($target)).TrimEnd('\', '/')
        } catch {
            $script:OverlapPathUnresolved = $true
        }
    }
    return ([string]$current).TrimEnd('\', '/')
}

# Both sides are canonicalised first. Comparing the raw -SrcDir string was no
# guard at all: '.\', '..\', a trailing separator, forward slashes and any
# junctioned parent all spell the desktop's own tree while matching none of the
# string tests below, so the installer went on to fetch, hard-reset and build
# inside it.
function Assert-DesktopSourceNotShared {
    $candidate = Get-CanonicalOverlapPath $script:SrcDir
    $unresolved = $script:OverlapPathUnresolved
    $root = Get-CanonicalOverlapPath $DesktopSourceRoot
    if ($script:OverlapPathUnresolved) { $unresolved = $true }
    if ($unresolved -or -not $candidate -or -not $root) {
        Fail ("Refusing $($script:SrcDir): it could not be canonicalised - one of its parents is a " +
              "reparse point this installer cannot read - so it cannot be proved to sit outside the " +
              "FlintTrade Desktop shell's source tree at $DesktopSourceRoot.")
    }
    $shared = $candidate.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
        $candidate.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $root.StartsWith($candidate + '\', [StringComparison]::OrdinalIgnoreCase)
    if (-not $shared) { return }
    Warn "$($script:SrcDir) overlaps the FlintTrade Desktop shell's active source tree at $DesktopActiveSource."
    Warn "The desktop guards every mutation of that tree with the bootstrap operation lease at"
    Warn "$DesktopOperationLease, and only its own singleton can hold one: a lease written by this"
    Warn "installer would be treated as stale evidence and deleted, so a desktop launched during the"
    Warn "fetch or the multi-minute build would corrupt the checkout underneath it."
    Fail "Choose a source checkout outside $DesktopSourceRoot (the default is $WebActiveSource)."
}

function Test-FileContains([string]$Path, [string]$Needle) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        return ([System.IO.File]::ReadAllText($Path)).Contains($Needle)
    } catch {
        return $false
    }
}

function Test-WebPathContainsReparsePoint([string]$Target) {
    try {
        $full = ([System.IO.Path]::GetFullPath($Target)).TrimEnd('\', '/')
        $root = [System.IO.Path]::GetPathRoot($full)
        if (-not $root) { return $true }
        $relative = $full.Substring($root.Length).TrimStart('\', '/')
        $current = $root
        foreach ($component in @($relative -split '[\\/]' | Where-Object { $_ })) {
            $current = Join-Path $current $component
            if (-not (Test-Path -LiteralPath $current)) { continue }
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $true }
        }
    } catch {
        return $true
    }
    return $false
}

function Test-OwnerLocalWebPath([string]$Target) {
    try {
        $owner = (Get-Acl -LiteralPath $Target).GetOwner([System.Security.Principal.SecurityIdentifier])
        if (-not $owner) { return $false }
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $allowed = @([string]$identity.User.Value)
        foreach ($group in @($identity.Groups)) { $allowed += [string]$group.Value }
        return ($allowed -contains [string]$owner.Value)
    } catch {
        return $false
    }
}

# One field from the web-install receipt, and only when the receipt proves
# itself exactly as flinttrade-uninstall.ps1's Read-WebInstallReceipt requires:
# an owner-local receipt reached through a path with no reparse alias in it, and
# the v1 format line. The receipt authorises destructive replacement, so this is
# the single reader every trusting caller goes through - a second, weaker one
# would simply be the way round it.
function Get-RecordedWebInstallField([string]$Prefix) {
    if (-not $WebReceiptPath -or -not $WebReceiptDir) { return "" }
    if (-not (Test-Path -LiteralPath $WebReceiptPath -PathType Leaf)) { return "" }
    if (Test-WebPathContainsReparsePoint $WebReceiptPath) { return "" }
    if (-not (Test-OwnerLocalWebPath $WebReceiptDir)) { return "" }
    if (-not (Test-OwnerLocalWebPath $WebReceiptPath)) { return "" }
    $lines = @()
    try {
        $lines = @(Get-Content -LiteralPath $WebReceiptPath)
    } catch {
        return ""
    }
    if ($lines.Count -lt 1) { return "" }
    if (([string]$lines[0]) -cne "format=flinttrade-web-install-v1") { return "" }
    $value = ""
    foreach ($line in $lines) {
        if (([string]$line).StartsWith($Prefix, [StringComparison]::Ordinal)) {
            $value = ([string]$line).Substring($Prefix.Length)
        }
    }
    return $value
}

# The installer's own receipt is the ONLY proof that this installer created a
# directory: it was written by a previous run and names the exact directory that
# run managed.
function Test-WebReceiptNamesSource([string]$Target) {
    $recorded = Get-RecordedWebInstallField "source="
    if (-not $recorded) { return $false }
    $recorded = $recorded.TrimEnd('\')
    $candidate = ([string]$Target).TrimEnd('\')
    if ($candidate.Equals($recorded, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    $candidateFull = Get-CanonicalOverlapPath $candidate
    if ($script:OverlapPathUnresolved -or -not $candidateFull) { return $false }
    $recordedFull = Get-CanonicalOverlapPath $recorded
    if ($script:OverlapPathUnresolved -or -not $recordedFull) { return $false }
    return $candidateFull.Equals($recordedFull, [StringComparison]::OrdinalIgnoreCase)
}

# Repository identity, not project shape and NOT ownership. flint.toml is this
# repository's own project manifest and names the repository it belongs to; the
# workspace member sets name FlintTrade's own packages. Revisions that predate
# flint.toml are still recognised through the second pair.
#
# All of those files are checked into the repository, so every contributor clone
# on earth satisfies this - including one holding a week of uncommitted work.
# That is why the markers authorise only the in-place update in
# Assert-SourceDirSafe and never a recursive replacement.
function Test-FlintTradeSourceMarkers([string]$Target) {
    if (Test-FileContains (Join-Path $Target "flint.toml") $RepoSlug) { return $true }
    $hasPyproject = Test-FileContains (Join-Path $Target "pyproject.toml") "flinttrade-core"
    $hasWorkspace = Test-FileContains (Join-Path $Target "pnpm-workspace.yaml") "packages/apps/terminal"
    if ($hasPyproject -and $hasWorkspace) { return $true }
    return $false
}

# A git-less refresh removes the directory recursively before publishing the
# downloaded checkout, so this guard decides whether unrelated source is
# destroyed. Two separate questions decide it, and conflating them is what put a
# contributor's working clone at risk:
#
#   * is this directory FlintTrade's code?  Repository markers answer that, and
#     every clone of this repository carries them;
#   * did THIS installer create this directory?  Only its own receipt answers
#     that, and only that answer authorises a recursive replacement.
#
# So a receipt-proved directory may be replaced; a merely marker-proved one may
# only be updated in place with 'git fetch' + 'git reset --hard', and not even
# that while it holds uncommitted work. An empty or absent directory needs no
# proof - there is nothing there to destroy - and an unproven one is refused
# rather than emptied.
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
    if (Test-WebReceiptNamesSource $script:SrcDir) { return }
    # A tree this run has just moved out of the desktop source root was proved by
    # that same receipt a moment ago; the receipt keeps naming the old path until
    # it is rewritten at the end of the run.
    if ($script:MigratedWebSource -and
        ([string]$script:MigratedWebSource).TrimEnd('\').Equals(
            ([string]$script:SrcDir).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    if (Test-FlintTradeSourceMarkers $script:SrcDir) {
        $markerWarning = @(
            "Refusing to replace $($script:SrcDir) - its FlintTrade markers prove the CODE is this",
            "repository's, not that this installer created the directory, and only a web-install",
            "receipt naming this exact path proves that."
        )
        if (-not (Have git)) {
            $markerWarning | ForEach-Object { Warn $_ }
            Fail ("git is not installed here, so this checkout could only be replaced wholesale. " +
                  "Install git so it can be updated in place, or pass -SrcDir (or set " +
                  "FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages.")
        }
        if (-not (Test-Path -LiteralPath (Join-Path $script:SrcDir ".git"))) {
            $markerWarning | ForEach-Object { Warn $_ }
            Fail ("It is not a Git checkout either, so it could only be replaced wholesale. Remove " +
                  "it yourself if you really meant that path, or pass -SrcDir (or set " +
                  "FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages.")
        }
        $status = $null
        try {
            $status = @(& git -C $script:SrcDir status --porcelain)
        } catch {
            $status = $null
        }
        if ($null -eq $status -or $LASTEXITCODE -ne 0) {
            Warn "Refusing to update $($script:SrcDir) - 'git status' could not report whether it holds"
            Warn "uncommitted work, and this installer runs 'git reset --hard' on it."
            Fail ("Check that checkout by hand, or pass -SrcDir (or set FLINTTRADE_WEB_SRC_DIR) to a " +
                  "directory this installer manages.")
        }
        $dirty = @($status | Where-Object { ([string]$_).Trim() })
        if ($dirty.Count -gt 0) {
            Warn "Refusing to update $($script:SrcDir) - it is a FlintTrade checkout with uncommitted"
            Warn "changes, and no web-install receipt names it, so this installer cannot claim it"
            Warn "created it. The update runs 'git fetch' + 'git reset --hard', which would discard"
            Warn "that work."
            Fail ("Commit, stash or remove those changes, or pass -SrcDir (or set " +
                  "FLINTTRADE_WEB_SRC_DIR) to a directory this installer manages.")
        }
        $script:SourceUpdateOnly = $true
        Say "No web-install receipt names $($script:SrcDir), so it will be updated in place (git fetch"
        Say "+ reset) rather than replaced; its FlintTrade markers prove the code, not this"
        Say "installer's ownership."
        return
    }
    Warn "Refusing to replace $($script:SrcDir) - nothing there proves it is a FlintTrade checkout."
    Warn "This installer deletes and republishes the directory it is given, so it replaces only a"
    Warn "directory a web-install receipt of its own names at this exact path. A clean Git checkout"
    Warn "carrying FlintTrade's identity - a flint.toml naming $RepoSlug, or FlintTrade's own"
    Warn "workspace members in pyproject.toml and pnpm-workspace.yaml - is updated in place instead."
    Fail ("Remove $($script:SrcDir) yourself if you really meant that path, or pass -SrcDir " +
          "(or set FLINTTRADE_WEB_SRC_DIR) to the intended checkout.")
}

# Evidence that the Electron desktop shell is installed on this machine: its
# electron-builder per-user directory, or an uninstall-registry entry that names
# it. %LOCALAPPDATA%\Programs\FlintTradeWeb is deliberately NOT in the list -
# that is this installer's own launcher directory.
function Test-DesktopShellInstalled {
    if ($LocalAppDataRoot) {
        $electronDir = Join-Path $LocalAppDataRoot "Programs\FlintTrade"
        if (Test-Path -LiteralPath $electronDir) { return $true }
    }
    try {
        $entries = @(Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue) |
            Where-Object { $_.DisplayName -ceq "FlintTrade" }
        if (@($entries).Count -gt 0) { return $true }
    } catch {
        return $false
    }
    return $false
}

# ---------------------------------------------------------------------------
# Upgrade path for machines installed by the revision that shared the desktop's
# source root.
#
# That revision defaulted the web source to $DesktopActiveSource, so a machine it
# installed still has a web-built checkout sitting in the tree the Electron
# desktop shell claims - the very overlap Assert-DesktopSourceNotShared now
# refuses outright. Retiring only the legacy launcher healed half of that and
# left the desktop and this installer fighting over one directory, which is the
# same class of failure the separate-trees rule exists to prevent.
#
# So move that checkout to the new web source root when the receipt proves this
# installer created it and nothing else can be claiming it, and otherwise leave
# it exactly where it is and say what has to happen and why. A tree that cannot
# be proved is never deleted, and never deleted at all: it is only ever moved.
# ---------------------------------------------------------------------------
function Move-LegacyWebSourceCheckout {
    $recorded = Get-RecordedWebInstallField "source="
    if (-not $recorded) { return }
    $recordedFull = Get-CanonicalOverlapPath $recorded
    if ($script:OverlapPathUnresolved -or -not $recordedFull) { return }
    $desktopRoot = Get-CanonicalOverlapPath $DesktopSourceRoot
    $insideDesktopTree = $recordedFull.Equals($desktopRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $recordedFull.StartsWith($desktopRoot + '\', [StringComparison]::OrdinalIgnoreCase)
    if (-not $insideDesktopTree) { return }
    $target = Get-CanonicalOverlapPath $script:SrcDir
    if ($recordedFull.Equals($target, [StringComparison]::OrdinalIgnoreCase)) { return }
    if (-not (Test-Path -LiteralPath $recorded -PathType Container)) { return }
    if (Test-WebPathContainsReparsePoint $recorded) { return }
    Warn "This machine was installed by an earlier revision that built the web app inside the"
    Warn "FlintTrade Desktop shell's own source root: $recorded"
    Warn "The desktop claims that tree and guards it with a lease no script can hold, so leaving a"
    Warn "web checkout there makes the two installs mutate one directory - and can leave the"
    Warn "desktop shell unable to bootstrap at all."
    # Every refusal below is evaluated before the dry-run report, so -DryRun
    # never promises a move this installer would not make.
    if (Test-Path -LiteralPath $DesktopOperationLease) {
        Warn "Leaving $recorded - the desktop bootstrap operation lease at $DesktopOperationLease"
        Warn "says FlintTrade Desktop is working in that tree right now. Quit FlintTrade Desktop and"
        Warn "re-run this installer to complete the move."
        return
    }
    if (Test-DesktopShellInstalled) {
        Warn "Leaving $recorded - the FlintTrade Desktop shell is installed on this machine, so that"
        Warn "checkout may be the desktop's own rather than one this installer created, and this"
        Warn "installer never moves a tree it cannot prove it owns alone."
        Warn "Decide which checkout to keep, then either delete $recorded (the desktop rebuilds its"
        Warn "own on next launch) or move it to $($script:SrcDir) yourself, and re-run this installer."
        return
    }
    $emptyDestination = $false
    if (Test-Path -LiteralPath $script:SrcDir) {
        $occupied = $true
        if (Test-Path -LiteralPath $script:SrcDir -PathType Container) {
            $existing = @(Get-ChildItem -LiteralPath $script:SrcDir -Force -ErrorAction SilentlyContinue)
            $occupied = $existing.Count -ne 0
        }
        if ($occupied) {
            Warn "Leaving $recorded - the new web source root $($script:SrcDir) already holds something,"
            Warn "and this installer will not move one checkout on top of another."
            Warn "Delete or rename whichever of the two you do not want, then re-run this installer."
            return
        }
        $emptyDestination = $true
    }
    if ($DryRun) {
        Say "DRY-RUN: would move $recorded to $($script:SrcDir) (this installer's receipt names it)."
        return
    }
    if ($emptyDestination) {
        try {
            Remove-Item -LiteralPath $script:SrcDir -Force -ErrorAction Stop
        } catch {
            Warn "Could not clear the empty $($script:SrcDir): $($_.Exception.Message)"
            return
        }
    }
    $parent = Split-Path -Parent $script:SrcDir
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    try {
        Move-Item -LiteralPath $recorded -Destination $script:SrcDir -ErrorAction Stop
        $script:MigratedWebSource = $script:SrcDir
        Say "Moved the earlier web checkout out of the desktop's source root: $recorded -> $($script:SrcDir)"
        Remove-EmptyOwnedWebDirectory (Split-Path -Parent $recorded)
    } catch {
        Warn "Could not move $recorded to $($script:SrcDir): $($_.Exception.Message)"
        Warn "Move it yourself - or delete it, once you no longer need what it holds - so the desktop"
        Warn "shell owns $DesktopSourceRoot alone, then re-run this installer."
    }
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

# -Ref is documented as "branch, tag or commit", and the archive fallback ends by
# telling the operator to re-run with -Ref <sha>. 'git clone --branch' can honour
# only the first two of those: its argument is resolved against the remote's
# branches and tags, never against an arbitrary revision, so a commit SHA failed
# on every fresh machine and made that advice unfollowable.
#
# 'git init' + 'git fetch <ref>' + 'git checkout FETCH_HEAD' accepts all three
# forms through one code path — a branch name, a tag name and a raw commit SHA
# are all valid fetch refspecs, and GitHub serves arbitrary revisions
# (uploadpack.allowAnySHA1InWant). It is also exactly what the refresh branch
# already does, so a fresh install and an update now resolve -Ref identically
# instead of disagreeing about which forms exist.
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
    if ($script:SourceUpdateOnly) {
        Fail ("Refusing to replace $($script:SrcDir): only an in-place update is authorised for a " +
              "checkout no web-install receipt names.")
    }
    Say "Fetching FlintTrade ($GitRef) into $($script:SrcDir)..."
    $parent = Split-Path -Parent $script:SrcDir
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (Test-Path -LiteralPath $script:SrcDir) {
        Remove-Item -LiteralPath $script:SrcDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $script:SrcDir | Out-Null
    & git -C $script:SrcDir init --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Could not initialise a Git checkout at $($script:SrcDir)." }
    # Recorded so every later run's Assert-SourceOriginTrusted has an origin to
    # prove; a clone used to set this, and dropping it would silently retire the
    # "is this really the official repository?" guard.
    & git -C $script:SrcDir remote add origin $RepoUrl
    if ($LASTEXITCODE -ne 0) { Fail "Could not record the FlintTrade origin in $($script:SrcDir)." }
    & git -C $script:SrcDir fetch --depth 1 origin $GitRef
    if ($LASTEXITCODE -ne 0) { Fail "Could not fetch '$GitRef' from $RepoUrl." }
    & git -C $script:SrcDir checkout --detach --force FETCH_HEAD
    if ($LASTEXITCODE -ne 0) { Fail "Could not check out '$GitRef' in $($script:SrcDir)." }
}

function Invoke-ArchiveSourceAcquisition([string]$GitRef) {
    if ($script:SourceUpdateOnly) {
        Fail ("Refusing to replace $($script:SrcDir): only an in-place update is authorised for a " +
              "checkout no web-install receipt names.")
    }
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
    Assert-DesktopSourceNotShared
    # Before the identity guard, so the migrated checkout is judged where it now
    # lives rather than refused for sitting in the desktop's tree.
    Move-LegacyWebSourceCheckout
    Assert-SourceDirSafe
    if ($DryRun) {
        if (Have git) {
            Say "DRY-RUN: would fetch $RepoUrl at '$gitRef' (branch, tag or commit) into $($script:SrcDir) and check it out"
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

# Earlier revisions installed the web launcher and its Start Menu shortcut into
# the Electron desktop shell's own locations. Retire them on a re-run, but only
# where this installer's own receipt still proves both the path and the
# byte-for-byte contents; anything else is left for the operator to judge. The
# receipt is read through the strict Get-RecordedWebInstallField above.
function Remove-EmptyOwnedWebDirectory([string]$Path) {
    if (-not $Path) { return }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return }
    $children = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
    if ($children.Count -ne 0) { return }
    try {
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    } catch {
        Warn "Could not remove the now-empty $Path; remove it by hand."
    }
}

function Remove-LegacyWebLauncher {
    if (-not $ShimPath -or -not $LegacyShimPath) { return }
    if ($ShimPath.Equals($LegacyShimPath, [StringComparison]::OrdinalIgnoreCase)) { return }
    if (-not (Test-Path -LiteralPath $LegacyShimPath -PathType Leaf)) { return }
    $recorded = Get-RecordedWebInstallField "shim="
    if (-not $recorded) { return }
    try {
        $recordedFull = [System.IO.Path]::GetFullPath($recorded)
        $legacyFull = [System.IO.Path]::GetFullPath($LegacyShimPath)
    } catch {
        return
    }
    if (-not $recordedFull.Equals($legacyFull, [StringComparison]::OrdinalIgnoreCase)) { return }
    $recordedHash = (Get-RecordedWebInstallField "shim_sha256=").ToLowerInvariant()
    if ($recordedHash -notmatch '^[0-9a-f]{64}$') { return }
    $actual = ""
    try {
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $LegacyShimPath).Hash.ToLowerInvariant()
    } catch {
        $actual = ""
    }
    if ($actual -ne $recordedHash) {
        Warn "Leaving $LegacyShimPath - it is no longer the launcher this installer recorded."
        return
    }
    # The shortcut goes first: once the launcher is gone it can no longer be
    # proved to have pointed at it.
    # The receipt may only ever aim this at the one location the earlier
    # revision wrote; it is not a general deletion instruction.
    $recordedShortcut = Get-RecordedWebInstallField "shortcut="
    if ($recordedShortcut) {
        try {
            $recordedShortcutFull = [System.IO.Path]::GetFullPath($recordedShortcut)
            $legacyShortcutFull = [System.IO.Path]::GetFullPath($LegacyStartMenuShortcut)
        } catch {
            $recordedShortcutFull = ""
            $legacyShortcutFull = "-"
        }
        if (-not $recordedShortcutFull.Equals($legacyShortcutFull, [StringComparison]::OrdinalIgnoreCase)) {
            $recordedShortcut = ""
        }
    }
    if ($recordedShortcut -and (Test-Path -LiteralPath $recordedShortcut -PathType Leaf)) {
        $target = ""
        try {
            $target = [string](New-Object -ComObject WScript.Shell).CreateShortcut($recordedShortcut).TargetPath
        } catch {
            $target = ""
        }
        if ($target -and ([System.IO.Path]::GetFullPath($target)).Equals($legacyFull, [StringComparison]::OrdinalIgnoreCase)) {
            try {
                Remove-Item -LiteralPath $recordedShortcut -Force -ErrorAction Stop
                Say "Retired the earlier Start Menu shortcut at $recordedShortcut."
                Remove-EmptyOwnedWebDirectory (Split-Path -Parent $recordedShortcut)
            } catch {
                Warn "Could not remove the earlier Start Menu shortcut at ${recordedShortcut}: $($_.Exception.Message)"
            }
        } else {
            Warn "Leaving $recordedShortcut - it no longer points at the launcher this installer recorded."
        }
    }
    try {
        Remove-Item -LiteralPath $LegacyShimPath -Force -ErrorAction Stop
        Say "Retired the earlier web launcher at $LegacyShimPath (it is now $ShimPath)."
        Remove-EmptyOwnedWebDirectory $LegacyShimDir
    } catch {
        Warn "Could not remove the earlier web launcher at ${LegacyShimPath}: $($_.Exception.Message)"
    }
}

function Install-LauncherShim([string]$PythonExecutable) {
    if (Test-Path -LiteralPath $ShimDir -PathType Leaf) {
        Fail "Refusing to replace a non-directory launcher path: $ShimDir"
    }
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
    Say "Managed source     : $($script:SrcDir)  (the desktop shell keeps its own at $DesktopActiveSource)"
    Say "Launcher           : $ShimPath  (also: flinttrade-web <subcommand>)"
    Say "Install receipt    : $WebReceiptPath  (the uninstaller removes only what this proves)"
    Say "Runner             : python scripts/ft.py <start|stop|restart|status|dev|setup|test|lint|clean|version|help|desktop-test|desktop-build|desktop-package|desktop-dev>"
    Say "Open FlintTrade at : $BackendUrl"
    Say "Uninstall          : $UninstallCommand"
    Say "                     (add -Purge to delete the workspace, tools and source too)"
    Say "----------------------------------------------------------------"
}

function Invoke-OptionalLaunch {
    if ($NoLaunch) {
        Say "Not starting FlintTrade (-NoLaunch). Start it later with: flinttrade-web start"
        return
    }
    if (-not (Confirm-Step "Start FlintTrade now?")) {
        Say "Not started. Start it later with: flinttrade-web start"
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
    # A source checkout that overlaps the desktop shell's is a configuration
    # error, not a runtime condition, so it is refused before anything is
    # probed, reported or downloaded - including under -DryRun, where reporting
    # a plan that could never run safely would be a lie.
    Assert-DesktopSourceNotShared

    $script:Target = Get-BootstrapTarget
    Say "Detected bootstrap target: $($script:Target)"

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
    Remove-LegacyWebLauncher
    Install-LauncherShim $venvPython
    Install-StartMenuShortcut
    Write-WebInstallReceipt

    Write-PathReport
    Invoke-OptionalLaunch
}

Invoke-FlintTradeWebInstall
