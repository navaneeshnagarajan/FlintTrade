# FlintTrade desktop uninstaller (Windows)
#
# Default mode runs the per-user NSIS uninstaller (when present) and then
# sweeps the disposable residue the installer creates: the install folder,
# Start-menu and desktop shortcuts, and the per-user registry keys. Two kinds
# of data are ALWAYS kept unless you explicitly pass -Purge:
#   1. The FlintTrade workspace at %APPDATA%\flinttrade (encrypted credential
#      vault, auth database, journals, workspace.json).
#   2. The WebView2 profile at %LOCALAPPDATA%\com.flinttrade.app, whose
#      localStorage holds in-app saved content (trade journal notes and
#      screenshots, flow-builder workflows, saved AI chats).
#
#   irm https://flinttrade.vercel.app/uninstall.ps1 | iex
#   & ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge
#
# Environment (uninstall-specific; the install scripts never read these):
#   FLINTTRADE_UNINSTALL_PURGE=1    same as -Purge
#   FLINTTRADE_UNINSTALL_YES=1      same as -Yes (skips the typed confirmation)
#   FLINTTRADE_UNINSTALL_DRY_RUN=1  same as -DryRun
#   FLINTTRADE_WORKSPACE_DIR / FLINTTRADE_HOME are honoured the same way the
#   backend honours them when resolving the workspace to purge.

param(
    [switch]$Purge = ($env:FLINTTRADE_UNINSTALL_PURGE -eq "1"),
    [switch]$Yes = ($env:FLINTTRADE_UNINSTALL_YES -eq "1"),
    [switch]$DryRun = ($env:FLINTTRADE_UNINSTALL_DRY_RUN -eq "1")
)

$ErrorActionPreference = "Stop"

$BundleId = "com.flinttrade.app"
$InstallDir = Join-Path $env:LOCALAPPDATA "FlintTrade"
# Resolve the workspace exactly the way the backend does
# (flinttrade_core.workspace): FLINTTRADE_WORKSPACE_DIR beats FLINTTRADE_HOME
# beats %APPDATA%\flinttrade. Purging a hardcoded default while the real vault
# lives behind an override would report success and leave the data on disk.
$WorkspaceDir = if ($env:FLINTTRADE_WORKSPACE_DIR) {
    $env:FLINTTRADE_WORKSPACE_DIR
} elseif ($env:FLINTTRADE_HOME) {
    $env:FLINTTRADE_HOME
} else {
    Join-Path $env:APPDATA "flinttrade"
}
$WebViewStorageDir = Join-Path $env:LOCALAPPDATA $BundleId
$script:RemovedAny = $false
$script:FailedAny = $false

