<#
.SYNOPSIS
    Ensures the Prettier CLI is available as a user-level npm global.
.DESCRIPTION
    Uses a user-owned npm prefix so `prettier` works in future terminals without
    administrator rights or writing into the Node.js install directory.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageName = Get-DevSetupValue $config "advanced.prettier.npmPackage" "prettier"
$packageSpec = Get-DevSetupValue $config "advanced.prettier.npmPackageSpec" "prettier@latest"
$globalPrefix = Expand-DevSetupPath (Get-DevSetupValue $config "advanced.prettier.windowsGlobalPrefix" "$env:USERPROFILE\.npm-global")

function Get-PrettierCommand {
    $command = Get-Command prettier.cmd -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if ($command) { return $command }

    $candidate = Join-Path $globalPrefix "prettier.cmd"
    if (Test-Path $candidate) { return $candidate }

    return $null
}

function Get-NpmCommand {
    Update-DevSetupSessionPath
    Get-Command npm.cmd -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
}

function Get-NodeCommand {
    Update-DevSetupSessionPath
    Get-Command node.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
}

function Set-PrettierNpmPrefix {
    param([Parameter(Mandatory)][string]$NpmCommand)

    if (-not (Test-Path $globalPrefix)) {
        New-Item -Path $globalPrefix -ItemType Directory -Force | Out-Null
    }

    $currentPrefix = (& $NpmCommand config get prefix).Trim()
    if ($currentPrefix.TrimEnd([char]'\') -ne $globalPrefix.TrimEnd([char]'\')) {
        & $NpmCommand config set prefix $globalPrefix | Out-Null
        Write-DevSetupStatus install "npm" "global prefix -> $globalPrefix"
    } else {
        Write-DevSetupStatus found "npm" "global prefix already $globalPrefix"
    }

    Add-DevSetupUserPath $globalPrefix -Prepend
    $env:Path = "$globalPrefix;$env:Path"
}

function Get-PrettierVersion {
    param(
        [Parameter(Mandatory)][string]$PrettierCommand,
        [string]$NodeCommand
    )

    $entryPoint = Join-Path $globalPrefix "node_modules\prettier\bin\prettier.cjs"
    if ($NodeCommand -and (Test-Path $entryPoint)) {
        return ((& $NodeCommand $entryPoint --version 2>$null | Select-Object -First 1) -as [string]).Trim()
    }

    return ((& $PrettierCommand --version 2>$null | Select-Object -First 1) -as [string]).Trim()
}

function Test-PrettierNpmUpgrade {
    param(
        [Parameter(Mandatory)][string]$NpmCommand,
        [Parameter(Mandatory)][string]$PackageName,
        [Parameter(Mandatory)][string]$PrettierCommand,
        [string]$NodeCommand
    )

    $installedVersion = Get-PrettierVersion -PrettierCommand $PrettierCommand -NodeCommand $NodeCommand
    $latestVersion = ((& $NpmCommand view $PackageName version 2>$null | Select-Object -First 1) -as [string]).Trim()
    if ($installedVersion -and $latestVersion -and $installedVersion -ne $latestVersion) {
        Write-DevSetupStatus update "Prettier" "newer version available: installed $installedVersion, latest $latestVersion (run: npm update --global $PackageName)"
    }
}

$nodeCommand = Get-NodeCommand
$npmCommand = Get-NpmCommand
if ($nodeCommand) {
    $nodeDirectory = Split-Path -Parent $nodeCommand
    $env:Path = "$nodeDirectory;$env:Path"
}
$prettierCommand = Get-PrettierCommand

if ($Uninstall) {
    if (-not $npmCommand) {
        Write-DevSetupStatus warn "Prettier" "npm is unavailable; cannot uninstall"
        return
    }
    if ($Audit) {
        Write-DevSetupStatus remove "Prettier" "would uninstall $packageName via npm"
        return
    }
    Set-PrettierNpmPrefix -NpmCommand $npmCommand
    & $npmCommand uninstall --global $packageName | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-DevSetupStatus remove "Prettier" "uninstalled $packageName via npm"
    } else {
        Write-DevSetupStatus warn "Prettier" "npm uninstall failed (exit $LASTEXITCODE)"
    }
    return
}

if ($Audit) {
    if ($prettierCommand) {
        Write-DevSetupStatus found "Prettier" "$(Get-PrettierVersion -PrettierCommand $prettierCommand -NodeCommand $nodeCommand) at $prettierCommand"
    } elseif ($nodeCommand -and $npmCommand) {
        Write-DevSetupStatus install "Prettier" "would install $packageSpec via npm using prefix $globalPrefix"
    } elseif (Get-DevSetupValue $config "user.install.node" $true) {
        Write-DevSetupStatus install "Prettier" "would install $packageSpec after Node.js/npm are available"
    } else {
        Write-DevSetupStatus warn "Prettier" "missing and Node.js/npm are unavailable; enable user.install.node or install Node.js first"
    }

    if ($CheckUpgrades -and $npmCommand -and $prettierCommand) {
        Test-PrettierNpmUpgrade -NpmCommand $npmCommand -PackageName $packageName -PrettierCommand $prettierCommand -NodeCommand $nodeCommand
    }
    return
}

if (-not $nodeCommand -or -not $npmCommand) {
    throw "Prettier requires Node.js and npm, but one or both were not found. Run the Node.js step first, then run setup again."
}

if (-not $prettierCommand) {
    Set-PrettierNpmPrefix -NpmCommand $npmCommand
    Write-DevSetupStatus install "Prettier" "installing $packageSpec via npm (user global)"
    & $npmCommand install --global $packageSpec
    if ($LASTEXITCODE -ne 0) { throw "npm failed to install $packageSpec (exit code $LASTEXITCODE)" }
    $prettierCommand = Get-PrettierCommand
} elseif ($prettierCommand -like "$globalPrefix\*") {
    Add-DevSetupUserPath $globalPrefix -Prepend
    $env:Path = "$globalPrefix;$env:Path"
}

if (-not $prettierCommand) {
    throw "Prettier setup completed but prettier.cmd was not found. Open a new terminal and run setup again."
}

Write-DevSetupStatus found "Prettier" "$(Get-PrettierVersion -PrettierCommand $prettierCommand -NodeCommand $nodeCommand) at $prettierCommand"

if ($CheckUpgrades) {
    Test-PrettierNpmUpgrade -NpmCommand $npmCommand -PackageName $packageName -PrettierCommand $prettierCommand -NodeCommand $nodeCommand
}