<# Ensures PHP is available for VS Code's built-in PHP validator. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.php.wingetPackageId" "PHP.PHP.8.5"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "PHP" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    Find-DevSetupWingetExecutable $config "php.exe" "advanced.php.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\php.exe"
    )
}

Install-DevSetupWingetTool -Component "PHP" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install PHP from https://www.php.net/downloads.php."
