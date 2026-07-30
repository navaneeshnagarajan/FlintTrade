# FlintTrade Electron shell installer / updater (Windows)
#
# The default path installs the published Windows x64 Electron shell. On first
# launch, the shell acquires and builds verified FlintTrade source. The
# contributor-only -BuildFromSource path packages only the Electron shell.
#
#   irm https://flinttrade.vercel.app/install.ps1 | iex
#
# Parameters:
#   -Channel beta|stable  Release channel to install (default: beta)
#   -Ref <tag>            Install an exact release tag
#   -BuildFromSource      Package the Electron shell from a trusted checkout
#   -SrcDir <dir>         Checkout used by -BuildFromSource.
#                         Default: $HOME\.flinttrade\source-build\FlintTrade
#                         Override with the FLINTTRADE_SRC_DIR environment
#                         variable (the parameter wins over the variable).
#                         The web installer (flinttrade-web-install.ps1) deprecates
#                         FLINTTRADE_SRC_DIR in favour of FLINTTRADE_WEB_SRC_DIR
#                         for its managed source checkout.
#   -Update               Alias for the default install/update flow
#   -Yes                  Compatibility flag for the bundled updater
#   -NoLaunch             Do not launch FlintTrade after installing
#   -DryRun               Resolve and verify policy without installing
#
# Where things land:
#   $HOME\.flinttrade\source-build\FlintTrade   the -SrcDir checkout, multi-GB
#                                               once built
# It sits under $HOME\.flinttrade so `uninstall.ps1 -Purge` can find and remove
# it; the workspace itself stays in %APPDATA%\flinttrade.

param(
    [string]$Channel = $(if ($env:FLINTTRADE_CHANNEL) { $env:FLINTTRADE_CHANNEL } else { "beta" }),
    [string]$Ref = $env:FLINTTRADE_REF,
    [string]$SrcDir = $(if ($env:FLINTTRADE_SRC_DIR) { $env:FLINTTRADE_SRC_DIR } else { Join-Path $HOME ".flinttrade\source-build\FlintTrade" }),
    [switch]$BuildFromSource = ($env:FLINTTRADE_BUILD_FROM_SOURCE -eq "1"),
    [switch]$Update,
    [switch]$Yes = ($env:FLINTTRADE_YES -eq "1"),
    [switch]$NoLaunch = ($env:FLINTTRADE_NO_LAUNCH -eq "1"),
    [switch]$DryRun = ($env:FLINTTRADE_DRY_RUN -eq "1")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoSlug = "navaneeshnagarajan/FlintTrade"
$RepoUrl = "https://github.com/$RepoSlug.git"
$GitHubApiBase = "https://api.github.com/repos/$RepoSlug"
$ReleaseDownloadBase = "https://github.com/$RepoSlug/releases/download"
$ReleaseApiOverride = $env:FLINTTRADE_GITHUB_RELEASES_API
$PinnedPnpmVersion = "10.34.5"
$LocalAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$LegacyShellInstallDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "FlintTrade" } else { "" }
$DefaultElectronInstallDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "Programs\FlintTrade" } else { "" }
$ReleaseTagPattern = '^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
$script:ReleaseAssetVerified = $false
$script:UpdateAttestationBound = $false
$script:WindowsUpdateInstallDir = $null
$script:VerifiedLegacyShell = $null

function Say([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Yellow }
function Fail([string]$Message) {
    Write-Host "[flinttrade] ERROR: $Message" -ForegroundColor Red
    throw "[flinttrade] $Message"
}
function Have([string]$Command) { $null -ne (Get-Command $Command -ErrorAction SilentlyContinue) }

function Invoke-Pnpm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
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
    Fail "pnpm $PinnedPnpmVersion is required through Corepack, npx, or a matching binary."
}

function ConvertTo-FlintSemVer([string]$Tag) {
    $match = [Regex]::Match(
        $Tag,
        '^v(?<major>0|[1-9]\d*)\.(?<minor>0|[1-9]\d*)\.(?<patch>0|[1-9]\d*)(?:-(?<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
    )
    if (-not $match.Success) { return $null }
    $prerelease = if ($match.Groups['pre'].Success) { @($match.Groups['pre'].Value -split '\.') } else { @() }
    [pscustomobject]@{
        Core = @($match.Groups['major'].Value, $match.Groups['minor'].Value, $match.Groups['patch'].Value)
        Prerelease = $prerelease
        Tag = $Tag
    }
}

function Compare-NumericSemVerIdentifier([string]$Left, [string]$Right) {
    if ($Left.Length -ne $Right.Length) { return $(if ($Left.Length -lt $Right.Length) { -1 } else { 1 }) }
    $comparison = [string]::CompareOrdinal($Left, $Right)
    if ($comparison -eq 0) { return 0 }
    return $(if ($comparison -lt 0) { -1 } else { 1 })
}

