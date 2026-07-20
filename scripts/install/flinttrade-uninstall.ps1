# FlintTrade desktop uninstaller (Windows)
#
# Default mode runs the per-user NSIS uninstaller (when present) and then
# sweeps every application-side residue the installer or the Tauri runtime
# creates: the install folder, WebView2 profile, Start-menu and desktop
# shortcuts, and the per-user registry keys. Your trading data — the
# FlintTrade workspace at %APPDATA%\flinttrade with the encrypted credential
# vault, auth database, journals, and workspace.json — is kept unless you
# explicitly pass -Purge.
#
#   irm https://flinttrade.vercel.app/uninstall.ps1 | iex
#   & ([scriptblock]::Create((irm https://flinttrade.vercel.app/uninstall.ps1))) -Purge

param(
    [switch]$Purge = ($env:FLINTTRADE_PURGE -eq "1"),
    [switch]$Yes = ($env:FLINTTRADE_YES -eq "1"),
    [switch]$DryRun = ($env:FLINTTRADE_DRY_RUN -eq "1")
)

$ErrorActionPreference = "Stop"

$BundleId = "com.flinttrade.app"
$InstallDir = Join-Path $env:LOCALAPPDATA "FlintTrade"
$WorkspaceDir = Join-Path $env:APPDATA "flinttrade"
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
    $backend = Get-NetTCPConnection -LocalPort 5100 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($backend) {
        Say "Stopping the FlintTrade backend (PID $($backend.OwningProcess))"
        Stop-Process -Id $backend.OwningProcess -Force -ErrorAction SilentlyContinue
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
        Start-Process -FilePath $Uninstaller -ArgumentList "/S", "_?=$InstallDir" -Wait
    }
} else {
    Say "No NSIS uninstaller found — sweeping residue directly."
}

# --- Sweep application-side residue. -----------------------------------------
Remove-IfExists $InstallDir
Remove-IfExists (Join-Path $env:LOCALAPPDATA $BundleId)        # WebView2 profile (EBWebView)
Remove-IfExists (Join-Path $env:APPDATA $BundleId)             # Tauri app-config residue
Remove-IfExists (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FlintTrade.lnk")
Remove-IfExists (Join-Path ([Environment]::GetFolderPath("Desktop")) "FlintTrade.lnk")
Remove-IfExists (Join-Path $HOME ".flinttrade\src")            # build-from-source clone

Remove-RegistryKeyIfExists "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FlintTrade"
Remove-RegistryKeyIfExists "HKCU:\Software\FlintTrade"
Remove-RegistryKeyIfExists "HKCU:\Software\$BundleId"

# --- Workspace data: kept by default, deleted only with -Purge. --------------
if ($Purge) {
    $targets = @($WorkspaceDir, (Join-Path $HOME ".flinttrade")) |
        Where-Object { Test-Path -LiteralPath $_ }
    if (-not $targets) {
        Say "No workspace data to purge."
    } elseif ($DryRun) {
        $targets | ForEach-Object { Say "[dry-run] would DELETE workspace data at $_" }
    } else {
        $proceed = $Yes
        if (-not $proceed) {
            # In a non-interactive host Read-Host throws; treat that as a
            # refusal — -Yes (or FLINTTRADE_YES=1) is the only scripted consent.
            try {
                $answer = Read-Host "About to DELETE all FlintTrade data at $($targets -join ', ') (credential vault, auth.db, journals, workspace.json). This is irreversible. Type 'purge' to continue"
            } catch {
                $answer = ""
            }
            $proceed = ($answer -eq "purge")
        }
        if ($proceed) {
            $targets | ForEach-Object { Remove-IfExists $_ }
        } else {
            Say "Purge cancelled — workspace data kept."
        }
    }
} elseif (Test-Path -LiteralPath $WorkspaceDir) {
    Say "Workspace data kept at $WorkspaceDir (credential vault, journals, settings)."
    Say "To delete it too, re-run with -Purge."
}

if ($DryRun) {
    Say "Dry run complete — nothing was deleted."
} elseif ($script:FailedAny) {
    Warn "Uninstall finished with some paths left behind (see above)."
} elseif ($script:RemovedAny) {
    Say "FlintTrade uninstalled cleanly."
} else {
    Say "Nothing to remove — FlintTrade does not appear to be installed."
}
