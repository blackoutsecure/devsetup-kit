<# Ensures ripgrep is available for fast recursive text search. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.ripgrep.wingetPackageId" "BurntSushi.ripgrep.MSVC"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "ripgrep" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    Find-DevSetupWingetExecutable $config "rg.exe" "advanced.ripgrep.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\rg.exe"
    )
}

$ripgrep = Install-DevSetupWingetTool -Component "ripgrep" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install it from https://github.com/BurntSushi/ripgrep#installation."

if ($Audit) { return }

$ripgrepDirectory = Split-Path -Parent $ripgrep
$env:Path = "$ripgrepDirectory;$env:Path"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$ripgrepDirectory*") {
    [Environment]::SetEnvironmentVariable("Path", "$ripgrepDirectory;$userPath", "User")
}
