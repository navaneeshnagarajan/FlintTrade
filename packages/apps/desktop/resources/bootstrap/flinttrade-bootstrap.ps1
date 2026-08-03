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

function Write-BootstrapWarning {
    param([string]$Message)

    [Console]::Error.WriteLine("WARNING: $Message")
}

function Get-CanonicalExistingPath {
    param([string]$Path)

    $pending = [IO.Path]::GetFullPath($Path)
    for ($redirectCount = 0; $redirectCount -lt 32; $redirectCount++) {
        $root = [IO.Path]::GetPathRoot($pending)
        if (-not $root) {
            throw "Could not resolve an absolute managed Python path."
        }
        $components = @($pending.Substring($root.Length) -split '[\\/]' | Where-Object { $_ })
        $current = $root
        $item = Get-Item -LiteralPath $root -Force -ErrorAction Stop
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
            return ([IO.Path]::GetFullPath($current)).TrimEnd('\', '/')
        }
    }
    throw "Managed Python path contains too many reparse points."
}

function Get-CanonicalExistingDirectory {
    param([string]$Path)

    $canonicalPath = Get-CanonicalExistingPath $Path
    if (-not (Get-Item -LiteralPath $canonicalPath -Force -ErrorAction Stop).PSIsContainer) {
        throw "Managed Python home is not a directory."
    }
    return $canonicalPath
}

function Assert-OrdinaryManagedToolsPath {
    param([string]$Path)

    $current = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    while ($current) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing managed Python tool root because its tools path contains a linked ancestor."
        }
        $parent = Split-Path -Parent $current
        if (-not $parent -or $parent -eq $current) {
            break
        }
        $current = $parent
    }
}

function Assert-ManagedPythonTree {
    param([string]$Path)

    $rootItem = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $rootItem) {
        return
    }
    if (
        -not $rootItem.PSIsContainer -or
        ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Refusing managed Python tool root because it is linked or not a directory."
    }

    $canonicalRoot = Get-CanonicalExistingDirectory $Path
    $canonicalPrefix = "$($canonicalRoot.TrimEnd([IO.Path]::DirectorySeparatorChar))$([IO.Path]::DirectorySeparatorChar)"
    $pendingDirectories = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
    $pendingDirectories.Push($rootItem)
    while ($pendingDirectories.Count -gt 0) {
        $directory = $pendingDirectories.Pop()
        Get-ChildItem -LiteralPath $directory.FullName -Force | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                $target = [string](@($_.Target) | Select-Object -First 1)
                if (-not $target) {
                    throw "Refusing managed Python tool root because a linked entry cannot be resolved."
                }
                if (-not [IO.Path]::IsPathRooted($target)) {
                    $target = Join-Path (Split-Path -Parent $_.FullName) $target
                }
                try {
                    $targetPath = [IO.Path]::GetFullPath($target)
                    $targetParent = Get-CanonicalExistingDirectory (Split-Path -Parent $targetPath)
                    $targetLocation = Join-Path $targetParent (Split-Path -Leaf $targetPath)
                    $canonicalTarget = Get-CanonicalExistingPath $_.FullName
                }
                catch {
                    throw "Refusing managed Python tool root because a linked entry cannot be resolved."
                }
                if (
                    (
                        -not $targetPath.Equals($canonicalRoot, [StringComparison]::Ordinal) -and
                        -not $targetPath.StartsWith($canonicalPrefix, [StringComparison]::Ordinal)
                    ) -or (
                        -not $targetLocation.Equals($canonicalRoot, [StringComparison]::Ordinal) -and
                        -not $targetLocation.StartsWith($canonicalPrefix, [StringComparison]::Ordinal)
                    ) -or (
                        -not $canonicalTarget.Equals($canonicalRoot, [StringComparison]::Ordinal) -and
                        -not $canonicalTarget.StartsWith($canonicalPrefix, [StringComparison]::Ordinal)
                    )
                ) {
                    throw "Refusing managed Python tool root because a linked entry resolves outside it."
                }
            }
            elseif ($_.PSIsContainer) {
                $pendingDirectories.Push($_)
            }
        }
    }
}