function Compare-FlintSemVer($Left, $Right) {
    for ($index = 0; $index -lt 3; $index++) {
        $comparison = Compare-NumericSemVerIdentifier $Left.Core[$index] $Right.Core[$index]
        if ($comparison -ne 0) { return $comparison }
    }
    if ($Left.Prerelease.Count -eq 0 -or $Right.Prerelease.Count -eq 0) {
        if ($Left.Prerelease.Count -eq $Right.Prerelease.Count) { return 0 }
        return $(if ($Left.Prerelease.Count -eq 0) { 1 } else { -1 })
    }
    $length = [Math]::Max($Left.Prerelease.Count, $Right.Prerelease.Count)
    for ($index = 0; $index -lt $length; $index++) {
        if ($index -ge $Left.Prerelease.Count) { return -1 }
        if ($index -ge $Right.Prerelease.Count) { return 1 }
        $leftPart = [string]$Left.Prerelease[$index]
        $rightPart = [string]$Right.Prerelease[$index]
        if ($leftPart -ceq $rightPart) { continue }
        $leftNumeric = $leftPart -cmatch '^\d+$'
        $rightNumeric = $rightPart -cmatch '^\d+$'
        if ($leftNumeric -and $rightNumeric) {
            return (Compare-NumericSemVerIdentifier $leftPart $rightPart)
        }
        if ($leftNumeric -ne $rightNumeric) { return $(if ($leftNumeric) { -1 } else { 1 }) }
        $comparison = [string]::CompareOrdinal($leftPart, $rightPart)
        return $(if ($comparison -lt 0) { -1 } else { 1 })
    }
    return 0
}

function Resolve-LatestReleaseTag([string[]]$Tags) {
    $best = $null
    foreach ($tag in $Tags) {
        $candidate = ConvertTo-FlintSemVer $tag
        if (-not $candidate) { continue }
        if (-not $best -or (Compare-FlintSemVer $candidate $best) -gt 0) { $best = $candidate }
    }
    if ($best) { return $best.Tag }
    return $null
}

function Test-ReleaseTagForChannel([string]$Tag, [string]$WantedChannel) {
    $semver = ConvertTo-FlintSemVer $Tag
    if (-not $semver) { return $false }
    if ($WantedChannel -eq "stable") { return $semver.Prerelease.Count -eq 0 }
    return $semver.Prerelease.Count -eq 0 -or $semver.Prerelease[0] -ceq "beta"
}

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

function Get-ReleaseApiUrl {
    if ($ReleaseApiOverride) {
        if ($ReleaseApiOverride.StartsWith("https://")) { return $ReleaseApiOverride }
        if ($ReleaseApiOverride.StartsWith("file://") -and $env:FLINTTRADE_ALLOW_LOCAL_ASSET -eq "1") {
            return $ReleaseApiOverride
        }
        Fail "Refusing non-HTTPS GitHub release API override."
    }
    if ($Ref) {
        return "$GitHubApiBase/releases/tags/$([Uri]::EscapeDataString($Ref))"
    }
    return "$GitHubApiBase/releases?per_page=100"
}

function Test-CompleteWindowsRelease($Release) {
    $tag = [string]$Release.tag_name
    if ($tag -cnotmatch $ReleaseTagPattern) { return $false }
    $version = $tag -replace '^v', ''
    $assetName = "FlintTrade-$version-win-x64.exe"
    $assetMatches = @(@($Release.assets) | Where-Object {
        $_.name -ceq $assetName -and $_.browser_download_url -ceq "$ReleaseDownloadBase/$tag/$assetName"
    })
    $sumsMatches = @(@($Release.assets) | Where-Object {
        $_.name -ceq "SHA256SUMS.txt" -and $_.browser_download_url -ceq "$ReleaseDownloadBase/$tag/SHA256SUMS.txt"
    })
    return $assetMatches.Count -eq 1 -and $sumsMatches.Count -eq 1
}

