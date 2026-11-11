<# Ensures BusyBox for Windows is available as a user-local multi-call binary. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.busybox.wingetPackageId" "frippery.busybox-w32"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "BusyBox" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    Find-DevSetupWingetExecutable $config "busybox.exe" "advanced.busybox.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Links\busybox.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\busybox*.exe"
    )
}

$busybox = Install-DevSetupWingetTool -Component "BusyBox" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install BusyBox for Windows from https://frippery.org/busybox/." -VersionArgs @("--help")

if ($Audit) { return }

$busyboxDirectory = Split-Path -Parent $busybox
$env:Path = "$busyboxDirectory;$env:Path"
Add-DevSetupUserPath $busyboxDirectory -Prepend