function Get-ValidatedUvVenvConfiguration {
    param([string[]]$Lines, [string]$ErrorMessage)

    $values = New-Object 'System.Collections.Generic.Dictionary[string,string]' `
        ([StringComparer]::Ordinal)
    foreach ($line in $Lines) {
        $separator = $line.IndexOf('=')
        if ($separator -lt 0) {
            continue
        }
        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($key -cnotmatch '^[A-Za-z0-9_-]+$') {
            throw $ErrorMessage
        }
        $normalisedKey = $key.ToLowerInvariant()
        $usesVersionAlias = $normalisedKey -eq "version"
        if ($usesVersionAlias) {
            $normalisedKey = "version_info"
        }
        if ($normalisedKey -notin @("home", "uv", "version_info", "relocatable")) {
            continue
        }
        if (
            $usesVersionAlias -or
            $key -cne $normalisedKey -or
            $values.ContainsKey($normalisedKey)
        ) {
            throw $ErrorMessage
        }
        $values.Add($normalisedKey, $value)
    }

    if (
        $values.Count -ne 4 -or
        -not $values.ContainsKey("home") -or -not $values["home"] -or
        -not $values.ContainsKey("uv") -or $values["uv"] -cne "0.11.16" -or
        -not $values.ContainsKey("version_info") -or
        $values["version_info"] -notmatch '^3\.12\.[0-9]+$' -or
        -not $values.ContainsKey("relocatable") -or $values["relocatable"] -cne "true"
    ) {
        throw $ErrorMessage
    }
    return $values
}

function Get-OrdinaryWindowsFiles {
    param([string]$Path, [string]$ErrorMessage)

    $root = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (
        $null -eq $root -or
        -not $root.PSIsContainer -or
        ($root.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw $ErrorMessage
    }
    $pendingDirectories = New-Object 'System.Collections.Generic.Stack[System.IO.DirectoryInfo]'
    $files = New-Object 'System.Collections.Generic.List[System.IO.FileInfo]'
    $pendingDirectories.Push($root)
    while ($pendingDirectories.Count -gt 0) {
        $directory = $pendingDirectories.Pop()
        Get-ChildItem -LiteralPath $directory.FullName -Force | ForEach-Object {
            if (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw $ErrorMessage
            }
            if ($_.PSIsContainer) {
                $pendingDirectories.Push($_)
            }
            else {
                [void]$files.Add($_)
            }
        }
    }
    return $files.ToArray()
}

function Assert-OrdinaryWindowsDirectoryTree {
    param([string]$Path, [string]$ErrorMessage)

    $null = @(Get-OrdinaryWindowsFiles $Path $ErrorMessage)
}

function Assert-OrdinaryWindowsVirtualEnvironmentLaunchers {
    param([string]$Path, [string]$ErrorMessage)

    foreach ($launcherName in @("python.exe", "pythonw.exe")) {
        $launcher = Get-Item `
            -LiteralPath (Join-Path (Join-Path $Path "Scripts") $launcherName) `
            -Force `
            -ErrorAction SilentlyContinue
        if (
            $null -eq $launcher -or
            $launcher.PSIsContainer -or
            ($launcher.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw $ErrorMessage
        }
    }
}