function Get-SelectedRelease {
    if ($Channel -ne "beta" -and $Channel -ne "stable") { Fail "-Channel must be beta or stable." }
    if ($Ref -and $Ref -cnotmatch $ReleaseTagPattern) {
        Fail "-Ref must be a semantic-version release tag such as v0.6.0-beta.13."
    }
    $apiUrl = Get-ReleaseApiUrl
    Say "Resolving FlintTrade shell release from GitHub ($apiUrl)..."
    try {
        $response = Invoke-RestMethod -Uri $apiUrl -Headers @{
            Accept = "application/vnd.github+json"
            "X-GitHub-Api-Version" = "2022-11-28"
        }
    } catch {
        Fail "Could not query the official GitHub release API: $($_.Exception.Message)"
    }

    $releases = @($response) | Where-Object {
        $candidateTag = [string]$_.tag_name
        if ($_.draft -or $candidateTag -cnotmatch $ReleaseTagPattern) { return $false }
        $tagIsPrerelease = $candidateTag -cmatch '^v[^+]*-'
        return ([bool]$_.prerelease) -eq $tagIsPrerelease
    }
    if ($Ref) {
        $release = $releases | Where-Object { $_.tag_name -eq $Ref } | Select-Object -First 1
    } elseif ($Channel -eq "beta") {
        # The beta channel advances to a subsequently published stable release,
        # matching the in-app updater's prerelease-to-stable progression.
        $release = $releases |
            Where-Object { -not $_.prerelease -or ([string]$_.tag_name -cmatch '-beta(?:\.|\+|$)') } |
            Where-Object { Test-CompleteWindowsRelease $_ } |
            Select-Object -First 1
    } else {
        $release = $releases |
            Where-Object { -not $_.prerelease } |
            Where-Object { Test-CompleteWindowsRelease $_ } |
            Select-Object -First 1
    }
    if (-not $release) {
        if ($Ref) { Fail "No non-draft release was found for exact ref $Ref." }
        Fail "No complete non-draft $Channel release was found for Windows x64."
    }
    return $release
}

function Assert-TrustedReleaseAsset([string]$Url, [string]$Tag, [string]$Name) {
    $expected = "$ReleaseDownloadBase/$Tag/$Name"
    if ($Url -cne $expected) { Fail "Refusing asset URL outside the selected official release: $Url" }
}

function Get-Checksum([string]$Text, [string]$AssetName) {
    $escapedName = [Regex]::Escape($AssetName)
    $matches = [Regex]::Matches($Text, "(?im)^([0-9a-f]{64})\s+\*?$escapedName\s*$")
    if ($matches.Count -ne 1) {
        Fail "SHA256SUMS.txt does not contain exactly one valid checksum for $AssetName."
    }
    return $matches[0].Groups[1].Value.ToLowerInvariant()
}

