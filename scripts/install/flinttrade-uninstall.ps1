# FlintTrade Electron shell uninstaller (Windows)
#
# Ordinary uninstall removes the electron-builder application, its shortcuts,
# the retired pre-Electron shell at %LOCALAPPDATA%\FlintTrade (the same legacy
# install flinttrade-install.ps1 retires on upgrade) and the one-line web
# install's launcher shim and Start Menu shortcut, each only when the
# installer's own receipt proves it.
# The workspace, Electron profile, managed source/toolchain, the contributor
# source-build checkout, the pre-workspace data directories and legacy desktop
# storage are kept unless -Purge is explicitly confirmed. -Purge always prints
# every resolved path first, including with -Yes, because for an upgraded
# install the pre-workspace directories still hold real trading state.

param(
    [switch]$Purge = ($env:FLINTTRADE_UNINSTALL_PURGE -eq "1"),
    [switch]$Yes = ($env:FLINTTRADE_UNINSTALL_YES -eq "1"),
    [switch]$DryRun = ($env:FLINTTRADE_UNINSTALL_DRY_RUN -eq "1")
)

$ErrorActionPreference = "Stop"
$LegacyBundleId = "com.flinttrade.app"
$LocalAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$RoamingAppDataRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
$DefaultInstallDir = Join-Path $LocalAppDataRoot "Programs\FlintTrade"
# The retired pre-Electron shell installed here with an NSIS "uninstall.exe".
# flinttrade-install.ps1 retires it on upgrade; the uninstaller had no
# counterpart, so a whole second FlintTrade stayed behind (and its registry
# entry made every uninstall fail closed).
$LegacyShellInstallDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "FlintTrade" } else { "" }
$DefaultWorkspace = Join-Path $RoamingAppDataRoot "flinttrade"
$ElectronProfile = Join-Path $RoamingAppDataRoot "flinttrade-shell"
$ManagedRoot = Join-Path $HOME ".flinttrade"
$SourceRoot = Join-Path $ManagedRoot "src"
$ToolsRoot = Join-Path $ManagedRoot "tools"
# The same installer family clones the contributor checkout here
# (flinttrade-install.ps1 -SrcDir defaults to $SourceBuildRoot\FlintTrade;
# FLINTTRADE_SRC_DIR overrides it). The Windows workspace lives under %APPDATA%,
# so nothing else in the purge list would ever reach this tree.
$SourceBuildRoot = Join-Path $ManagedRoot "source-build"
# Pre-workspace data directories. workspace.py still reads these at every
# backend start, and its migration COPIES rather than moves — so they retain a
# live copy of the DuckDB store, the append-only audit chain and the encrypted
# broker-credential vault. Purging them is real data loss for an upgraded
# install, which is why every path is printed before any confirmation.
$LegacyDataDir = Join-Path $ManagedRoot "data"
$LegacyArchiveDir = Join-Path $ManagedRoot "archive"
$LegacySandboxDir = Join-Path $ManagedRoot "sandbox"
$LegacyDittoVault = Join-Path $LegacyDataDir "ditto_credentials.db"
# Pre-workspace droppings written DIRECTLY at .flinttrade\<name> by the modules the
# workspace path-unification wave re-pointed at the resolver. Windows is the worst
# case: the real workspace is %APPDATA%\flinttrade, so everything here is a full
# second copy of state the backend now reads from somewhere else - the TOTP secret
# store and its install key, the trade journal and its screenshots, and the
# operator's own flows, models and strategy files.
#
# $ManagedRoot below would delete them all transitively, but only by never naming
# them. Enumerating each one is what makes the confirmation list honest: nobody
# should confirm an irreversible purge of their own strategy code from a list that
# does not mention it.
$LegacyFlowsDir = Join-Path $ManagedRoot "flows"
$LegacyModelsDir = Join-Path $ManagedRoot "models"
$LegacyStrategiesDir = Join-Path $ManagedRoot "strategies"
$LegacyScreenshotsDir = Join-Path $ManagedRoot "journal_screenshots"
$LegacyTotpDb = Join-Path $ManagedRoot "totp_auth.duckdb"
$LegacyTotpInstallKey = Join-Path $ManagedRoot "totp_install_key"
$LegacyJournalDb = Join-Path $ManagedRoot "journal.sqlite"
$LegacyShortcutsDb = Join-Path $ManagedRoot "shortcuts.duckdb"
$LegacyQtyFreezeDb = Join-Path $ManagedRoot "qty_freeze.duckdb"
$LegacyActionCenterDb = Join-Path $ManagedRoot "action_center.duckdb"
$LegacyWatchlistDb = Join-Path $ManagedRoot "watchlist.db"
$LegacyPresetsFile = Join-Path $ManagedRoot "presets.json"
$LegacyLatencyDb = Join-Path $ManagedRoot "latency_log.duckdb"
$LegacyTrafficDb = Join-Path $ManagedRoot "traffic_log.duckdb"
# The one-line web installer records everything it writes outside the managed
# root here (flinttrade-web-install.ps1). Without it the launcher shim and its
# Start Menu shortcut were orphaned residue. The web launcher now lives in its
# own $WebLauncherDir and its own Start Menu folder, precisely so it can never be
# confused with — or block — the Electron shell at $DefaultInstallDir; earlier
# revisions put it inside $DefaultInstallDir, so with no Electron registry record
# every uninstall reported an unproven same-name install directory and failed
# closed.
$WebLauncherDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "Programs\FlintTradeWeb" } else { "" }
$WebReceiptDir = if ($LocalAppDataRoot) { Join-Path $LocalAppDataRoot "flinttrade-web" } else { "" }
$WebReceiptPath = if ($WebReceiptDir) { Join-Path $WebReceiptDir "web-install.receipt" } else { "" }
$script:RemovedAny = $false
$script:FailedAny = $false
$script:PurgeCompleted = $false
$script:PurgedDataAny = $false
$script:DataRetainedAny = $false
$script:LegacyShellRecord = $null
$script:WebReceipt = $null
$script:WebReceiptRetained = $false
$script:WebRemovedAny = $false
$script:WebShimProven = $false
$script:ShellRemovedAny = $false

