<#
.SYNOPSIS
    Ensures GitHub CLI is available per user for repository and PR automation.
.DESCRIPTION
    Uses user-scoped WinGet with an official SHA256-verified portable ZIP fallback.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.githubCli.wingetPackageId" "GitHub.cli"

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "GitHub CLI" -PackageId $packageId -Audit:$Audit
    return
}

$find = {
    $exe = Find-DevSetupWingetExecutable $config "gh.exe" "advanced.githubCli.windowsSearchPaths" $packageId @(
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\gh.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\bin\gh.exe",
        "%LOCALAPPDATA%\Microsoft\WinGet\Packages\{wingetPackageId}_*\*\bin\gh.exe",
        "%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe",
        "%LOCALAPPDATA%\Programs\GitHub CLI\bin\gh.exe",
        "%ProgramFiles%\GitHub CLI\gh.exe",
        "%ProgramFiles%\GitHub CLI\bin\gh.exe"
    )
    if ($exe) { return $exe }
    $portableDir = Expand-DevSetupPath (Get-DevSetupValue $config "advanced.githubCli.portableInstallDir" "%LOCALAPPDATA%\Programs\GitHub CLI")
    $portableExe = Join-Path $portableDir "bin\gh.exe"
    if (Test-Path $portableExe) { return $portableExe }
}

$gh = Install-DevSetupWingetTool -Component "GitHub CLI" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
    -FallbackInstall { Install-DevSetupPortableRuntime -Config $config -Tool githubCli } `
    -ManualInstallHint "Install GitHub CLI from https://cli.github.com/." |
    Select-Object -Last 1

if (-not $gh) { return }

$ghDirectory = Split-Path -Parent $gh
Add-DevSetupUserPath $ghDirectory -Prepend -Audit:$Audit
if ($Audit) { return $gh }

$env:Path = "$ghDirectory;$env:Path"
return $gh
