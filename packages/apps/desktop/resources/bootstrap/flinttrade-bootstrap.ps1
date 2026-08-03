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

function Get-CanonicalExistingDirectory {
    param([string]$Path)

    $pending = [IO.Path]::GetFullPath($Path)
    for ($redirectCount = 0; $redirectCount -lt 32; $redirectCount++) {
        $root = [IO.Path]::GetPathRoot($pending)
        if (-not $root) {
            throw "Could not resolve an absolute managed Python path."
        }
        $components = @($pending.Substring($root.Length) -split '[\\/]' | Where-Object { $_ })
        $current = $root
        $redirected = $false
        for ($index = 0; $index -lt $components.Count; $index++) {
            $current = Join-Path $current $components[$index]
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) {
                continue
            }
            $target = [string](@($item.Target) | Select-Object -First 1)
            if (-not $target) {
                throw "Could not resolve a managed Python reparse point."
            }
            if (-not [IO.Path]::IsPathRooted($target)) {
                $target = Join-Path (Split-Path -Parent $current) $target
            }
            $pending = [IO.Path]::GetFullPath($target)
            for ($remaining = $index + 1; $remaining -lt $components.Count; $remaining++) {
                $pending = Join-Path $pending $components[$remaining]
            }
            $redirected = $true
            break
        }
        if (-not $redirected) {
            if (-not $item.PSIsContainer) {
                throw "Managed Python home is not a directory."
            }
            return ([IO.Path]::GetFullPath($current)).TrimEnd('\', '/')
        }
    }
    throw "Managed Python path contains too many reparse points."
}

if ($PnpmVersion -ne "10.34.5") {
    throw "Bootstrap entrypoint requires pnpm 10.34.5."
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

$managedPythonRootPath = Join-Path $ToolsRoot "python"
$managedPythonRootItem = Get-Item -LiteralPath $managedPythonRootPath -Force -ErrorAction SilentlyContinue
if (
    $null -ne $managedPythonRootItem -and (
        -not $managedPythonRootItem.PSIsContainer -or
        ($managedPythonRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    )
) {
    throw "Refusing managed Python tool root because it is linked or not a directory."
}

$virtualEnvironmentPath = Join-Path $Candidate ".venv"
$virtualEnvironment = Get-Item -LiteralPath $virtualEnvironmentPath -Force -ErrorAction SilentlyContinue
$reuseVirtualEnvironment = $false
if ($null -ne $virtualEnvironment) {
    if (($virtualEnvironment.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing linked .venv in the managed source checkout."
    }
    $virtualEnvironmentConfig = Get-Item `
        -LiteralPath (Join-Path $virtualEnvironmentPath "pyvenv.cfg") `
        -Force `
        -ErrorAction SilentlyContinue
    if (
        -not $virtualEnvironment.PSIsContainer -or
        $null -eq $virtualEnvironmentConfig -or
        $virtualEnvironmentConfig.PSIsContainer -or
        ($virtualEnvironmentConfig.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Refusing existing .venv because it is not a regular virtual environment."
    }
    $virtualEnvironmentConfigLines = Get-Content -LiteralPath $virtualEnvironmentConfig.FullName
    if (
        -not ($virtualEnvironmentConfigLines -match '^uv = \S+$') -or
        -not ($virtualEnvironmentConfigLines -match '^version_info = 3\.12\.[0-9]+$') -or
        -not ($virtualEnvironmentConfigLines -match '^relocatable = true$')
    ) {
        throw "Refusing existing .venv because it is not a uv-managed relocatable Python 3.12 environment."
    }
    $pythonHomeLines = @($virtualEnvironmentConfigLines | Where-Object { $_ -match '^home = .+$' })
    if ($pythonHomeLines.Count -ne 1) {
        throw "Refusing existing .venv because its managed Python home is invalid."
    }
    $pythonHome = Get-CanonicalExistingDirectory ($pythonHomeLines[0].Substring("home = ".Length))
    $managedPythonRoot = Get-CanonicalExistingDirectory $managedPythonRootPath
    $managedPythonPrefix = "$($managedPythonRoot.TrimEnd([IO.Path]::DirectorySeparatorChar))$([IO.Path]::DirectorySeparatorChar)"
    if (
        -not $pythonHome.StartsWith($managedPythonPrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Refusing existing .venv because its Python is outside the managed tool root."
    }
    $pendingEnvironmentDirectories = New-Object `
        'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
    $pendingEnvironmentDirectories.Push($virtualEnvironment)
    while ($pendingEnvironmentDirectories.Count -gt 0) {
        $environmentDirectory = $pendingEnvironmentDirectories.Pop()
        Get-ChildItem -LiteralPath $environmentDirectory.FullName -Force | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing linked entry inside .venv in the managed source checkout."
            }
            if ($_.PSIsContainer) {
                $pendingEnvironmentDirectories.Push($_)
            }
        }
    }
    $reuseVirtualEnvironment = $true
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

Push-Location -LiteralPath $Candidate
try {
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tsyncing-python`t48`tInstalling managed Python 3.12"
    if (-not $reuseVirtualEnvironment) {
        Invoke-Checked $Uv @("python", "install", "3.12")
        Invoke-Checked $Uv @("venv", "--relocatable", "--python", "3.12", ".venv")
    }
    Invoke-Checked $Uv @("sync", "--frozen", "--all-packages", "--no-install-package", "flinttrade-ticks")
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tsyncing-javascript`t68`tInstalling pnpm 10.34.5 dependencies"
    $resolvedPnpmVersion = (& $Node $CorepackJs pnpm --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedPnpmVersion -ne "10.34.5") {
        throw "Corepack did not resolve the repository-pinned pnpm 10.34.5."
    }
    Invoke-Checked $Node @($CorepackJs, "pnpm", "install", "--frozen-lockfile")
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tbuilding-terminal`t84`tBuilding the terminal for production"
    Invoke-Checked $Node @($CorepackJs, "pnpm", "--filter", "@flinttrade/terminal", "build")
}
finally {
    Pop-Location
}
