<# Ensures ShellCheck is available for local Bash linting. #>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.shellcheck.wingetPackageId" "koalaman.shellcheck"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "ShellCheck" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    Find-DevSetupWingetExecutable $config "shellcheck.exe" "advanced.shellcheck.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\shellcheck.exe"
    )
}

$shellCheck = Install-DevSetupWingetTool -Component "ShellCheck" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -ManualInstallHint "Install it from https://www.shellcheck.net/."

if ($Audit) { return }

# Unlike PHP/PowerShell, ShellCheck needs to be usable in *this* session immediately,
# since local Bash lint checks may run right after setup.
$shellCheckDirectory = Split-Path -Parent $shellCheck
$env:Path = "$shellCheckDirectory;$env:Path"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$shellCheckDirectory*") {
    [Environment]::SetEnvironmentVariable("Path", "$shellCheckDirectory;$userPath", "User")
}