function Say([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "[flinttrade] $Message" -ForegroundColor Yellow }

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

function Remove-RegistryKeyIfExists([string]$KeyPath) {
    if (-not (Test-Path -Path $KeyPath)) { return }
    if ($DryRun) { Say "[dry-run] would remove registry key $KeyPath"; return }
    try {
        Remove-Item -Path $KeyPath -Recurse -Force -ErrorAction Stop
        Say "Removed registry key $KeyPath"
        $script:RemovedAny = $true
    } catch {
        Warn "Could not remove registry key ${KeyPath}: $($_.Exception.Message)"
        $script:FailedAny = $true
    }
}

# --- Stop the app and its backend sidecar so files are not locked. -----------
if ($DryRun) {
    Say "[dry-run] would stop any running FlintTrade app/backend"
} else {
    Get-Process -Name "FlintTrade" -ErrorAction SilentlyContinue | ForEach-Object {
        Say "Stopping FlintTrade (PID $($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    # Port 5100 is FlintTrade's backend; OpenAlgo (5000-5009) is left alone.
    # Only kill the listener if it is actually FlintTrade's backend — 5100
    # could be an unrelated local service on a machine without FlintTrade.
    $backend = Get-NetTCPConnection -LocalPort 5100 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($backend) {
        $owner = Get-Process -Id $backend.OwningProcess -ErrorAction SilentlyContinue
        if ($owner -and $owner.ProcessName -match "flinttrade") {
            Say "Stopping the FlintTrade backend (PID $($owner.Id))"
            Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
        } elseif ($owner) {
            Say "Port 5100 is held by a non-FlintTrade process ($($owner.ProcessName), PID $($owner.Id)) - leaving it alone."
        }
    }
    Start-Sleep -Seconds 1
}

# --- Run the NSIS uninstaller when it is still present. ----------------------
$Uninstaller = Join-Path $InstallDir "uninstall.exe"
if (Test-Path -LiteralPath $Uninstaller) {
    if ($DryRun) {
        Say "[dry-run] would run $Uninstaller /S"
    } else {
        Say "Running the FlintTrade uninstaller..."
        # `_?=` keeps the uninstaller synchronous (no self-copy), so -Wait is
        # honoured; the sweep below removes what it cannot delete of itself.
        # Guarded so a blocked launch (AV quarantine, AppLocker) does not
        # strand the rest of the sweep under $ErrorActionPreference = Stop.
        try {
            Start-Process -FilePath $Uninstaller -ArgumentList "/S", "_?=$InstallDir" -Wait
        } catch {
            Warn "Could not run the NSIS uninstaller: $($_.Exception.Message)"
            $script:FailedAny = $true
        }
    }
} else {
    Say "No NSIS uninstaller found - sweeping residue directly."
}

# --- Sweep disposable residue. -----------------------------------------------
# $WebViewStorageDir is NOT here: its localStorage is the only home of in-app
# journal notes, flows, and saved AI chats - it is data, removed only by -Purge.
Remove-IfExists $InstallDir
Remove-IfExists (Join-Path $env:APPDATA $BundleId)             # Tauri app-config residue
Remove-IfExists (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FlintTrade.lnk")
Remove-IfExists (Join-Path ([Environment]::GetFolderPath("Desktop")) "FlintTrade.lnk")
Remove-IfExists (Join-Path $HOME ".flinttrade\src")            # build-from-source clone

Remove-RegistryKeyIfExists "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintTrade"
Remove-RegistryKeyIfExists "HKCU:\Software\FlintTrade"
Remove-RegistryKeyIfExists "HKCU:\Software\$BundleId"

# --- FlintTrade data: kept by default, deleted only with -Purge. -------------
if ($Purge) {
    $targets = @($WorkspaceDir, $WebViewStorageDir, (Join-Path $HOME ".flinttrade")) |
        Where-Object { Test-Path -LiteralPath $_ }
    if (-not $targets) {
        Say "No FlintTrade data to purge."
    } elseif ($DryRun) {
        $targets | ForEach-Object { Say "[dry-run] would DELETE FlintTrade data at $_" }
    } else {
        $proceed = $Yes
        if (-not $proceed) {
            # In a non-interactive host Read-Host throws; treat that as a
            # refusal - -Yes (or FLINTTRADE_UNINSTALL_YES=1) is the only
            # scripted consent.
            try {
                $answer = Read-Host "About to DELETE all FlintTrade data at $($targets -join ', ') (credential vault, auth.db, journals, settings, and in-app saved content: journal notes, flows, AI chats). This is irreversible. Type 'purge' to continue"
            } catch {
                $answer = ""
            }
            $proceed = ($answer -eq "purge")
        }
        if ($proceed) {
            $targets | ForEach-Object { Remove-IfExists $_ }
        } else {
            Say "Purge cancelled - FlintTrade data kept."
        }
    }
} else {
    if (Test-Path -LiteralPath $WorkspaceDir) {
        Say "Workspace data kept at $WorkspaceDir (credential vault, journals, settings, in-app content)."
    }
    if (Test-Path -LiteralPath $WebViewStorageDir) {
        Say "In-app saved content kept at $WebViewStorageDir (content saved by older versions; current versions store journal notes, flows, and AI chats in the workspace)."
    }
    if ((Test-Path -LiteralPath $WorkspaceDir) -or (Test-Path -LiteralPath $WebViewStorageDir)) {
        Say "To delete all FlintTrade data too, re-run with -Purge (or set FLINTTRADE_UNINSTALL_PURGE=1)."
    }
}

if ($DryRun) {
    Say "Dry run complete - nothing was deleted."
} elseif ($script:FailedAny) {
    # throw, not exit: under `irm | iex` an exit terminates the user's whole
    # PowerShell session; throw surfaces the failure and gives -File callers
    # a non-zero exit code (same convention as flinttrade-install.ps1).
    throw "[flinttrade] Uninstall finished with some paths left behind (see above)."
} elseif ($script:RemovedAny) {
    Say "FlintTrade uninstalled cleanly."
} else {
    Say "Nothing to remove - FlintTrade does not appear to be installed."
}