function Get-CanonicalExistingPath([string]$Path, [string]$Label) {
    try {
        return (Resolve-Path -LiteralPath ([Environment]::ExpandEnvironmentVariables($Path)) -ErrorAction Stop).Path.TrimEnd('\', '/')
    } catch {
        Fail "$Label cannot be resolved to an existing path."
    }
}

function Test-WindowsPathContainsReparsePoint([string]$Path) {
    try {
        $full = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
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

function Get-CommandExecutable([string]$CommandLine) {
    if (-not $CommandLine) { return $null }
    $trimmed = $CommandLine.Trim()
    if ($trimmed -match '^"([^"]+)"') { return $Matches[1] }
    return ($trimmed -split '\s+', 2)[0]
}

function Get-ProvenDefaultElectronRegistryEntry($Entry) {
    if (-not $Entry.PSPath -or $Entry.DisplayName -cne "FlintTrade" -or -not $Entry.UninstallString) {
        return $null
    }
    $command = Get-CommandExecutable ([string]$Entry.UninstallString)
    try {
        $directory = [System.IO.Path]::GetFullPath($DefaultElectronInstallDir).TrimEnd('\', '/')
        $uninstaller = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($command)).TrimEnd('\', '/')
    } catch {
        return $null
    }
    if (-not $uninstaller.Equals((Join-Path $directory "Uninstall FlintTrade.exe"), [StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $directory -PathType Container) -or
        (Test-WindowsPathContainsReparsePoint $directory)) {
        return $null
    }
    try {
        $directoryItem = Get-Item -LiteralPath $directory -Force -ErrorAction Stop
        $canonicalDirectory = (Resolve-Path -LiteralPath $directory -ErrorAction Stop).Path.TrimEnd('\', '/')
        $uninstallerItem = Get-Item -LiteralPath $uninstaller -Force -ErrorAction Stop
        $canonicalUninstaller = (Resolve-Path -LiteralPath $uninstaller -ErrorAction Stop).Path
        $executablePath = Join-Path $canonicalDirectory "FlintTrade.exe"
        $executableItem = Get-Item -LiteralPath $executablePath -Force -ErrorAction Stop
        $canonicalExecutable = (Resolve-Path -LiteralPath $executablePath -ErrorAction Stop).Path
    } catch {
        return $null
    }
    if (-not $directoryItem.PSIsContainer -or
        ($directoryItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        $uninstallerItem.PSIsContainer -or
        ($uninstallerItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        $executableItem.PSIsContainer -or
        ($executableItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        -not $canonicalDirectory.Equals($directory, [StringComparison]::OrdinalIgnoreCase) -or
        -not $canonicalUninstaller.Equals($uninstaller, [StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }
    if ($Entry.InstallLocation) {
        try { $location = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$Entry.InstallLocation)).TrimEnd('\', '/') } catch { return $null }
        if (-not $location.Equals($canonicalDirectory, [StringComparison]::OrdinalIgnoreCase)) { return $null }
    }
    if ($Entry.QuietUninstallString) {
        $quietCommand = Get-CommandExecutable ([string]$Entry.QuietUninstallString)
        try { $quietCommand = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($quietCommand)).TrimEnd('\', '/') } catch { return $null }
        if (-not $quietCommand.Equals($canonicalUninstaller, [StringComparison]::OrdinalIgnoreCase)) { return $null }
    }
    if ($Entry.DisplayIcon) {
        $displayIcon = ([string]$Entry.DisplayIcon).Trim() -replace ',\d+$', ''
        $displayIcon = $displayIcon.Trim('"')
        try { $displayIcon = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($displayIcon)).TrimEnd('\', '/') } catch { return $null }
        $allowedIcons = @($canonicalExecutable, (Join-Path $canonicalDirectory "uninstallerIcon.ico"))
        if (-not @($allowedIcons | Where-Object { $_.Equals($displayIcon, [StringComparison]::OrdinalIgnoreCase) })) {
            return $null
        }
    }
    [pscustomobject]@{
        RegistryPath = [string]$Entry.PSPath
        Directory = $canonicalDirectory
        ExecutablePath = $canonicalExecutable
        UninstallerPath = $canonicalUninstaller
    }
}

function Assert-WindowsFreshInstallAdmission {
    if ($Update) { return }
    if (-not $DefaultElectronInstallDir) { Fail "LOCALAPPDATA is required for a per-user Electron shell install." }
    if (Test-WindowsPathContainsReparsePoint $DefaultElectronInstallDir) {
        Fail "The default Electron install path contains a reparse alias; refusing an unsafe shell replacement."
    }
    $entries = @(
        @(Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue) |
            Where-Object { $_.DisplayName -ceq "FlintTrade" }
    )
    $electronRecords = @($entries | ForEach-Object { Get-ProvenDefaultElectronRegistryEntry $_ } | Where-Object { $_ })
    $legacyRegistryPath = if ($script:VerifiedLegacyShell) { [string]$script:VerifiedLegacyShell.RegistryPath } else { "" }
    $provedRegistryPaths = @($electronRecords | ForEach-Object { [string]$_.RegistryPath })
    $unprovedEntries = @($entries | Where-Object {
        $path = [string]$_.PSPath
        $isElectron = @($provedRegistryPaths | Where-Object { $_.Equals($path, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
        $isLegacy = $legacyRegistryPath -and $legacyRegistryPath.Equals($path, [StringComparison]::OrdinalIgnoreCase)
        -not $isElectron -and -not $isLegacy
    })
    if ($unprovedEntries.Count -gt 0) {
        Fail "An unproven same-name FlintTrade registry identity exists; refusing to let NSIS overwrite it."
    }
    $targetExists = Test-Path -LiteralPath $DefaultElectronInstallDir
    if ($targetExists -and $electronRecords.Count -ne 1) {
        Fail "The default Electron install directory exists without one exact registered FlintTrade identity; refusing to overwrite it."
    }
    if (-not $targetExists -and $electronRecords.Count -ne 0) {
        Fail "A stale Electron registry identity exists without its exact install directory; refusing an ambiguous install."
    }
    if ($electronRecords.Count -gt 1) {
        Fail "Multiple Electron install identities target the default directory; refusing an ambiguous install."
    }
}

function Assert-WindowsUpdateTarget {
    $requested = $env:FLINTTRADE_UPDATE_WINDOWS_INSTALL_DIR
    if (-not $requested -or -not [System.IO.Path]::IsPathRooted($requested)) {
        Fail "The Windows updater requires the exact absolute running install directory."
    }
    if (-not $DefaultElectronInstallDir) {
        Fail "LOCALAPPDATA is required for a per-user Electron shell update."
    }
    $full = [System.IO.Path]::GetFullPath($requested).TrimEnd('\', '/')
    $canonical = Get-CanonicalExistingPath $requested "The Windows updater target"
    $allowed = [System.IO.Path]::GetFullPath($DefaultElectronInstallDir).TrimEnd('\', '/')
    if (-not $full.Equals($canonical, [StringComparison]::OrdinalIgnoreCase) -or
        -not $canonical.Equals($allowed, [StringComparison]::OrdinalIgnoreCase) -or
        (Test-WindowsPathContainsReparsePoint $canonical)) {
        Fail "The Windows updater target must be the canonical, ordinary per-user Electron install directory."
    }

    $entries = @(
        @(Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue) |
            Where-Object { $_.DisplayName -ceq "FlintTrade" }
    )
    $records = @($entries | ForEach-Object { Get-ProvenDefaultElectronRegistryEntry $_ } | Where-Object { $_ })
    if ($entries.Count -ne 1 -or $records.Count -ne 1 -or
        -not $records[0].Directory.Equals($canonical, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "The updater requires one exact HKCU electron-builder FlintTrade identity at the default per-user install directory."
    }

    $probe = Join-Path $canonical ".flinttrade-update-probe-$([Guid]::NewGuid().ToString('N'))"
    try {
        $stream = [System.IO.File]::Open($probe, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $stream.Dispose()
        Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
    } catch {
        if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
        Fail "The exact running Windows install directory is not writable."
    }
    $script:WindowsUpdateInstallDir = $canonical
}

function Assert-VerifiedLegacyShell {
    $script:VerifiedLegacyShell = $null
    if (-not $LegacyShellInstallDir -or -not (Test-Path -LiteralPath $LegacyShellInstallDir)) { return }
    if (Test-WindowsPathContainsReparsePoint $LegacyShellInstallDir) {
        Fail "The legacy desktop-shell install path contains a reparse alias; refusing a duplicate install."
    }
    $legacyDirectory = Get-Item -LiteralPath $LegacyShellInstallDir -Force -ErrorAction Stop
    $legacyExecutablePath = Join-Path $LegacyShellInstallDir "FlintTrade.exe"
    $legacyUninstallerPath = Join-Path $LegacyShellInstallDir "uninstall.exe"
    if (-not $legacyDirectory.PSIsContainer -or ($legacyDirectory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        -not (Test-Path -LiteralPath $legacyExecutablePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $legacyUninstallerPath -PathType Leaf)) {
        Fail "A legacy-looking FlintTrade directory exists but its desktop-shell identity is not proven; refusing a duplicate install."
    }
    foreach ($path in @($legacyExecutablePath, $legacyUninstallerPath)) {
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            Fail "The legacy desktop shell contains a reparse alias; refusing a duplicate install."
        }
    }
    if ($script:WindowsUpdateInstallDir -and
        $script:WindowsUpdateInstallDir.Equals($LegacyShellInstallDir, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "The running Electron shell is co-located with legacy desktop-shell files; automatic retirement is unsafe."
    }
    $legacyEntry = Get-ItemProperty -LiteralPath "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintTrade" -ErrorAction SilentlyContinue
    if (-not $legacyEntry -or $legacyEntry.DisplayName -cne "FlintTrade" -or -not $legacyEntry.UninstallString) {
        Fail "The legacy desktop shell has no matching registered uninstaller; refusing a duplicate install."
    }
    $command = ([string]$legacyEntry.UninstallString).Trim()
    $registeredPath = if ($command -match '^"([^"]+)"') { $Matches[1] } else { ($command -split '\s+', 2)[0] }
    try { $registeredPath = (Resolve-Path -LiteralPath $registeredPath -ErrorAction Stop).Path } catch {
        Fail "The registered legacy desktop-shell uninstaller cannot be resolved."
    }
    $expectedPath = (Resolve-Path -LiteralPath $legacyUninstallerPath -ErrorAction Stop).Path
    if (-not $registeredPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "The registered legacy desktop-shell uninstaller does not match the legacy install directory."
    }

    $script:VerifiedLegacyShell = [pscustomobject]@{
        Directory = (Resolve-Path -LiteralPath $LegacyShellInstallDir -ErrorAction Stop).Path
        ExecutablePath = (Resolve-Path -LiteralPath $legacyExecutablePath -ErrorAction Stop).Path
        UninstallerPath = $expectedPath
        RegistryPath = if ($legacyEntry.PSPath) { [string]$legacyEntry.PSPath } else { "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintTrade" }
    }
}

function Remove-VerifiedLegacyShell {
    if (-not $script:VerifiedLegacyShell) { return }
    $verified = $script:VerifiedLegacyShell
    if (-not (Test-Path -LiteralPath $verified.Directory -PathType Container)) {
        Fail "The verified legacy desktop shell changed before retirement; refusing to remove an unknown path."
    }
    $legacyDirectory = Get-Item -LiteralPath $verified.Directory -Force -ErrorAction Stop
    $currentDirectory = (Resolve-Path -LiteralPath $verified.Directory -ErrorAction Stop).Path
    if (($legacyDirectory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        -not $currentDirectory.Equals($verified.Directory, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "The verified legacy desktop shell changed before retirement; refusing to remove an unknown path."
    }
    foreach ($path in @($verified.ExecutablePath, $verified.UninstallerPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
            ((Get-Item -LiteralPath $path -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            Fail "The verified legacy desktop shell changed before retirement; refusing to remove an unknown path."
        }
    }

    Say "Retiring the identity-verified legacy desktop shell while preserving its workspace and WebView data..."
    Remove-Item -LiteralPath $verified.Directory -Recurse -Force -ErrorAction Stop

    # The new NSIS setup may have reused this registry key. Remove it only when
    # it still identifies the exact legacy uninstaller that was proved above.
    $currentEntry = Get-ItemProperty -LiteralPath $verified.RegistryPath -ErrorAction SilentlyContinue
    if ($currentEntry -and $currentEntry.UninstallString) {
        $command = ([string]$currentEntry.UninstallString).Trim()
        $currentUninstaller = if ($command -match '^"([^"]+)"') { $Matches[1] } else { ($command -split '\s+', 2)[0] }
        try {
            $currentUninstaller = [System.IO.Path]::GetFullPath(
                [Environment]::ExpandEnvironmentVariables($currentUninstaller)
            )
        } catch {
            Fail "The legacy FlintTrade registry entry changed before retirement; leaving it for manual review."
        }
        if ($currentUninstaller.Equals($verified.UninstallerPath, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $verified.RegistryPath -Recurse -Force -ErrorAction Stop
        }
    }
    $script:VerifiedLegacyShell = $null
}

function Signal-UpdateHandoff {
    if ($DryRun -or -not $env:FLINTTRADE_UPDATE_HANDOFF) { return }
    if (-not $Update) { Fail "The verified installer handoff requires explicit -Update mode." }
    if (-not $script:ReleaseAssetVerified) { Fail "Refusing an updater handoff before release checksum verification." }
    if (-not $script:UpdateAttestationBound) { Fail "Refusing an updater handoff before app-verified release attestation binding." }
    $parentPid = 0
    if (-not [int]::TryParse($env:FLINTTRADE_UPDATE_PARENT_PID, [ref]$parentPid) -or $parentPid -le 1 -or $parentPid -eq $PID) {
        Fail "The verified installer handoff requires a valid exact parent PID."
    }
    try {
        $parent = Get-Process -Id $parentPid -ErrorAction Stop
        $parentIdentity = $parent.StartTime.ToFileTimeUtc()
    } catch {
        Fail "The verified installer handoff parent is not available: $($_.Exception.Message)"
    }
    try {
        New-Item -ItemType File -Path $env:FLINTTRADE_UPDATE_HANDOFF -ErrorAction Stop | Out-Null
    } catch {
        Fail "Could not signal the verified installer handoff: $($_.Exception.Message)"
    }

    $timeout = 3600
    if ($env:FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS) {
        if (-not [int]::TryParse($env:FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS, [ref]$timeout) -or $timeout -lt 1 -or $timeout -gt 3900) {
            Fail "The update-parent timeout must be between 1 and 3900 seconds."
        }
    }
    $activeWaitIterations = $timeout * 5
    for ($elapsed = 0; $elapsed -lt $activeWaitIterations; $elapsed++) {
        try {
            $current = Get-Process -Id $parentPid -ErrorAction Stop
            $currentIdentity = $current.StartTime.ToFileTimeUtc()
        } catch {
            return
        }
        if ($currentIdentity -ne $parentIdentity) {
            # The exact parent exited and Windows reused its numeric PID.
            return
        }
        [System.Threading.Thread]::Sleep(200)
    }
    try {
        $current = Get-Process -Id $parentPid -ErrorAction Stop
        if ($current.StartTime.ToFileTimeUtc() -ne $parentIdentity) { return }
    } catch {
        return
    }
    Fail "The verified shell installer timed out waiting for its exact Electron parent to exit; no installed shell was changed."
}

function Install-BinaryRelease {
    if ($Update -and -not $env:FLINTTRADE_UPDATE_HANDOFF) {
        Fail "-Update requires the private verified installer handoff environment."
    }
    if ($Update) { Assert-WindowsUpdateTarget }
    Assert-VerifiedLegacyShell
    Assert-WindowsFreshInstallAdmission
    $arch = Get-WindowsArch
    if ($arch -eq "arm64") {
        Say "No native Windows ARM64 shell is published; installing x64 under Windows emulation."
        $arch = "x64"
    }
    if ($arch -ne "x64") { Fail "The current release supports Windows x64 only. Detected: $arch." }

    $release = Get-SelectedRelease
    $tag = [string]$release.tag_name
    if ($tag -cnotmatch $ReleaseTagPattern) { Fail "GitHub returned an invalid release tag." }
    if ($Ref -and $tag -cne $Ref) { Fail "GitHub returned tag $tag while $Ref was requested." }
    $version = $tag -replace '^v', ''
    $assetName = "FlintTrade-$version-win-x64.exe"
    $sumsName = "SHA256SUMS.txt"
    $assetMatches = @(@($release.assets) | Where-Object { $_.name -ceq $assetName })
    $sumsMatches = @(@($release.assets) | Where-Object { $_.name -ceq $sumsName })
    if ($assetMatches.Count -eq 0) { Fail "Release $tag has no required $assetName shell installer." }
    if ($sumsMatches.Count -eq 0) { Fail "Release $tag has no required SHA256SUMS.txt asset." }
    if ($assetMatches.Count -ne 1) { Fail "Release $tag must contain exactly one $assetName shell installer." }
    if ($sumsMatches.Count -ne 1) { Fail "Release $tag must contain exactly one SHA256SUMS.txt asset." }
    $asset = $assetMatches[0]
    $sumsAsset = $sumsMatches[0]
    Assert-TrustedReleaseAsset ([string]$asset.browser_download_url) $tag $assetName
    Assert-TrustedReleaseAsset ([string]$sumsAsset.browser_download_url) $tag $sumsName

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "flinttrade-$([Guid]::NewGuid().ToString('N'))"
    $installer = Join-Path $tempRoot $assetName
    $sumsPath = Join-Path $tempRoot $sumsName
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    try {
        Invoke-WebRequest -Uri $sumsAsset.browser_download_url -OutFile $sumsPath -UseBasicParsing
        $expectedHash = Get-Checksum (Get-Content -LiteralPath $sumsPath -Raw) $assetName
        if ($env:FLINTTRADE_UPDATE_HANDOFF) {
            $attestedName = $env:FLINTTRADE_UPDATE_ASSET_NAME
            $attestedHash = $env:FLINTTRADE_UPDATE_ASSET_SHA256
            if ($attestedName -cne $assetName) {
                Fail "The selected installer name did not match the app-verified release attestation."
            }
            if (-not $attestedHash -or $attestedHash -cnotmatch '^[0-9a-f]{64}$') {
                Fail "The app-verified release attestation digest was invalid."
            }
            if ($expectedHash -cne $attestedHash) {
                Fail "SHA256SUMS.txt did not match the app-verified release attestation digest."
            }
            $expectedHash = $attestedHash
            $script:UpdateAttestationBound = $true
        }
        if ($DryRun) {
            Say "DRY-RUN: would download $assetName"
            Say "DRY-RUN: $($asset.browser_download_url)"
            Say "DRY-RUN: would verify sha256 $expectedHash from $($sumsAsset.browser_download_url)"
            Say "DRY-RUN: would run $installer"
            return
        }

        Say "Downloading $assetName..."
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installer -UseBasicParsing
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            Fail "Checksum mismatch for $assetName. Expected $expectedHash, got $actualHash."
        }
        Say "Verified SHA-256 checksum from the selected release."
        $script:ReleaseAssetVerified = $true
        Unblock-File -LiteralPath $installer -ErrorAction SilentlyContinue
        Assert-VerifiedLegacyShell
        Assert-WindowsFreshInstallAdmission
        Signal-UpdateHandoff
        Say "Running FlintTrade setup..."
        if ($Update) {
            # The detached in-app updater has no visible console or wizard
            # owner. electron-builder's force-run flag relaunches the updated
            # app after its silent one-click NSIS install completes.
            $setup = Start-Process -FilePath $installer -ArgumentList @(
                "/S",
                "--force-run",
                "/D=$script:WindowsUpdateInstallDir"
            ) -Wait -PassThru
        } elseif ($NoLaunch) {
            $setup = Start-Process -FilePath $installer -ArgumentList "/S" -Wait -PassThru
        } else {
            $setup = Start-Process -FilePath $installer -Wait -PassThru
        }
        if ($setup.ExitCode -ne 0) { Fail "FlintTrade setup exited with code $($setup.ExitCode)." }
        Remove-VerifiedLegacyShell
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Say "Done. First launch builds the verified local source checkout. Rerun this installer only for shell updates."
}

function Assert-TrustedSourceOrigin {
    if (-not (Test-Path -LiteralPath (Join-Path $SrcDir ".git"))) { return }
    $origin = (& git -C $SrcDir remote get-url origin 2>$null).Trim()
    $repoUrlWithoutSuffix = $RepoUrl.Substring(0, $RepoUrl.Length - 4)
    if ($origin -cne $RepoUrl -and $origin -cne $repoUrlWithoutSuffix) {
        Fail "Refusing to update $SrcDir because origin is not the official HTTPS FlintTrade repository."
    }
}

function Assert-IsolatedSourceBuildTarget {
    $sourcePath = [System.IO.Path]::GetFullPath($SrcDir).TrimEnd('\', '/')
    $managedPath = [System.IO.Path]::GetFullPath((Join-Path $HOME ".flinttrade\src")).TrimEnd('\', '/')
    if (Test-Path -LiteralPath $sourcePath) {
        $sourcePath = (Resolve-Path -LiteralPath $sourcePath).Path.TrimEnd('\', '/')
    }
    if (Test-Path -LiteralPath $managedPath) {
        $managedPath = (Resolve-Path -LiteralPath $managedPath).Path.TrimEnd('\', '/')
    }
    if ($sourcePath.Equals($managedPath, [StringComparison]::OrdinalIgnoreCase) -or
        $sourcePath.StartsWith("$managedPath$([System.IO.Path]::DirectorySeparatorChar)", [StringComparison]::OrdinalIgnoreCase)) {
        Fail "Source-build mode refuses to mutate the managed active source tree."
    }
}

function Assert-SourcePrerequisites {
    $missing = @()
    if (-not (Have git)) { $missing += "Git from https://git-scm.com" }
    if (Have node) {
        $nodeVersion = [version]((& node -p "process.versions.node").Trim())
        if ($nodeVersion -lt [version]"22.12.0") { $missing += "Node.js >= 22.12 (found v$nodeVersion)" }
    } else {
        $missing += "Node.js >= 22.12"
    }
    $hasPinnedPnpm = $false
    if (Have pnpm) { $hasPinnedPnpm = ((pnpm --version 2>$null).Trim() -eq $PinnedPnpmVersion) }
    if (-not (Have corepack) -and -not (Have npx) -and -not $hasPinnedPnpm) {
        $missing += "pnpm $PinnedPnpmVersion through Corepack, npx, or a matching binary"
    }
    $compiler = if ($env:WINDIR) {
        Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    } else {
        $null
    }
    if (-not $compiler -or -not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
        $missing += "the trusted .NET Framework x64 compiler required for native desktop helpers"
    }
    if ($missing.Count -gt 0) {
        Warn "Missing source-build prerequisites:"
        $missing | ForEach-Object { Warn "  - $_" }
        Fail "Install the tools above, then rerun with -BuildFromSource."
    }
}

function Build-FromSource {
    Say "Source-build mode packages only the Electron shell. Checking Git, Node, pnpm and the native compiler..."
    Assert-VerifiedLegacyShell
    Assert-WindowsFreshInstallAdmission
    Assert-IsolatedSourceBuildTarget
    Assert-SourcePrerequisites
    Assert-TrustedSourceOrigin
    if ($DryRun) {
        $target = if ($Ref) { $Ref } else { "the newest release tag" }
        Say "DRY-RUN: would clone or update the pinned repository at $target"
        Say "DRY-RUN: would install the frozen JavaScript workspace and package only @flinttrade/desktop with pnpm $PinnedPnpmVersion"
        return
    }

    if (-not $Ref) {
        Say "Resolving newest release tag from the official repository..."
        $tags = @(git ls-remote --tags --refs $RepoUrl "v*" |
            ForEach-Object { ($_ -split "/")[-1] } |
            Where-Object { $_ -cmatch $ReleaseTagPattern -and (Test-ReleaseTagForChannel $_ $Channel) })
        $script:Ref = Resolve-LatestReleaseTag $tags
        if (-not $Ref) { Fail "Could not resolve a release tag from $RepoUrl." }
    }

    if (Test-Path -LiteralPath (Join-Path $SrcDir ".git")) {
        Say "Updating trusted source workspace at $SrcDir..."
        git -C $SrcDir fetch --tags $RepoUrl
        if ($LASTEXITCODE -ne 0) { Fail "Git fetch from the official repository failed." }
        git -C $SrcDir checkout --quiet $Ref
        if ($LASTEXITCODE -ne 0) { Fail "Git could not check out $Ref." }
    } else {
        Say "Cloning FlintTrade ($Ref) into $SrcDir..."
        New-Item -ItemType Directory -Force -Path (Split-Path $SrcDir) | Out-Null
        git clone --branch $Ref --depth 1 $RepoUrl $SrcDir
        if ($LASTEXITCODE -ne 0) { Fail "Git clone from the official repository failed." }
    }
    Push-Location $SrcDir
    try {
        Say "Installing the frozen JavaScript workspace with pnpm $PinnedPnpmVersion..."
        Invoke-Pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { Fail "pnpm install failed." }
        Say "Packaging the Electron NSIS installer..."
        Invoke-Pnpm --dir packages/apps/desktop run pack:win
        if ($LASTEXITCODE -ne 0) { Fail "Electron packaging failed." }
    } finally {
        Pop-Location
    }

    $version = $Ref -replace '^v', ''
    $installer = Join-Path $SrcDir "packages\apps\desktop\release\electron\FlintTrade-$version-win-x64.exe"
    if (-not (Test-Path -LiteralPath $installer)) { Fail "Electron packaging completed without $installer." }
    Say "Built: $installer"
    Assert-VerifiedLegacyShell
    Assert-WindowsFreshInstallAdmission
    if ($NoLaunch) {
        $setup = Start-Process -FilePath $installer -ArgumentList "/S" -Wait -PassThru
    } else {
        $setup = Start-Process -FilePath $installer -Wait -PassThru
    }
    if ($setup.ExitCode -ne 0) { Fail "FlintTrade setup exited with code $($setup.ExitCode)." }
    Remove-VerifiedLegacyShell
}

if ($env:FLINTTRADE_RESOLVE_TAGS_ONLY -eq "1") {
    $tags = @(([Console]::In.ReadToEnd() -split "`r?`n") |
        Where-Object { $_ -and (Test-ReleaseTagForChannel $_ $Channel) })
    $latest = Resolve-LatestReleaseTag $tags
    if ($latest) { Write-Output $latest }
} elseif ($BuildFromSource) {
    Build-FromSource
} else {
    Install-BinaryRelease
}
