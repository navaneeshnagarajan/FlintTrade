# FlintTrade Electron shell uninstaller (Windows)
#
# Ordinary uninstall removes the electron-builder application and shortcuts.
# The workspace, Electron profile, managed source/toolchain and legacy desktop
# storage are kept unless -Purge is explicitly confirmed.

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
$DefaultWorkspace = Join-Path $RoamingAppDataRoot "flinttrade"
$ElectronProfile = Join-Path $RoamingAppDataRoot "flinttrade-shell"
$ManagedRoot = Join-Path $HOME ".flinttrade"
$SourceRoot = Join-Path $ManagedRoot "src"
$ToolsRoot = Join-Path $ManagedRoot "tools"
$script:RemovedAny = $false
$script:FailedAny = $false

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
        (Join-Path $shortcutDirectory "FlintTrade.lnk"),
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "FlintTrade.lnk")
    )
    foreach ($shortcutPath in $shortcutPaths) {
        if (-not (Test-Path -LiteralPath $shortcutPath)) { continue }
        $safe = $false
        if ($Record -and -not (Test-PathContainsReparsePoint $shortcutPath)) {
            $target = Get-ShortcutTarget $shortcutPath
            $safe = $target -and $Record.ExecutablePath.Equals($target, [StringComparison]::OrdinalIgnoreCase)
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
        if ($Record -and $children.Count -eq 0 -and -not (Test-PathContainsReparsePoint $shortcutDirectory)) {
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
$defaultCollision = Test-Path -LiteralPath $DefaultInstallDir
if (-not $record -and $defaultCollision) {
    Warn "Leaving an unproven same-name install directory at $DefaultInstallDir."
    $script:FailedAny = $true
}
$provenRegistryPath = if ($record) { [string]$record.RegistryPath } else { "" }
$unprovenInstallEntries = @($installEntries | Where-Object {
    -not $provenRegistryPath -or -not ([string]$_.PSPath).Equals($provenRegistryPath, [StringComparison]::OrdinalIgnoreCase)
})

Stop-ProvenShellProcesses $record
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
        } catch {
            Warn "Could not run the registered FlintTrade uninstaller: $($_.Exception.Message)"
            $script:FailedAny = $true
        }
    }
} else {
    Say "No identity-verified FlintTrade uninstaller found; leaving same-name shell residue unmodified."
}

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

function Get-DataTargets {
    $candidates = @(
        $WorkspaceDir,
        $DefaultWorkspace,
        $ElectronProfile,
        $SourceRoot,
        $ToolsRoot,
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
    $root = [System.IO.Path]::GetPathRoot($full).TrimEnd('\', '/')
    try { Get-Item -LiteralPath $Target -Force -ErrorAction Stop | Out-Null } catch { return $false }
    if (Test-PathContainsReparsePoint $Target) {
        Warn "Refusing to purge $Target because the target or one of its ancestors is a reparse point."
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

$dataTargets = @(Get-DataTargets | Where-Object { Test-SafePurgeTarget $_ })
if ($Purge) {
    if (-not $dataTargets) {
        Say "No FlintTrade data to purge."
    } elseif ($DryRun) {
        $dataTargets | ForEach-Object { Say "[dry-run] would DELETE FlintTrade data at $_" }
    } else {
        $proceed = $Yes
        if (-not $proceed) {
            try {
                $answer = Read-Host "About to DELETE the workspace, Electron profile, managed source/tools and legacy desktop storage at $($dataTargets -join ', '). This is irreversible. Type 'purge' to continue"
            } catch {
                $answer = ""
            }
            $proceed = ($answer -eq "purge")
        }
        if ($proceed) {
            Say "Purging explicitly confirmed FlintTrade data:"
            $dataTargets | ForEach-Object { Say "  $_"; Remove-IfExists $_ }
        } else {
            Say "Purge cancelled; FlintTrade data kept."
        }
    }
} elseif ($dataTargets) {
    Say "The following FlintTrade data was kept:"
    $dataTargets | ForEach-Object { Say "  $_" }
    Say "This includes the workspace, Electron profile, managed source/tools and any legacy desktop storage."
    Say "To delete it too, re-run with -Purge and confirm explicitly."
}

if ($DryRun) {
    Say "Dry run complete; nothing was deleted."
} elseif ($script:FailedAny) {
    throw "[flinttrade] Uninstall finished with some paths left behind (see above)."
} elseif ($script:RemovedAny) {
    Say "FlintTrade shell uninstalled cleanly; retained data remains available for reinstall."
} else {
    Say "Nothing to remove; the FlintTrade shell does not appear to be installed."
}