function Say([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Yellow }

function Expand-FlintPath([string]$Value) {
    if ($Value -eq "~") { return $HOME }
    if ($Value.StartsWith("~\") -or $Value.StartsWith("~/")) { return Join-Path $HOME $Value.Substring(2) }
    if ($Value.StartsWith("~")) { throw "Named-user home paths are not supported: $Value" }
    return [Environment]::ExpandEnvironmentVariables($Value)
}

$WorkspaceDir = if ($env:FLINTTRADE_WORKSPACE_DIR) {
    Expand-FlintPath $env:FLINTTRADE_WORKSPACE_DIR
} elseif ($env:FLINTTRADE_HOME) {
    Expand-FlintPath $env:FLINTTRADE_HOME
} else {
    $DefaultWorkspace
}

# A relative override otherwise resolves against the uninstaller's own working
# directory at every later use, so the path that gets printed is not necessarily
# the path that would be deleted. Resolve it once, up front.
function Resolve-AbsoluteFlintPath([string]$Value) {
    if (-not $Value) { return "" }
    try {
        return [System.IO.Path]::GetFullPath($Value).TrimEnd('\', '/')
    } catch {
        return ""
    }
}

$SrcDirOverride = if ($env:FLINTTRADE_SRC_DIR) {
    Resolve-AbsoluteFlintPath (Expand-FlintPath $env:FLINTTRADE_SRC_DIR)
} else {
    ""
}

function Remove-IfExists([string]$Target) {
    if (-not (Test-Path -LiteralPath $Target)) { return }
    if ($DryRun) { Say "[dry-run] would remove $Target"; return }
    try {
        Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction Stop
        Say "Removed $Target"
        $script:RemovedAny = $true
    } catch {
        Warn "Could not remove ${Target}: $($_.Exception.Message)"
        $script:FailedAny = $true
    }
}

function Test-PathContainsReparsePoint([string]$Target) {
    try {
        $full = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
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

function Test-OwnerLocalPath([string]$Path) {
    try {
        $owner = (Get-Acl -LiteralPath $Path).GetOwner([System.Security.Principal.SecurityIdentifier])
        if (-not $owner) { return $false }
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $allowed = @([string]$identity.User.Value)
        foreach ($group in @($identity.Groups)) { $allowed += [string]$group.Value }
        return ($allowed -contains [string]$owner.Value)
    } catch {
        return $false
    }
}

function Read-WebInstallReceipt {
    # Returns the recorded web-install identity, or $null when no web install
    # was ever recorded or the receipt does not prove itself. A missing receipt
    # is never an uninstall failure: the machine simply has no web install.
    if (-not $WebReceiptPath) { return $null }
    if (-not (Test-Path -LiteralPath $WebReceiptPath -PathType Leaf)) { return $null }
    if (Test-PathContainsReparsePoint $WebReceiptPath) {
        Warn "Leaving $WebReceiptPath because its path contains a reparse alias."
        return $null
    }
    if (-not (Test-OwnerLocalPath $WebReceiptPath)) {
        Warn "Leaving $WebReceiptPath because it is not owned by the current user."
        return $null
    }
    try {
        $lines = @(Get-Content -LiteralPath $WebReceiptPath -Encoding UTF8)
    } catch {
        Warn "Leaving $WebReceiptPath because it could not be read: $($_.Exception.Message)"
        return $null
    }
    if ($lines.Count -ne 7) {
        Warn "Leaving $WebReceiptPath because the receipt shape is invalid."
        return $null
    }
    if ($lines[0] -cne "format=flinttrade-web-install-v1" -or $lines[1] -cne "platform=Windows") {
        Warn "Leaving $WebReceiptPath because the receipt format or platform does not match."
        return $null
    }
    $prefixes = @("shim=", "shim_sha256=", "shortcut=", "source=", "tools=")
    for ($index = 0; $index -lt $prefixes.Count; $index++) {
        if (-not ([string]$lines[$index + 2]).StartsWith($prefixes[$index], [StringComparison]::Ordinal)) {
            Warn "Leaving $WebReceiptPath because the receipt field names are invalid."
            return $null
        }
    }
    $shim = ([string]$lines[2]).Substring($prefixes[0].Length)
    $shimSha256 = ([string]$lines[3]).Substring($prefixes[1].Length).ToLowerInvariant()
    $shortcut = ([string]$lines[4]).Substring($prefixes[2].Length)
    $source = ([string]$lines[5]).Substring($prefixes[3].Length)
    $tools = ([string]$lines[6]).Substring($prefixes[4].Length)
    if (-not $shim -or $shimSha256 -notmatch '^[0-9a-f]{64}$') {
        Warn "Leaving $WebReceiptPath because the receipt omits exact launcher identity."
        return $null
    }
    # The receipt may only ever aim the remover at a location the web installer
    # writes to; it is not a general deletion instruction. Both the current pair
    # and the pre-collision one are accepted: revisions before
    # %LOCALAPPDATA%\Programs\FlintTradeWeb wrote into the Electron shell's own
    # install directory and Start Menu folder, and those machines still deserve a
    # clean uninstall. Identity is never assumed from the path — the launcher is
    # removed only when its SHA-256 still matches the receipt, and the shortcut
    # only when it still points at that launcher.
    $expectedShims = @(
        (Resolve-AbsoluteFlintPath (Join-Path $WebLauncherDir "flinttrade-web.cmd")),
        (Resolve-AbsoluteFlintPath (Join-Path $DefaultInstallDir "flinttrade.cmd"))
    )
    $expectedShortcuts = @(
        (Resolve-AbsoluteFlintPath (
            Join-Path $RoamingAppDataRoot "Microsoft\Windows\Start Menu\Programs\FlintTrade Web\FlintTrade Web.lnk")),
        (Resolve-AbsoluteFlintPath (
            Join-Path $RoamingAppDataRoot "Microsoft\Windows\Start Menu\Programs\FlintTrade\FlintTrade.lnk"))
    )
    $resolvedShim = Resolve-AbsoluteFlintPath $shim
    if (-not @($expectedShims | Where-Object { $_.Equals($resolvedShim, [StringComparison]::OrdinalIgnoreCase) })) {
        Warn "Leaving $WebReceiptPath because the recorded launcher is not the installer-owned location."
        return $null
    }
    if ($shortcut) {
        $resolvedShortcut = Resolve-AbsoluteFlintPath $shortcut
        if (-not @($expectedShortcuts | Where-Object { $_.Equals($resolvedShortcut, [StringComparison]::OrdinalIgnoreCase) })) {
            Warn "Leaving $WebReceiptPath because the recorded shortcut is not the installer-owned location."
            return $null
        }
    }
    [pscustomobject]@{
        Shim = (Resolve-AbsoluteFlintPath $shim)
        ShimSha256 = $shimSha256
        Shortcut = (Resolve-AbsoluteFlintPath $shortcut)
        Source = (Resolve-AbsoluteFlintPath $source)
        Tools = (Resolve-AbsoluteFlintPath $tools)
    }
}

function Remove-EmptyOwnedDirectory([string]$Path) {
    if (-not $Path) { return }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return }
    if (Test-PathContainsReparsePoint $Path) { return }
    $children = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
    if ($children.Count -ne 0) { return }
    if ($DryRun) {
        Say "[dry-run] would remove empty directory $Path"
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
        Say "Removed $Path"
        $script:RemovedAny = $true
    } catch {
        Warn "Could not remove empty directory ${Path}: $($_.Exception.Message)"
    }
}

function Remove-ProvenWebInstall {
    $receipt = Read-WebInstallReceipt
    if (-not $receipt) { return }
    $script:WebReceipt = $receipt
    if (Test-Path -LiteralPath $receipt.Shim) {
        if (Test-PathContainsReparsePoint $receipt.Shim) {
            Warn "Leaving $($receipt.Shim) because its path contains a reparse alias."
            return
        }
        $actual = ""
        try {
            $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $receipt.Shim).Hash.ToLowerInvariant()
        } catch {
            $actual = ""
        }
        if (-not $actual -or $actual -ne $receipt.ShimSha256) {
            Warn "Leaving $($receipt.Shim) because its SHA-256 identity does not match the web-install receipt."
            Warn "Keeping $WebReceiptPath so a later run can retry."
            return
        }
        $script:WebShimProven = $true
        Remove-IfExists $receipt.Shim
        if (-not $DryRun -and (Test-Path -LiteralPath $receipt.Shim)) {
            Warn "Keeping $WebReceiptPath because the recorded launcher could not be removed."
            return
        }
        if (-not $DryRun) {
            Say "Removed the launcher recorded by $WebReceiptPath."
            $script:WebRemovedAny = $true
        }
    }
    if ($receipt.Shortcut -and (Test-Path -LiteralPath $receipt.Shortcut)) {
        $target = Get-ShortcutTarget $receipt.Shortcut
        $proven = $target -and
            ([string]$receipt.Shim).Equals([string]$target, [StringComparison]::OrdinalIgnoreCase) -and
            -not (Test-PathContainsReparsePoint $receipt.Shortcut)
        if ($proven) {
            Remove-IfExists $receipt.Shortcut
        } else {
            Warn "Leaving $($receipt.Shortcut) because it no longer points at the recorded launcher."
        }
    }
    Remove-EmptyOwnedDirectory (Split-Path -Parent $receipt.Shim)
    if ($receipt.Shortcut) { Remove-EmptyOwnedDirectory (Split-Path -Parent $receipt.Shortcut) }
    # An ordinary uninstall deliberately RETAINS the managed source and tools the
    # receipt records - and for a custom -SrcDir outside the managed root that
    # receipt is the only thing that names them. Deleting it here left a later
    # -Purge with no proof and no path, so the custom checkout was omitted
    # permanently. Keep the receipt for exactly as long as it still proves
    # retained data.
    if (Test-WebInstallDataStillPresent) {
        $script:WebReceiptRetained = $true
        Say "Keeping $WebReceiptPath - it is the only proof of the retained web-install data below,"
        Say "so a later -Purge can still find and authorise it:"
        foreach ($retained in @([string]$receipt.Source, [string]$receipt.Tools)) {
            if ($retained) { Say "  $retained" }
        }
        return
    }
    Remove-IfExists $WebReceiptPath
    Remove-EmptyOwnedDirectory $WebReceiptDir
}

# Whether anything the web-install receipt records as retained data is still on
# disk. The launcher is not retained data - it is removed by the ordinary
# uninstall - so only the managed source and tools count here.
function Test-WebInstallDataStillPresent {
    if (-not $script:WebReceipt) { return $false }
    foreach ($candidate in @([string]$script:WebReceipt.Source, [string]$script:WebReceipt.Tools)) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $true }
    }
    return $false
}

# The retained receipt is retired once it no longer proves anything: a -Purge in
# this same run has just removed the recorded source and tools, so the receipt is
# removed exactly as an ordinary uninstall would have removed it.
function Remove-RetainedWebReceipt {
    if (-not $script:WebReceiptRetained) { return }
    if ($DryRun) { return }
    if (Test-WebInstallDataStillPresent) { return }
    Remove-IfExists $WebReceiptPath
    Remove-EmptyOwnedDirectory $WebReceiptDir
}

function Get-InstallEntries {
    @(Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue) |
        Where-Object { $_.DisplayName -ceq "FlintTrade" }
}

function Get-CommandExecutable([string]$CommandLine) {
    if (-not $CommandLine) { return $null }
    $trimmed = $CommandLine.Trim()
    if ($trimmed -match '^"([^"]+)"') { return $Matches[1] }
    return ($trimmed -split '\s+', 2)[0]
}

function Test-AllowedInstallDirectory([string]$Candidate) {
    try {
        $full = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\', '/')
        $allowed = [System.IO.Path]::GetFullPath($DefaultInstallDir).TrimEnd('\', '/')
    } catch {
        return $false
    }
    return $full.Equals($allowed, [StringComparison]::OrdinalIgnoreCase)
}

function Get-ProvenInstallRecord($Entry) {
    if (-not $Entry.PSPath -or -not $Entry.UninstallString) { return $null }
    $registeredCommand = Get-CommandExecutable ([string]$Entry.UninstallString)
    if (-not $registeredCommand) { return $null }
    try {
        $registeredCommand = [Environment]::ExpandEnvironmentVariables($registeredCommand)
        $registeredFull = [System.IO.Path]::GetFullPath($registeredCommand).TrimEnd('\', '/')
        $directoryFull = [System.IO.Path]::GetFullPath((Split-Path -Parent $registeredFull)).TrimEnd('\', '/')
    } catch {
        return $null
    }
    if ((Split-Path -Leaf $registeredFull) -cne "Uninstall FlintTrade.exe") { return $null }
    if (-not (Test-AllowedInstallDirectory $directoryFull)) { return $null }
    if (-not (Test-Path -LiteralPath $directoryFull -PathType Container)) { return $null }
    if (Test-PathContainsReparsePoint $directoryFull) { return $null }

    try {
        $directory = Get-Item -LiteralPath $directoryFull -Force -ErrorAction Stop
        $canonicalDirectory = (Resolve-Path -LiteralPath $directoryFull -ErrorAction Stop).Path.TrimEnd('\', '/')
        $uninstaller = Get-Item -LiteralPath $registeredFull -Force -ErrorAction Stop
        $canonicalUninstaller = (Resolve-Path -LiteralPath $registeredFull -ErrorAction Stop).Path
        $executablePath = Join-Path $canonicalDirectory "FlintTrade.exe"
        $executable = Get-Item -LiteralPath $executablePath -Force -ErrorAction Stop
        $canonicalExecutable = (Resolve-Path -LiteralPath $executablePath -ErrorAction Stop).Path
    } catch {
        return $null
    }
    if (-not $directory.PSIsContainer -or
        ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        $uninstaller.PSIsContainer -or
        ($uninstaller.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        $executable.PSIsContainer -or
        ($executable.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        return $null
    }
    if (-not $canonicalDirectory.Equals($directoryFull, [StringComparison]::OrdinalIgnoreCase) -or
        -not $canonicalUninstaller.Equals($registeredFull, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Parent $canonicalUninstaller).Equals($canonicalDirectory, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Parent $canonicalExecutable).Equals($canonicalDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }
    if ($Entry.InstallLocation) {
        try { $installLocation = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$Entry.InstallLocation)).TrimEnd('\', '/') } catch { return $null }
        if (-not $installLocation.Equals($canonicalDirectory, [StringComparison]::OrdinalIgnoreCase)) { return $null }
    }
    if ($Entry.QuietUninstallString) {
        $quietCommand = Get-CommandExecutable ([string]$Entry.QuietUninstallString)
        try { $quietFull = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($quietCommand)).TrimEnd('\', '/') } catch { return $null }
        if (-not $quietFull.Equals($canonicalUninstaller, [StringComparison]::OrdinalIgnoreCase)) { return $null }
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
        Directory = $canonicalDirectory
        ExecutablePath = $canonicalExecutable
        UninstallerPath = $canonicalUninstaller
        RegistryPath = [string]$Entry.PSPath
    }
}

function Test-RegistryEntryStillBoundToRecord($Entry, $Record) {
    if (-not $Entry -or -not $Record -or $Entry.DisplayName -cne "FlintTrade" -or -not $Entry.UninstallString) {
        return $false
    }
    $command = Get-CommandExecutable ([string]$Entry.UninstallString)
    try { $command = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($command)).TrimEnd('\', '/') } catch { return $false }
    if (-not $command.Equals($Record.UninstallerPath, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    if ($Entry.InstallLocation) {
        try { $location = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$Entry.InstallLocation)).TrimEnd('\', '/') } catch { return $false }
        if (-not $location.Equals($Record.Directory, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    if ($Entry.QuietUninstallString) {
        $quietCommand = Get-CommandExecutable ([string]$Entry.QuietUninstallString)
        try { $quietCommand = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($quietCommand)).TrimEnd('\', '/') } catch { return $false }
        if (-not $quietCommand.Equals($Record.UninstallerPath, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    if ($Entry.DisplayIcon) {
        $displayIcon = ([string]$Entry.DisplayIcon).Trim() -replace ',\d+$', ''
        $displayIcon = $displayIcon.Trim('"')
        try { $displayIcon = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($displayIcon)).TrimEnd('\', '/') } catch { return $false }
        $allowedIcons = @($Record.ExecutablePath, (Join-Path $Record.Directory "uninstallerIcon.ico"))
        if (-not @($allowedIcons | Where-Object { $_.Equals($displayIcon, [StringComparison]::OrdinalIgnoreCase) })) {
            return $false
        }
    }
    return $true
}

function Stop-ProvenShellProcesses($Record) {
    if (-not $Record) { return }
    $expectedPath = [string]$Record.ExecutablePath
    foreach ($process in @(Get-Process -Name "FlintTrade" -ErrorAction SilentlyContinue)) {
        try {
            $processPath = (Resolve-Path -LiteralPath ([string]$process.Path) -ErrorAction Stop).Path
            $processIdentity = $process.StartTime.ToFileTimeUtc()
        } catch {
            continue
        }
        if (-not $expectedPath.Equals($processPath, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ($DryRun) {
            Say "[dry-run] would stop identity-proven FlintTrade shell process $($process.Id) at $processPath"
            continue
        }
        try {
            $current = Get-Process -Id $process.Id -ErrorAction Stop
            $currentPath = (Resolve-Path -LiteralPath ([string]$current.Path) -ErrorAction Stop).Path
            $currentIdentity = $current.StartTime.ToFileTimeUtc()
            if ($currentIdentity -ne $processIdentity -or
                -not $expectedPath.Equals($currentPath, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            Say "Stopping identity-proven FlintTrade shell process $($process.Id) at $processPath"
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        } catch {
            Warn "Could not stop the identity-proven FlintTrade shell process $($process.Id): $($_.Exception.Message)"
            $script:FailedAny = $true
        }
    }
}

function Get-ShortcutTarget([string]$ShortcutPath) {
    try {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($ShortcutPath)
        if (-not $shortcut.TargetPath) { return $null }
        return [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$shortcut.TargetPath))
    } catch {
        return $null
    }
}

function Remove-ProvenShortcuts($Record) {
    $shortcutDirectory = Join-Path $RoamingAppDataRoot "Microsoft\Windows\Start Menu\Programs\FlintTrade"
    $shortcutPaths = @(
        (Join-Path $RoamingAppDataRoot "Microsoft\Windows\Start Menu\Programs\FlintTrade.lnk"),
        (Join-Path $shortcutDirectory "FlintTrade.lnk")
    )
    # Guarded on its root like every other Join-Path here: the Desktop known
    # folder resolves to an empty string on a profile that has none (a redirected
    # or freshly provisioned one), and Join-Path then throws a raw binder error
    # that aborted the whole uninstall part-way through.
    $desktopRoot = [Environment]::GetFolderPath("Desktop")
    if ($desktopRoot) { $shortcutPaths += (Join-Path $desktopRoot "FlintTrade.lnk") }
    foreach ($shortcutPath in $shortcutPaths) {
        if (-not (Test-Path -LiteralPath $shortcutPath)) { continue }
        $safe = $false
        if ($Record -and -not (Test-PathContainsReparsePoint $shortcutPath)) {
            $target = Get-ShortcutTarget $shortcutPath
            $safe = $target -and $Record.ExecutablePath.Equals($target, [StringComparison]::OrdinalIgnoreCase)
        }
        # A shortcut left by the retired pre-Electron shell is equally proven
        # once that shell's own identity has been proved from the registry.
        if (-not $safe -and $script:LegacyShellRecord -and -not (Test-PathContainsReparsePoint $shortcutPath)) {
            $legacyTarget = Get-ShortcutTarget $shortcutPath
            $safe = $legacyTarget -and $script:LegacyShellRecord.ExecutablePath.Equals(
                $legacyTarget, [StringComparison]::OrdinalIgnoreCase)
        }
        if (-not $safe) {
            Warn "Leaving an unproven same-name shell shortcut at $shortcutPath."
            $script:FailedAny = $true
            continue
        }
        Remove-IfExists $shortcutPath
    }
    if (Test-Path -LiteralPath $shortcutDirectory -PathType Container) {
        $children = @(Get-ChildItem -LiteralPath $shortcutDirectory -Force -ErrorAction SilentlyContinue)
        $shortcutOwnerProven = $Record -or $script:LegacyShellRecord
        if ($shortcutOwnerProven -and $children.Count -eq 0 -and -not (Test-PathContainsReparsePoint $shortcutDirectory)) {
            if ($DryRun) { Say "[dry-run] would remove empty shortcut directory $shortcutDirectory" }
            else {
                try {
                    Remove-Item -LiteralPath $shortcutDirectory -Force -ErrorAction Stop
                    $script:RemovedAny = $true
                } catch {
                    Warn "Could not remove empty shortcut directory ${shortcutDirectory}: $($_.Exception.Message)"
                    $script:FailedAny = $true
                }
            }
        } else {
            Warn "Leaving non-empty same-name shortcut directory at $shortcutDirectory."
            $script:FailedAny = $true
        }
    }
}

function Get-ProvenLegacyShellRecord($Entries) {
    # The retired pre-Electron shell registered an NSIS "uninstall.exe" — a leaf
    # name Get-ProvenInstallRecord deliberately rejects, so the legacy install
    # was invisible to the uninstaller while its registry entry was reported as
    # unproven residue. Prove it exactly the way flinttrade-install.ps1's
    # Assert-VerifiedLegacyShell does before touching anything.
    if (-not $LegacyShellInstallDir -or -not (Test-Path -LiteralPath $LegacyShellInstallDir)) { return $null }
    if (Test-PathContainsReparsePoint $LegacyShellInstallDir) {
        Warn "Leaving the legacy FlintTrade shell at $LegacyShellInstallDir because its path contains a reparse alias."
        $script:FailedAny = $true
        return $null
    }
    try {
        $directory = Get-Item -LiteralPath $LegacyShellInstallDir -Force -ErrorAction Stop
        $canonicalDirectory = (Resolve-Path -LiteralPath $LegacyShellInstallDir -ErrorAction Stop).Path.TrimEnd('\', '/')
        $executablePath = Join-Path $canonicalDirectory "FlintTrade.exe"
        $uninstallerPath = Join-Path $canonicalDirectory "uninstall.exe"
        $executable = Get-Item -LiteralPath $executablePath -Force -ErrorAction Stop
        $legacyUninstaller = Get-Item -LiteralPath $uninstallerPath -Force -ErrorAction Stop
        $canonicalExecutable = (Resolve-Path -LiteralPath $executablePath -ErrorAction Stop).Path
        $canonicalUninstaller = (Resolve-Path -LiteralPath $uninstallerPath -ErrorAction Stop).Path
    } catch {
        Warn "Leaving an unproven same-name directory at ${LegacyShellInstallDir}: no legacy shell identity could be read."
        $script:FailedAny = $true
        return $null
    }
    if (-not $directory.PSIsContainer -or
        ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        $executable.PSIsContainer -or
        ($executable.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        $legacyUninstaller.PSIsContainer -or
        ($legacyUninstaller.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        -not (Split-Path -Parent $canonicalExecutable).Equals($canonicalDirectory, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Parent $canonicalUninstaller).Equals($canonicalDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        Warn "Leaving an unproven same-name directory at $LegacyShellInstallDir."
        $script:FailedAny = $true
        return $null
    }
    $matched = $null
    foreach ($entry in @($Entries)) {
        if (-not $entry.PSPath -or -not $entry.UninstallString) { continue }
        $command = Get-CommandExecutable ([string]$entry.UninstallString)
        if (-not $command) { continue }
        try {
            $commandFull = [System.IO.Path]::GetFullPath(
                [Environment]::ExpandEnvironmentVariables($command)
            ).TrimEnd('\', '/')
        } catch {
            continue
        }
        if (-not $commandFull.Equals($canonicalUninstaller, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ($matched) {
            Warn "Multiple registry entries claim the legacy FlintTrade shell; refusing ambiguous automatic retirement."
            $script:FailedAny = $true
            return $null
        }
        $matched = $entry
    }
    if (-not $matched) {
        Warn "Leaving the legacy FlintTrade shell at $canonicalDirectory because no registry entry proves its uninstaller."
        $script:FailedAny = $true
        return $null
    }
    [pscustomobject]@{
        Directory = $canonicalDirectory
        ExecutablePath = $canonicalExecutable
        UninstallerPath = $canonicalUninstaller
        RegistryPath = [string]$matched.PSPath
    }
}

function Remove-ProvenLegacyShell($LegacyRecord) {
    # Symmetric with the POSIX uninstaller's legacy cleanup, and with
    # flinttrade-install.ps1's Remove-VerifiedLegacyShell: delete the proved
    # directory outright, then drop the registry entry only while it still names
    # the exact uninstaller that was proved.
    if (-not $LegacyRecord) { return }
    if ($DryRun) {
        Say "[dry-run] would retire the legacy FlintTrade shell at $($LegacyRecord.Directory)"
        Say "[dry-run] would remove legacy registry entry $($LegacyRecord.RegistryPath)"
        return
    }
    Say "Retiring the identity-proven legacy FlintTrade shell at $($LegacyRecord.Directory)..."
    Remove-IfExists $LegacyRecord.Directory
    if (Test-Path -LiteralPath $LegacyRecord.Directory) {
        Warn "Keeping the legacy FlintTrade registry entry because $($LegacyRecord.Directory) remains."
        $script:FailedAny = $true
        return
    }
    $script:ShellRemovedAny = $true
    if (-not (Test-Path -LiteralPath $LegacyRecord.RegistryPath)) { return }
    $currentEntry = Get-ItemProperty -LiteralPath $LegacyRecord.RegistryPath -ErrorAction SilentlyContinue
    $currentCommand = if ($currentEntry) { Get-CommandExecutable ([string]$currentEntry.UninstallString) } else { "" }
    if ($currentCommand) {
        try {
            $currentCommand = [System.IO.Path]::GetFullPath(
                [Environment]::ExpandEnvironmentVariables($currentCommand)
            ).TrimEnd('\', '/')
        } catch {
            $currentCommand = ""
        }
    }
    if (-not $currentCommand -or -not $currentCommand.Equals($LegacyRecord.UninstallerPath, [StringComparison]::OrdinalIgnoreCase)) {
        Warn "Leaving the legacy FlintTrade registry entry because its identity changed during uninstall."
        $script:FailedAny = $true
        return
    }
    try {
        Remove-Item -LiteralPath $LegacyRecord.RegistryPath -Recurse -Force -ErrorAction Stop
        $script:RemovedAny = $true
    } catch {
        Warn "Could not remove legacy registry entry $($LegacyRecord.RegistryPath): $($_.Exception.Message)"
        $script:FailedAny = $true
    }
}

# Before the shell sweep, so a proved web launcher and its Start Menu shortcut
# are already gone by the time the same-name checks below look at
# $DefaultInstallDir and the shortcut directory.
Remove-ProvenWebInstall

$installEntries = @(Get-InstallEntries)
$candidateRecords = @($installEntries | ForEach-Object { Get-ProvenInstallRecord $_ } | Where-Object { $_ })
$record = if ($candidateRecords.Count -eq 1) { $candidateRecords[0] } else { $null }
if ($candidateRecords.Count -gt 1) {
    Warn "Multiple registered FlintTrade install identities were found; refusing ambiguous automatic removal."
    $script:FailedAny = $true
}
if ($record) {
    $refreshedEntry = Get-ItemProperty -LiteralPath $record.RegistryPath -ErrorAction SilentlyContinue
    $refreshedRecord = if ($refreshedEntry) { Get-ProvenInstallRecord $refreshedEntry } else { $null }
    $identityStillMatches = $refreshedRecord -and
        $refreshedRecord.Directory.Equals($record.Directory, [StringComparison]::OrdinalIgnoreCase) -and
        $refreshedRecord.ExecutablePath.Equals($record.ExecutablePath, [StringComparison]::OrdinalIgnoreCase) -and
        $refreshedRecord.UninstallerPath.Equals($record.UninstallerPath, [StringComparison]::OrdinalIgnoreCase)
    if (-not $identityStillMatches) {
        Warn "The registered FlintTrade install identity changed during validation; refusing automatic removal."
        $script:FailedAny = $true
        $record = $null
    }
}
$script:LegacyShellRecord = Get-ProvenLegacyShellRecord $installEntries
# An empty directory is not an install. The web installer's launcher shim lives
# in this same directory, so once its receipt has proved and removed the shim
# what remains is an empty folder, not unproven residue to fail the run over.
$defaultCollision = $false
if (Test-Path -LiteralPath $DefaultInstallDir -PathType Container) {
    $defaultCollision = @(Get-ChildItem -LiteralPath $DefaultInstallDir -Force -ErrorAction SilentlyContinue).Count -gt 0
} elseif (Test-Path -LiteralPath $DefaultInstallDir) {
    $defaultCollision = $true
}
if (-not $record -and $defaultCollision) {
    Warn "Leaving an unproven same-name install directory at $DefaultInstallDir."
    $script:FailedAny = $true
}
$provenRegistryPath = if ($record) { [string]$record.RegistryPath } else { "" }
$legacyRegistryPath = if ($script:LegacyShellRecord) { [string]$script:LegacyShellRecord.RegistryPath } else { "" }
$unprovenInstallEntries = @($installEntries | Where-Object {
    $entryPath = [string]$_.PSPath
    (-not $provenRegistryPath -or -not $entryPath.Equals($provenRegistryPath, [StringComparison]::OrdinalIgnoreCase)) -and
        (-not $legacyRegistryPath -or -not $entryPath.Equals($legacyRegistryPath, [StringComparison]::OrdinalIgnoreCase))
})

Stop-ProvenShellProcesses $record
Stop-ProvenShellProcesses $script:LegacyShellRecord
if ($record) {
    $executionEntry = Get-ItemProperty -LiteralPath $record.RegistryPath -ErrorAction SilentlyContinue
    $executionRecord = if ($executionEntry) { Get-ProvenInstallRecord $executionEntry } else { $null }
    $executionIdentityMatches = $executionRecord -and
        $executionRecord.RegistryPath.Equals($record.RegistryPath, [StringComparison]::OrdinalIgnoreCase) -and
        $executionRecord.Directory.Equals($record.Directory, [StringComparison]::OrdinalIgnoreCase) -and
        $executionRecord.ExecutablePath.Equals($record.ExecutablePath, [StringComparison]::OrdinalIgnoreCase) -and
        $executionRecord.UninstallerPath.Equals($record.UninstallerPath, [StringComparison]::OrdinalIgnoreCase)
    if (-not $executionIdentityMatches) {
        Warn "The registered FlintTrade install identity changed before execution; refusing to run it."
        $script:FailedAny = $true
        $record = $null
    } else {
        $record = $executionRecord
    }
}
if ($record) {
    if ($DryRun) {
        Say "[dry-run] would run $($record.UninstallerPath) /S _?=$($record.Directory)"
    } else {
        try {
            Say "Running the exact registered FlintTrade uninstaller..."
            $process = Start-Process -FilePath $record.UninstallerPath -ArgumentList @("/S", "_?=$($record.Directory)") -Wait -PassThru
            if ($process.ExitCode -ne 0) { throw "uninstaller exited with code $($process.ExitCode)" }
            $script:RemovedAny = $true
            $script:ShellRemovedAny = $true
        } catch {
            Warn "Could not run the registered FlintTrade uninstaller: $($_.Exception.Message)"
            $script:FailedAny = $true
        }
    }
} else {
    Say "No identity-verified FlintTrade uninstaller found; leaving same-name shell residue unmodified."
}

# Retire the legacy shell before the shortcut sweep so its own Start Menu entry
# is evaluated against a record that still exists.
Remove-ProvenLegacyShell $script:LegacyShellRecord

$directoryRemains = $record -and (Test-Path -LiteralPath $record.Directory)
if ($record -and -not $DryRun -and $directoryRemains) {
    Warn "The registered uninstaller left the proved install directory in place; preserving it and its registry proof for retry."
    $script:FailedAny = $true
}
if ($DryRun -or -not $directoryRemains) {
    Remove-ProvenShortcuts $record
}
foreach ($entry in $unprovenInstallEntries) {
    if ($entry.PSPath -and (Test-Path -LiteralPath $entry.PSPath)) {
        Warn "Leaving an unproven FlintTrade registry entry at $($entry.PSPath)."
        $script:FailedAny = $true
    }
}
if ($record) {
    if (-not (Test-Path -LiteralPath $record.RegistryPath)) {
        $script:RemovedAny = $true
    } elseif (-not $DryRun -and $directoryRemains) {
        Warn "Keeping the exact FlintTrade registry entry because the proved install directory remains."
        $script:FailedAny = $true
    } else {
        $currentEntry = Get-ItemProperty -LiteralPath $record.RegistryPath -ErrorAction SilentlyContinue
        if (-not (Test-RegistryEntryStillBoundToRecord $currentEntry $record)) {
            Warn "Leaving the FlintTrade registry entry because its identity changed during uninstall."
            $script:FailedAny = $true
        } elseif ($DryRun) {
            Say "[dry-run] would remove registry entry $($record.RegistryPath)"
        } else {
            try {
                Remove-Item -LiteralPath $record.RegistryPath -Recurse -Force -ErrorAction Stop
                $script:RemovedAny = $true
            } catch {
                Warn "Could not remove registry entry $($record.RegistryPath): $($_.Exception.Message)"
                $script:FailedAny = $true
            }
        }
    }
}

function Test-WebReceiptNamesSource([string]$Target) {
    if (-not $script:WebReceipt -or -not $script:WebReceipt.Source) { return $false }
    $full = Resolve-AbsoluteFlintPath $Target
    if (-not $full) { return $false }
    return $full.Equals([string]$script:WebReceipt.Source, [StringComparison]::OrdinalIgnoreCase)
}

function Test-ProvenSourceCheckout([string]$Target) {
    # An FLINTTRADE_SRC_DIR override is only honoured when an installer receipt
    # proves the checkout is FlintTrade's own; an arbitrary env var must never be
    # able to aim a recursive delete at, say, the user's Documents folder.
    if (-not $Target -or -not (Test-Path -LiteralPath $Target -PathType Container)) { return $false }
    try {
        $directory = Get-Item -LiteralPath $Target -Force -ErrorAction Stop
        if ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return $false }
    } catch {
        return $false
    }
    foreach ($marker in @(".git", "pnpm-lock.yaml", "uv.lock", "pyproject.toml")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Target $marker))) { return $false }
    }
    # Shape is not identity: those four markers are every contributor clone of
    # this repository. Recursive deletion of a source checkout is authorised only
    # by an installer-written receipt, exactly as the shell-removal path requires
    # its own registry proof.
    return (Test-WebReceiptNamesSource $Target)
}

function Get-DataTargets {
    $provenOverride = ""
    if ($SrcDirOverride) {
        if (Test-ProvenSourceCheckout $SrcDirOverride) {
            $provenOverride = $SrcDirOverride
        } elseif (Test-Path -LiteralPath $SrcDirOverride -PathType Container) {
            Say "Leaving $SrcDirOverride - no FlintTrade installer receipt proves this source checkout."
        }
    }
    $webShim = ""
    $webShortcut = ""
    $webSource = ""
    $webTools = ""
    if ($script:WebReceipt) {
        $webSource = [string]$script:WebReceipt.Source
        $webTools = [string]$script:WebReceipt.Tools
        # Only a launcher whose digest still matched the receipt is purge-eligible;
        # -Purge must not finish a deletion the ordinary path already refused.
        if ($script:WebShimProven) {
            $webShim = [string]$script:WebReceipt.Shim
            $webShortcut = [string]$script:WebReceipt.Shortcut
        }
    }
    $candidates = @(
        $WorkspaceDir,
        $DefaultWorkspace,
        $ElectronProfile,
        $SourceRoot,
        $ToolsRoot,
        $SourceBuildRoot,
        $provenOverride,
        $webSource,
        $webTools,
        $webShim,
        $webShortcut,
        $LegacyDataDir,
        $LegacyArchiveDir,
        $LegacySandboxDir,
        $LegacyDittoVault,
        # Every root-level dropping, named individually. Each is retained by the
        # copy-once workspace migration, so on an upgraded install it is a live
        # second copy of real trading state, not residue.
        $LegacyFlowsDir,
        $LegacyModelsDir,
        $LegacyStrategiesDir,
        $LegacyScreenshotsDir,
        $LegacyTotpDb,
        $LegacyTotpInstallKey,
        $LegacyJournalDb,
        $LegacyShortcutsDb,
        $LegacyQtyFreezeDb,
        $LegacyActionCenterDb,
        $LegacyWatchlistDb,
        $LegacyPresetsFile,
        $LegacyLatencyDb,
        $LegacyTrafficDb,
        # The managed root itself, after the specific paths above so the printed
        # list still names them explicitly. Around nineteen modules wrote
        # DIRECTLY at .flinttrade\<name> on Windows, so enumerating only the
        # subdirectories left TOTP secrets and realised P&L state behind while
        # claiming everything had been purged.
        $ManagedRoot,
        (Join-Path $RoamingAppDataRoot $LegacyBundleId),
        (Join-Path $LocalAppDataRoot $LegacyBundleId)
    )
    $seen = @{}
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        $key = $candidate.TrimEnd('\', '/').ToLowerInvariant()
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $candidate
        }
    }
}

function Test-ProvenCustomWorkspace([string]$Target) {
    try {
        $directory = Get-Item -LiteralPath $Target -Force -ErrorAction Stop
        if (-not $directory.PSIsContainer -or ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            return $false
        }
        $workspace = Get-Item -LiteralPath (Join-Path $Target "workspace.json") -Force -ErrorAction Stop
        if ($workspace.PSIsContainer -or ($workspace.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            return $false
        }
        foreach ($name in @("credentials.db", "auth.db", "security.db", "master_password", "api_key_pepper", "safety_gate_secret")) {
            $path = Join-Path $Target $name
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
            $marker = Get-Item -LiteralPath $path -Force
            if (-not ($marker.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { return $true }
        }
    } catch {
        return $false
    }
    return $false
}

function Test-SafePurgeTarget([string]$Target) {
    $full = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
    try { $canonical = (Resolve-Path -LiteralPath $Target -ErrorAction Stop).Path.TrimEnd('\', '/') } catch { $canonical = $full }
    $homeFull = [System.IO.Path]::GetFullPath($HOME).TrimEnd('\', '/')
    try { $homeCanonical = (Resolve-Path -LiteralPath $HOME -ErrorAction Stop).Path.TrimEnd('\', '/') } catch { $homeCanonical = $homeFull }
    $homePrefix = $homeFull + [System.IO.Path]::DirectorySeparatorChar
    $homeCanonicalPrefix = $homeCanonical + [System.IO.Path]::DirectorySeparatorChar
    $root = [System.IO.Path]::GetPathRoot($full).TrimEnd('\', '/')
    try { Get-Item -LiteralPath $Target -Force -ErrorAction Stop | Out-Null } catch { return $false }
    if (Test-PathContainsReparsePoint $Target) {
        Warn "Refusing to purge $Target because the target or one of its ancestors is a reparse point."
        $script:FailedAny = $true
        return $false
    }
    if (-not $full.StartsWith($homePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not $canonical.StartsWith($homeCanonicalPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Warn "Refusing to purge $Target because it is outside the current user's home."
        $script:FailedAny = $true
        return $false
    }
    if (-not $full -or $full -eq $homeFull -or $canonical -eq $homeCanonical -or $full -eq $root) {
        Warn "Refusing to purge $Target because it is not a FlintTrade data directory."
        $script:FailedAny = $true
        return $false
    }
    $workspaceFull = [System.IO.Path]::GetFullPath($WorkspaceDir).TrimEnd('\', '/')
    $defaultFull = [System.IO.Path]::GetFullPath($DefaultWorkspace).TrimEnd('\', '/')
    if ($full.Equals($workspaceFull, [StringComparison]::OrdinalIgnoreCase) -and
        -not $workspaceFull.Equals($defaultFull, [StringComparison]::OrdinalIgnoreCase) -and
        -not (Test-ProvenCustomWorkspace $Target)) {
        Warn "Refusing to purge $Target because custom workspace identity is not proven."
        $script:FailedAny = $true
        return $false
    }
    return $true
}

$dataTargets = @(Get-DataTargets)
if ($Purge) {
    $purgeTargets = @($dataTargets | Where-Object { Test-SafePurgeTarget $_ })
    if (-not $dataTargets) {
        Say "No FlintTrade data to purge."
    } elseif (-not $purgeTargets) {
        Say "No identity-proven FlintTrade data was eligible for purge."
    } elseif ($DryRun) {
        $purgeTargets | ForEach-Object { Say "[dry-run] would DELETE FlintTrade data at $_" }
    } else {
        # Always print the exact resolved paths before anything is deleted —
        # including under -Yes. For an upgraded install the pre-workspace
        # directories below are real trading state, not a cache.
        Say "About to DELETE the FlintTrade workspace, Electron profile, managed source/tools,"
        Say "source-build checkout, pre-workspace storage, the whole .flinttrade managed root"
        Say "and legacy desktop data listed below:"
        $purgeTargets | ForEach-Object { Say "  $_" }
        Say ".flinttrade itself also holds files written directly at its top level - the TOTP"
        Say "secret store and install key, shortcuts, the trade journal and its screenshots,"
        Say "quantity-freeze and action-centre stores, the watchlist, saved presets, and your own"
        Say "flows\, models\ and strategies\ - so purging it is real trading state, not just the"
        Say "subdirectories named above."
        Say "Any .flinttrade\data, .flinttrade\archive or .flinttrade\sandbox path above is"
        Say "pre-workspace storage that the backend still reads: the DuckDB store, the append-only"
        Say "audit chain and the encrypted broker-credential vault live there."
        $proceed = $Yes
        if (-not $proceed) {
            try {
                $answer = Read-Host "This is irreversible. Type 'purge' to continue"
            } catch {
                $answer = ""
            }
            $proceed = ($answer -eq "purge")
        }
        if ($proceed) {
            Say "Purging explicitly confirmed FlintTrade data:"
            $purgeTargets | ForEach-Object { Say "  $_"; Remove-IfExists $_ }
            if (-not $script:FailedAny) {
                $script:PurgeCompleted = $true
                $script:PurgedDataAny = $true
            }
        } else {
            Say "Purge cancelled; FlintTrade data kept."
            $script:DataRetainedAny = $true
        }
    }
} elseif ($dataTargets) {
    $script:DataRetainedAny = $true
    Say "The following FlintTrade data was kept:"
    $dataTargets | ForEach-Object { Say "  $_" }
    Say "This includes the workspace, Electron profile, managed source/tools, the source-build"
    Say "checkout, the whole .flinttrade managed root (its top-level TOTP, journal and"
    Say "screenshots, shortcuts, quantity-freeze, action-centre, watchlist, presets, flows,"
    Say "models and strategies state included), any pre-workspace .flinttrade"
    Say "data/archive/sandbox storage (including the encrypted broker-credential vault) and any"
    Say "legacy desktop storage."
    Say "To delete it too, re-run with -Purge and confirm explicitly."
}

# After the purge/keep decision above, so a confirmed -Purge that has just
# removed the recorded source and tools retires the receipt it was kept for.
Remove-RetainedWebReceipt

if ($DryRun) {
    Say "Dry run complete; nothing was deleted."
} elseif ($script:FailedAny) {
    throw "[flinttrade] Uninstall finished with some paths left behind (see above)."
} elseif ($script:PurgedDataAny -and $script:PurgeCompleted) {
    Say "FlintTrade cleanup completed; explicitly confirmed data was purged."
} elseif ($script:RemovedAny) {
    # Removing only the one-line web install's launcher is not a shell uninstall,
    # and saying so would be untrue on a machine that never had the desktop shell.
    $removalSubject = "FlintTrade shell uninstalled cleanly"
    if (-not $script:ShellRemovedAny -and $script:WebRemovedAny) {
        $removalSubject = "FlintTrade web-app launcher removed cleanly"
    }
    if ($script:DataRetainedAny) {
        Say "${removalSubject}; retained data remains available for reinstall."
    } elseif ($Purge) {
        Say "${removalSubject}; no recognised FlintTrade data was found to purge."
    } else {
        Say "${removalSubject}; no recognised FlintTrade data was found."
    }
} elseif ($script:DataRetainedAny) {
    Say "No FlintTrade shell was removed; retained data remains available for reinstall."
} else {
    Say "Nothing to remove; the FlintTrade shell does not appear to be installed."
}
