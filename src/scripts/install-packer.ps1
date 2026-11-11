<# Ensures HashiCorp Packer is available for building VM images and OVA templates. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.packer.wingetPackageId" "Hashicorp.Packer"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "Packer" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    Find-DevSetupWingetExecutable $config "packer.exe" "advanced.packer.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Links\packer.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\packer.exe"
    )
}

$packer = Install-DevSetupWingetTool -Component "Packer" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install it from https://developer.hashicorp.com/packer/install."

if ($Audit) { return }

$packerDirectory = Split-Path -Parent $packer
$env:Path = "$packerDirectory;$env:Path"
Add-DevSetupUserPath $packerDirectory -Prepend
