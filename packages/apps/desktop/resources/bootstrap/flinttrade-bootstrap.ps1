# Canonical packaged source-build entrypoint. Tool acquisition and checksums are owned by Electron.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Candidate,
    [Parameter(Mandatory = $true)][string]$Uv,
    [Parameter(Mandatory = $true)][string]$Node,
    [Parameter(Mandatory = $true)][string]$CorepackJs,
    [Parameter(Mandatory = $true)][string]$ToolsRoot,
    [Parameter(Mandatory = $true)][string]$PnpmVersion
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

if ($PnpmVersion -ne "9.15.0") {
    throw "Bootstrap entrypoint requires pnpm 9.15.0."
}

@("package.json", "pyproject.toml", "uv.lock", "pnpm-lock.yaml", "packages/apps/terminal/package.json") |
    ForEach-Object {
        if (-not (Test-Path -LiteralPath (Join-Path $Candidate $_) -PathType Leaf)) {
            throw "Candidate is missing $_."
        }
    }
if (-not (Test-Path -LiteralPath $CorepackJs -PathType Leaf)) {
    throw "Verified Corepack JavaScript is missing."
}

$env:COREPACK_DEFAULT_TO_LATEST = "0"
$env:COREPACK_HOME = Join-Path $ToolsRoot "corepack"
$env:UV_CACHE_DIR = Join-Path $ToolsRoot "uv-cache"
$env:UV_NO_EDITABLE = "1"
$env:UV_PYTHON = "3.12"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsRoot "python"
$env:PATH = "$(Split-Path -Parent $Node)$([IO.Path]::PathSeparator)$env:PATH"

Invoke-Checked $Uv @("--version")
Invoke-Checked $Node @("--version")
Invoke-Checked $Node @($CorepackJs, "--version")

Push-Location $Candidate
try {
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tsyncing-python`t48`tInstalling managed Python 3.12"
    Invoke-Checked $Uv @("python", "install", "3.12")
    Invoke-Checked $Uv @("venv", "--relocatable", "--python", "3.12", ".venv")
    Invoke-Checked $Uv @("sync", "--frozen", "--all-packages", "--no-install-package", "flinttrade-ticks")
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tsyncing-javascript`t68`tInstalling pnpm 9.15.0 dependencies"
    $resolvedPnpmVersion = (& $Node $CorepackJs pnpm --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedPnpmVersion -ne "9.15.0") {
        throw "Corepack did not resolve the repository-pinned pnpm 9.15.0."
    }
    Invoke-Checked $Node @($CorepackJs, "pnpm", "install", "--frozen-lockfile")
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tbuilding-terminal`t84`tBuilding the terminal for production"
    Invoke-Checked $Node @($CorepackJs, "pnpm", "--filter", "@flinttrade/terminal", "build")
}
finally {
    Pop-Location
}
