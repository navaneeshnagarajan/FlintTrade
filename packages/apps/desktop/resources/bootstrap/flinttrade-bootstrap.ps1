# Packaged source-build entrypoint. Tool acquisition and checksums are owned by Electron.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Candidate,
    [Parameter(Mandatory = $true)][string]$Uv,
    [Parameter(Mandatory = $true)][string]$Node,
    [Parameter(Mandatory = $true)][string]$Corepack
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

@("package.json", "pyproject.toml", "uv.lock", "pnpm-lock.yaml", "packages/apps/terminal/package.json") |
    ForEach-Object {
        if (-not (Test-Path -LiteralPath (Join-Path $Candidate $_) -PathType Leaf)) {
            throw "Candidate is missing $_."
        }
    }

$Workspace = Split-Path -Parent (Split-Path -Parent $Candidate)
$Tools = Join-Path $Workspace "tools"
$env:COREPACK_DEFAULT_TO_LATEST = "0"
$env:COREPACK_HOME = Join-Path $Tools "corepack"
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
$env:UV_NO_EDITABLE = "1"
$env:UV_PYTHON = "3.12"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:PATH = "$(Split-Path -Parent $Node)$([IO.Path]::PathSeparator)$env:PATH"

Invoke-Checked $Uv @("--version")
Invoke-Checked $Node @("--version")
Invoke-Checked $Corepack @("--version")

Push-Location $Candidate
try {
    Invoke-Checked $Uv @("python", "install", "3.12")
    Invoke-Checked $Uv @("sync", "--frozen", "--all-packages", "--no-install-package", "flinttrade-ticks")
    $pnpmVersion = (& $Corepack pnpm --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $pnpmVersion -ne "9.15.0") {
        throw "Corepack did not resolve the repository-pinned pnpm 9.15.0."
    }
    Invoke-Checked $Corepack @("pnpm", "install", "--frozen-lockfile")
    Invoke-Checked $Corepack @("pnpm", "--filter", "@flinttrade/terminal", "build")
}
finally {
    Pop-Location
}
