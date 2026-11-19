<#
.SYNOPSIS
    Ensures Microsoft Azure CLI is available per user.
.DESCRIPTION
    Uses user-scoped WinGet. Azure CLI remains a standard Microsoft client;
    it is not used to create app registrations or store kit credentials.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.azureCli.wingetPackageId" "Microsoft.AzureCLI"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "Azure CLI" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    $exe = Find-DevSetupWingetExecutable $config "az.exe" "advanced.azureCli.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Links\az.exe",
        "%ProgramFiles%\Microsoft SDKs\Azure\CLI2\wbin\az.exe",
        "%ProgramFiles(x86)%\Microsoft SDKs\Azure\CLI2\wbin\az.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\wbin\az.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\*\wbin\az.exe"
    )
    if ($exe) { return $exe }
}

$az = Install-DevSetupWingetTool -Component "Azure CLI" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install Azure CLI from https://learn.microsoft.com/cli/azure/install-azure-cli." |
    Select-Object -Last 1

if (-not $az) { return }
$azDirectory = Split-Path -Parent $az
Add-DevSetupUserPath $azDirectory -Prepend -Audit:$Audit
if ($Audit) { return $az }
$env:Path = "$azDirectory;$env:Path"
return $az
