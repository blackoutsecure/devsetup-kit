<# Ensures GPG is available for Git commit/tag signing. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$gitInstallDir = Expand-DevSetupPath (Get-DevSetupValue $config "user.git.installDir" (
    Get-DevSetupValue $config "advanced.git.defaultInstallDir" "$env:USERPROFILE\PortableGit"))
$portableGitRelativePath = Get-DevSetupValue $config "advanced.gpg.portableGitRelativePath" "usr\bin\gpg.exe"
$portableGpg = Join-Path $gitInstallDir $portableGitRelativePath
$portableGit = Join-Path $gitInstallDir "cmd\git.exe"

function Get-BundledGitGpg {
    param([string]$GitExe)

    if (-not $GitExe) { return $null }
    $gitCommandDirectory = Split-Path -Parent $GitExe
    $gitRoot = Split-Path -Parent $gitCommandDirectory
    $candidate = Join-Path $gitRoot $portableGitRelativePath
    if (Test-Path $candidate) { return $candidate }

    return $null
}

if ($Uninstall) {
    Write-DevSetupStatus warn "GPG" "GPG is bundled with PortableGit; uninstall is not supported separately"
    return
}

$git = if (Test-Path $portableGit) {
    $portableGit
} else {
    Get-Command git.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
}
if (-not $git) { throw "Git was not found, so the global gpg.program setting cannot be updated." }

$gpg = if (Test-Path $portableGpg) {
    $portableGpg
} elseif (Get-BundledGitGpg $git) {
    Get-BundledGitGpg $git
} else {
    Get-Command gpg.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
}

if (-not $gpg) {
    $message = "GPG was not found. Enable user.install.git so setup can install PortableGit, which includes GPG without administrator rights."
    if ($Audit) {
        Write-DevSetupStatus warn "GPG" $message
        return
    }
    throw $message
}

$configuredGpg = & $git config --global --get gpg.program 2>$null

if ($Audit) {
    Write-DevSetupStatus found "GPG" "$(& $gpg --version | Select-Object -First 1) at $gpg"
    if ($configuredGpg -ne $gpg) {
        Write-DevSetupStatus install "GPG cfg" "would set global gpg.program to $gpg"
    } else {
        Write-DevSetupStatus found "GPG cfg" "global gpg.program already points to $gpg"
    }
    return
}

$gpgDirectory = Split-Path -Parent $gpg
$env:Path = "$gpgDirectory;$env:Path"
Add-DevSetupUserPath $gpgDirectory -Prepend

if ($configuredGpg -ne $gpg) {
    & $git config --global gpg.program $gpg
    Write-DevSetupStatus install "GPG cfg" "set global gpg.program to $gpg"
} else {
    Write-DevSetupStatus found "GPG cfg" "global gpg.program already points to $gpg"
}

Write-DevSetupStatus found "GPG" "$(& $gpg --version | Select-Object -First 1) at $gpg"
