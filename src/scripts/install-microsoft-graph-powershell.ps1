<#
.SYNOPSIS
    Ensures the Microsoft Graph PowerShell Authentication module is installed per user.
.DESCRIPTION
    Installs Microsoft.Graph.Authentication from PSGallery at CurrentUser scope.
    No app registration, certificate, secret, tenant, or Graph sign-in is created.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$moduleName = Get-DevSetupValue $config "advanced.microsoftGraphPowershell.moduleName" "Microsoft.Graph.Authentication"
$repository = Get-DevSetupValue $config "advanced.microsoftGraphPowershell.repository" "PSGallery"
$minimumVersion = [version](Get-DevSetupValue $config "advanced.microsoftGraphPowershell.minimumModuleVersion" "2.0.0")

$pwsh = Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $pwsh) {
    Write-DevSetupStatus skip "Microsoft Graph PowerShell" "PowerShell 7 is unavailable"
    return
}

$markerDirectory = Join-Path $env:LOCALAPPDATA "DevSetupKit"
$marker = Join-Path $markerDirectory "microsoft-graph-powershell.marker"

$script = @'
$ErrorActionPreference = 'Stop'
$module = Get-Module -ListAvailable -Name $args[0] -ErrorAction SilentlyContinue |
    Sort-Object Version -Descending |
    Select-Object -First 1
if ($null -ne $module) { $module.Version.ToString() }
'@
$installedText = & $pwsh -NoProfile -NoLogo -NonInteractive -Command $script $moduleName
$installed = if ($LASTEXITCODE -eq 0 -and $installedText) { [version]($installedText | Select-Object -First 1) } else { $null }

if ($Uninstall) {
    if ($Audit) {
        if (Test-Path $marker) {
            Write-DevSetupStatus remove "Microsoft Graph PowerShell" "would uninstall $moduleName at CurrentUser scope"
        } else {
            Write-DevSetupStatus skip "Microsoft Graph PowerShell" "module was not installed by devsetup-kit; existing module is preserved"
        }
        return
    }
    if (Test-Path $marker) {
        & $pwsh -NoProfile -NoLogo -NonInteractive -Command `
            '$ErrorActionPreference = "Stop"; Uninstall-Module -Name $args[0] -AllVersions -Scope CurrentUser -Force -ErrorAction Stop' $moduleName
        if ($LASTEXITCODE -ne 0) { throw "Microsoft Graph PowerShell module removal failed (exit $LASTEXITCODE)" }
        Remove-Item $marker -ErrorAction Stop
        Write-DevSetupStatus remove "Microsoft Graph PowerShell" "uninstalled $moduleName at CurrentUser scope"
    } else {
        Write-DevSetupStatus skip "Microsoft Graph PowerShell" "module was not installed by devsetup-kit; existing module is preserved"
    }
    return
}

if (-not $installed -or $installed -lt $minimumVersion) {
    if ($Audit) {
        Write-DevSetupStatus install "Microsoft Graph PowerShell" "would install $moduleName >= $minimumVersion from $repository at CurrentUser scope"
    } else {
        Write-DevSetupStatus install "Microsoft Graph PowerShell" "installing $moduleName >= $minimumVersion from $repository at CurrentUser scope"
        New-Item -Path $markerDirectory -ItemType Directory -Force | Out-Null
        & $pwsh -NoProfile -NoLogo -NonInteractive -Command `
            '$ErrorActionPreference = "Stop"; Install-Module -Name $args[1] -Repository $args[0] -MinimumVersion $args[2] -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop' `
            $repository $moduleName $minimumVersion.ToString()
        if ($LASTEXITCODE -ne 0) { throw "Microsoft Graph PowerShell module installation failed (exit $LASTEXITCODE)" }
        Set-Content -Path $marker -Value "module=$moduleName`nminimum=$minimumVersion"
        $installed = [version](& $pwsh -NoProfile -NoLogo -NonInteractive -Command `
            '$module = Get-Module -ListAvailable -Name $args[0] -ErrorAction SilentlyContinue | Sort-Object Version -Descending | Select-Object -First 1; if ($null -ne $module) { $module.Version.ToString() }' $moduleName)
    }
} else {
    Write-DevSetupStatus found "Microsoft Graph PowerShell" "module $moduleName $installed is available"
}

if ($CheckUpgrades -and $installed) {
    $latestText = & $pwsh -NoProfile -NoLogo -NonInteractive -Command `
        '$ErrorActionPreference = "Stop"; (Find-Module -Name $args[0] -Repository $args[1] -ErrorAction Stop).Version.ToString()' $moduleName $repository
    if ($LASTEXITCODE -eq 0 -and $latestText) {
        $latest = [version]($latestText | Select-Object -First 1)
        if ($latest -gt $installed) {
            Write-DevSetupStatus update "Microsoft Graph PowerShell" "installed $installed; latest $latest (run: Update-Module $moduleName -Scope CurrentUser)"
        }
    }
}
