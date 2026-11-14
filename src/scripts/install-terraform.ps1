<# Ensures HashiCorp Terraform is available. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.terraform.wingetPackageId" "Hashicorp.Terraform"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "Terraform" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    Find-DevSetupWingetExecutable $config "terraform.exe" "advanced.terraform.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Links\terraform.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\terraform.exe"
    )
}

$terraform = Install-DevSetupWingetTool -Component "Terraform" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install it from https://developer.hashicorp.com/terraform/install."

if ($Audit) { return }

$terraformDirectory = Split-Path -Parent $terraform
$env:Path = "$terraformDirectory;$env:Path"
Add-DevSetupUserPath $terraformDirectory -Prepend