function Assert-ValidatedVirtualEnvironmentBackup {
    param(
        [string]$Path,
        [string]$CandidatePath,
        [string]$ManagedPythonRootPath,
        [string]$ErrorMessage
    )

    $backup = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (
        $null -eq $backup -or
        -not $backup.PSIsContainer -or
        ($backup.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $backup.Name -cnotmatch '^\.venv\.flinttrade-backup-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$'
    ) {
        throw $ErrorMessage
    }
    try {
        $canonicalCandidate = Get-CanonicalExistingDirectory $CandidatePath
        $canonicalParent = Get-CanonicalExistingDirectory (Split-Path -Parent $backup.FullName)
    }
    catch {
        throw $ErrorMessage
    }
    if (-not $canonicalParent.Equals($canonicalCandidate, [StringComparison]::Ordinal)) {
        throw $ErrorMessage
    }

    Assert-OrdinaryWindowsDirectoryTree $Path $ErrorMessage
    Assert-OrdinaryWindowsVirtualEnvironmentLaunchers $Path $ErrorMessage
    $configuration = Get-Item `
        -LiteralPath (Join-Path $Path "pyvenv.cfg") `
        -Force `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $configuration -or
        $configuration.PSIsContainer -or
        ($configuration.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw $ErrorMessage
    }
    try {
        $configurationBytes = [IO.File]::ReadAllBytes($configuration.FullName)
        if (
            $configurationBytes.Length -ge 3 -and
            $configurationBytes[0] -eq 0xEF -and
            $configurationBytes[1] -eq 0xBB -and
            $configurationBytes[2] -eq 0xBF
        ) {
            throw "A UTF-8 byte-order mark is not permitted."
        }
        $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $configurationLines = @($strictUtf8.GetString($configurationBytes) -split '\r?\n')
        $configurationValues = Get-ValidatedUvVenvConfiguration $configurationLines $ErrorMessage
        $pythonHome = Get-CanonicalExistingDirectory $configurationValues["home"]
        $managedPythonRoot = Get-CanonicalExistingDirectory $ManagedPythonRootPath
    }
    catch {
        throw $ErrorMessage
    }
    $managedPythonPrefix = `
        "$($managedPythonRoot.TrimEnd([IO.Path]::DirectorySeparatorChar))$([IO.Path]::DirectorySeparatorChar)"
    if (-not $pythonHome.StartsWith($managedPythonPrefix, [StringComparison]::Ordinal)) {
        throw $ErrorMessage
    }
    Assert-ManagedPythonTree $ManagedPythonRootPath

}

function Test-ExclusiveFileAccess {
    param([string]$Path)

    $stream = $null
    try {
        # Read-only access succeeds for mapped Windows executables, so the
        # non-mutating removal probe must also request write access.
        $stream = [IO.File]::Open(
            $Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Remove-ValidatedVirtualEnvironmentBackup {
    param([string]$Path)

    $backupFiles = @(
        Get-OrdinaryWindowsFiles `
            $Path `
            "Refusing a changed or linked virtual-environment backup path during cleanup."
    )
    foreach ($backupFile in $backupFiles) {
        if (-not (Test-ExclusiveFileAccess $backupFile.FullName)) {
            Write-BootstrapWarning (
                "Deferred cleanup of the retired virtual environment because one of its " +
                "files is still in use. Blocked file: '$($backupFile.FullName)'. " +
                "Retained path: '$Path'. " +
                "FlintTrade will retry on the next installation."
            )
            return $false
        }
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
    return $true
}

function Remove-OrphanedVirtualEnvironmentBackups {
    param(
        [string]$CandidatePath,
        [string]$ManagedPythonRootPath
    )

    $orphanedBackups = @(
        Get-ChildItem `
            -LiteralPath $CandidatePath `
            -Filter ".venv.flinttrade-backup-*" `
            -Force `
            -ErrorAction Stop |
            Where-Object {
                $_.Name -cmatch '^\.venv\.flinttrade-backup-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$'
            }
    )
    foreach ($orphanedBackup in $orphanedBackups) {
        try {
            Assert-ValidatedVirtualEnvironmentBackup `
                $orphanedBackup.FullName `
                $CandidatePath `
                $ManagedPythonRootPath `
                "The retired virtual environment could not be proven safe to clean."
        }
        catch {
            Write-BootstrapWarning (
                "Preserved an unvalidated retired virtual environment at " +
                "'$($orphanedBackup.FullName)'. " +
                "Remove it manually only after confirming its exact path and contents."
            )
            continue
        }
        [void](Remove-ValidatedVirtualEnvironmentBackup $orphanedBackup.FullName)
    }
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
Assert-OrdinaryManagedToolsPath $ToolsRoot
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
$replaceVirtualEnvironment = $false
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
    try {
        $virtualEnvironmentConfigBytes = [IO.File]::ReadAllBytes($virtualEnvironmentConfig.FullName)
        if (
            $virtualEnvironmentConfigBytes.Length -ge 3 -and
            $virtualEnvironmentConfigBytes[0] -eq 0xEF -and
            $virtualEnvironmentConfigBytes[1] -eq 0xBB -and
            $virtualEnvironmentConfigBytes[2] -eq 0xBF
        ) {
            throw "A UTF-8 byte-order mark is not permitted."
        }
        $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $virtualEnvironmentConfigText = $strictUtf8.GetString($virtualEnvironmentConfigBytes)
        $virtualEnvironmentConfigLines = @($virtualEnvironmentConfigText -split '\r?\n')
    }
    catch {
        throw "Refusing existing .venv because its pyvenv.cfg is not valid BOM-less UTF-8."
    }
    $virtualEnvironmentConfigValues = Get-ValidatedUvVenvConfiguration `
        $virtualEnvironmentConfigLines `
        "Refusing existing .venv because it is not a uv-managed relocatable Python 3.12 environment."
    $pythonHome = Get-CanonicalExistingDirectory $virtualEnvironmentConfigValues["home"]
    $managedPythonRoot = Get-CanonicalExistingDirectory $managedPythonRootPath
    $managedPythonPrefix = "$($managedPythonRoot.TrimEnd([IO.Path]::DirectorySeparatorChar))$([IO.Path]::DirectorySeparatorChar)"
    if (
        -not $pythonHome.StartsWith($managedPythonPrefix, [StringComparison]::Ordinal)
    ) {
        throw "Refusing existing .venv because its Python is outside the managed tool root."
    }
    Assert-ManagedPythonTree $managedPythonRootPath
    Assert-OrdinaryWindowsDirectoryTree `
        $virtualEnvironmentPath `
        "Refusing linked entry inside .venv in the managed source checkout."
    Assert-OrdinaryWindowsVirtualEnvironmentLaunchers `
        $virtualEnvironmentPath `
        "Refusing existing .venv because its Python launchers are missing, linked, or not regular files."
    $replaceVirtualEnvironment = $true
}
Assert-ManagedPythonTree $managedPythonRootPath
Remove-OrphanedVirtualEnvironmentBackups $Candidate $managedPythonRootPath

$env:COREPACK_DEFAULT_TO_LATEST = "0"
$env:COREPACK_HOME = Join-Path $ToolsRoot "corepack"
$env:PATH = "$(Split-Path -Parent $Node)$([IO.Path]::PathSeparator)$env:PATH"

$stagingVirtualEnvironmentPath = Join-Path `
    $Candidate `
    (".venv.flinttrade-staging-" + [Guid]::NewGuid().ToString("N"))
if (Test-Path -LiteralPath $stagingVirtualEnvironmentPath) {
    throw "Refusing to overwrite an existing virtual-environment staging path."
}
$backupVirtualEnvironmentPath = Join-Path `
    $Candidate `
    (".venv.flinttrade-backup-" + [Guid]::NewGuid().ToString("N"))
if (Test-Path -LiteralPath $backupVirtualEnvironmentPath) {
    throw "Refusing to overwrite an existing virtual-environment backup path."
}
$uvEnvironmentSnapshot = @{}
Get-ChildItem Env: | Where-Object { $_.Name -like "UV_*" } | ForEach-Object {
    $uvEnvironmentSnapshot[$_.Name] = $_.Value
}
$candidateLocationPushed = $false
$stagingVirtualEnvironmentPromoted = $false
$backupVirtualEnvironmentCreated = $false
$bootstrapCompleted = $false
try {
    Get-ChildItem Env: | Where-Object { $_.Name -like "UV_*" } | ForEach-Object {
        Remove-Item -LiteralPath ("Env:\" + $_.Name)
    }
    $env:UV_CACHE_DIR = Join-Path $ToolsRoot "uv-cache"
    $env:UV_MANAGED_PYTHON = "1"
    $env:UV_NO_CONFIG = "1"
    $env:UV_NO_EDITABLE = "1"
    $env:UV_PROJECT = $Candidate
    $env:UV_PROJECT_ENVIRONMENT = $stagingVirtualEnvironmentPath
    $env:UV_PYTHON = "3.12"
    $env:UV_PYTHON_INSTALL_DIR = $managedPythonRootPath
    $env:UV_WORKING_DIR = $Candidate

    Invoke-Checked $Uv @("--version")
    Invoke-Checked $Node @("--version")
    Invoke-Checked $Node @($CorepackJs, "--version")

    Push-Location -LiteralPath $Candidate
    $candidateLocationPushed = $true
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tsyncing-python`t48`tInstalling managed Python 3.12"
    Invoke-Checked $Uv @(
        "python",
        "install",
        "3.12",
        "--no-bin",
        "--no-registry",
        "--no-config",
        "--directory",
        $Candidate
    )
    Assert-ManagedPythonTree $managedPythonRootPath
    Invoke-Checked $Uv @(
        "venv",
        "--relocatable",
        "--python",
        "3.12",
        $stagingVirtualEnvironmentPath,
        "--no-project",
        "--no-config",
        "--managed-python",
        "--directory",
        $Candidate
    )
    Invoke-Checked $Uv @(
        "sync",
        "--frozen",
        "--all-packages",
        "--no-install-package",
        "flinttrade-ticks",
        "--no-config",
        "--managed-python",
        "--directory",
        $Candidate,
        "--project",
        $Candidate
    )
    Assert-OrdinaryWindowsDirectoryTree `
        $stagingVirtualEnvironmentPath `
        "Refusing a linked entry in the staged virtual environment."
    Assert-OrdinaryWindowsVirtualEnvironmentLaunchers `
        $stagingVirtualEnvironmentPath `
        "Refusing staged .venv because its Python launchers are missing, linked, or not regular files."
    $stagedVirtualEnvironmentConfig = Get-Item `
        -LiteralPath (Join-Path $stagingVirtualEnvironmentPath "pyvenv.cfg") `
        -Force `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $stagedVirtualEnvironmentConfig -or
        $stagedVirtualEnvironmentConfig.PSIsContainer -or
        ($stagedVirtualEnvironmentConfig.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "Refusing staged .venv because it is not a regular virtual environment."
    }
    try {
        $stagedVirtualEnvironmentConfigBytes = [IO.File]::ReadAllBytes(
            $stagedVirtualEnvironmentConfig.FullName
        )
        if (
            $stagedVirtualEnvironmentConfigBytes.Length -ge 3 -and
            $stagedVirtualEnvironmentConfigBytes[0] -eq 0xEF -and
            $stagedVirtualEnvironmentConfigBytes[1] -eq 0xBB -and
            $stagedVirtualEnvironmentConfigBytes[2] -eq 0xBF
        ) {
            throw "A UTF-8 byte-order mark is not permitted."
        }
        $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $stagedVirtualEnvironmentConfigText = $strictUtf8.GetString(
            $stagedVirtualEnvironmentConfigBytes
        )
        $stagedVirtualEnvironmentConfigLines = @(
            $stagedVirtualEnvironmentConfigText -split '\r?\n'
        )
    }
    catch {
        throw "Refusing staged .venv because its pyvenv.cfg is not valid BOM-less UTF-8."
    }
    $stagedVirtualEnvironmentConfigValues = Get-ValidatedUvVenvConfiguration `
        $stagedVirtualEnvironmentConfigLines `
        "Refusing staged .venv because it is not a uv-managed relocatable Python 3.12 environment."
    $stagedPythonHome = Get-CanonicalExistingDirectory `
        $stagedVirtualEnvironmentConfigValues["home"]
    $currentManagedPythonRoot = Get-CanonicalExistingDirectory $managedPythonRootPath
    $currentManagedPythonPrefix = `
        "$($currentManagedPythonRoot.TrimEnd([IO.Path]::DirectorySeparatorChar))$([IO.Path]::DirectorySeparatorChar)"
    if (-not $stagedPythonHome.StartsWith($currentManagedPythonPrefix, [StringComparison]::Ordinal)) {
        throw "Refusing staged .venv because its Python is outside the managed tool root."
    }
    Assert-ManagedPythonTree $managedPythonRootPath
    if ($replaceVirtualEnvironment) {
        Assert-OrdinaryWindowsDirectoryTree `
            $virtualEnvironmentPath `
            "Refusing to replace a changed or linked existing virtual environment."
        $backupVirtualEnvironmentCreated = $true
        [IO.Directory]::Move($virtualEnvironmentPath, $backupVirtualEnvironmentPath)
    }
    try {
        [IO.Directory]::Move($stagingVirtualEnvironmentPath, $virtualEnvironmentPath)
        $stagingVirtualEnvironmentPromoted = $true
    }
    catch {
        if (
            $backupVirtualEnvironmentCreated -and
            -not (Test-Path -LiteralPath $virtualEnvironmentPath) -and
            (Test-Path -LiteralPath $backupVirtualEnvironmentPath -PathType Container)
        ) {
            [IO.Directory]::Move($backupVirtualEnvironmentPath, $virtualEnvironmentPath)
            $backupVirtualEnvironmentCreated = $false
        }
        throw
    }
    $env:UV_PROJECT_ENVIRONMENT = $virtualEnvironmentPath

    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tsyncing-javascript`t68`tInstalling pnpm 10.34.5 dependencies"
    $resolvedPnpmVersion = (& $Node $CorepackJs pnpm --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedPnpmVersion -ne "10.34.5") {
        throw "Corepack did not resolve the repository-pinned pnpm 10.34.5."
    }
    Invoke-Checked $Node @($CorepackJs, "pnpm", "install", "--frozen-lockfile")
    Write-Output "FLINTTRADE_BOOTSTRAP_PHASE`tbuilding-terminal`t84`tBuilding the terminal for production"
    Invoke-Checked $Node @($CorepackJs, "pnpm", "--filter", "@flinttrade/terminal", "build")
    $bootstrapCompleted = $true
}
finally {
    if ($candidateLocationPushed) {
        Pop-Location
    }
    Get-ChildItem Env: | Where-Object { $_.Name -like "UV_*" } | ForEach-Object {
        Remove-Item -LiteralPath ("Env:\" + $_.Name)
    }
    foreach ($uvEnvironmentName in $uvEnvironmentSnapshot.Keys) {
        [Environment]::SetEnvironmentVariable(
            $uvEnvironmentName,
            $uvEnvironmentSnapshot[$uvEnvironmentName],
            [EnvironmentVariableTarget]::Process
        )
    }
    $backupVirtualEnvironment = Get-Item `
        -LiteralPath $backupVirtualEnvironmentPath `
        -Force `
        -ErrorAction SilentlyContinue
    if ($null -ne $backupVirtualEnvironment) {
        Assert-ValidatedVirtualEnvironmentBackup `
            $backupVirtualEnvironmentPath `
            $Candidate `
            $managedPythonRootPath `
            "Refusing an unvalidated virtual-environment backup path during cleanup."
        if ($bootstrapCompleted) {
            $backupRemoved = Remove-ValidatedVirtualEnvironmentBackup $backupVirtualEnvironmentPath
            if ($backupRemoved) {
                $backupVirtualEnvironmentCreated = $false
            }
        }
        else {
            $currentVirtualEnvironment = Get-Item `
                -LiteralPath $virtualEnvironmentPath `
                -Force `
                -ErrorAction SilentlyContinue
            $stagedVirtualEnvironment = Get-Item `
                -LiteralPath $stagingVirtualEnvironmentPath `
                -Force `
                -ErrorAction SilentlyContinue
            if ($null -ne $currentVirtualEnvironment) {
                if ($null -ne $stagedVirtualEnvironment) {
                    throw "Virtual-environment rollback state is ambiguous."
                }
                Assert-OrdinaryWindowsDirectoryTree `
                    $virtualEnvironmentPath `
                    "Refusing to roll back a linked current virtual environment."
                [IO.Directory]::Move($virtualEnvironmentPath, $stagingVirtualEnvironmentPath)
                $stagingVirtualEnvironmentPromoted = $false
            }
            [IO.Directory]::Move($backupVirtualEnvironmentPath, $virtualEnvironmentPath)
            $backupVirtualEnvironmentCreated = $false
        }
    }
    $stagingVirtualEnvironment = Get-Item `
        -LiteralPath $stagingVirtualEnvironmentPath `
        -Force `
        -ErrorAction SilentlyContinue
    if ($null -ne $stagingVirtualEnvironment) {
        Assert-OrdinaryWindowsDirectoryTree `
            $stagingVirtualEnvironmentPath `
            "Refusing to clean a linked virtual-environment staging path."
        Remove-Item -LiteralPath $stagingVirtualEnvironmentPath -Recurse -Force
    }
}
