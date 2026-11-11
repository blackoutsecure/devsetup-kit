<#
.SYNOPSIS
    Detects PowerShell 7 and optionally upgrades to the latest stable release.
.DESCRIPTION
    Upgrades use checksum-verified, versioned user-local ZIPs without replacing
    system installations or stopping existing PowerShell sessions.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades, [switch]$Upgrade)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$packageId = Get-DevSetupValue $config "advanced.powershell.wingetPackageId" "Microsoft.PowerShell"
$portableRoot = Expand-DevSetupPath (Get-DevSetupValue $config "advanced.powershell.portableInstallDir" "%LOCALAPPDATA%\Programs\PowerShell")

if ($Uninstall -and $Upgrade) {
    throw "-Uninstall and -Upgrade cannot be combined."
}

if ($Uninstall) {
    Uninstall-DevSetupWingetTool -Component "PowerShell" -PackageId $packageId -Audit:$Audit
    return
}

function Get-DevSetupPowerShellVersion {
    param([Parameter(Mandatory)][string]$Path)

    $output = (& $Path --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $output -notmatch '^PowerShell (?<full>(?<base>\d+\.\d+\.\d+)(?<preview>-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$') {
        throw "Cannot detect the PowerShell version at $Path. Output: $output"
    }
    [pscustomobject]@{
        Path = $Path
        Version = [version]$Matches.base
        DisplayVersion = $Matches.full
        Prerelease = [bool]$Matches.preview
    }
}

function Get-DevSetupPowerShellInstallation {
    $candidates = @(
        Get-Command pwsh.exe -All -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
        Join-Path $portableRoot "pwsh.exe"
        if (Test-Path -LiteralPath $portableRoot) {
            Get-ChildItem -LiteralPath $portableRoot -Directory |
                Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' } |
                ForEach-Object { Join-Path $_.FullName "pwsh.exe" }
        }
    )
    $installations = foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            Get-DevSetupPowerShellVersion -Path $candidate
        }
    }
    $installations | Sort-Object -Property @{Expression = { $_.Version }; Descending = $true},
        @{Expression = { -not $_.Prerelease }; Descending = $true} | Select-Object -First 1
}

$installation = Get-DevSetupPowerShellInstallation
$release = $null
$latest = $null
if ($CheckUpgrades -or $Upgrade) {
    $releaseApi = Get-DevSetupValue $config "advanced.powershell.portableReleaseApiUrl" "https://api.github.com/repos/PowerShell/PowerShell/releases/latest"
    try {
        $release = Invoke-RestMethod -Uri $releaseApi -TimeoutSec 30
        if ($release.draft -or $release.prerelease -or $release.tag_name -notmatch '^v?(\d+\.\d+\.\d+)$') {
            throw "The release endpoint did not return a stable PowerShell version."
        }
        $latest = [version]$Matches[1]
    } catch {
        Write-DevSetupStatus warn "PowerShell" "latest stable version could not be detected: $($_.Exception.Message)"
        if ($Upgrade) { throw }
    }
}

if ($Upgrade -and $latest -and (-not $installation -or $installation.Version -lt $latest -or ($installation.Version -eq $latest -and $installation.Prerelease))) {
    $previous = if ($installation) { $installation.DisplayVersion } else { "not installed" }
    $destination = Join-Path $portableRoot $latest.ToString()
    if ($Audit) {
        Write-DevSetupStatus update "PowerShell" "installed $previous; latest stable $latest"
        Write-DevSetupStatus install "PowerShell" "would install stable $latest side-by-side in $destination; existing installations and sessions are preserved"
    } else {
        Write-DevSetupStatus install "PowerShell" "upgrading from $previous to latest stable $latest"
        $exe = Install-DevSetupPortableRuntime -Config $config -Tool powershell -InstallDirectory $destination -ReleaseMetadata $release
        $installation = Get-DevSetupPowerShellVersion -Path $exe
        if ($installation.Version -ne $latest -or $installation.Prerelease) {
            throw "PowerShell upgrade verification failed: expected stable $latest, found $($installation.DisplayVersion)."
        }
        Write-DevSetupStatus install "PowerShell" "upgraded to $($installation.DisplayVersion); existing installations and sessions were preserved"
    }
} elseif (-not $installation) {
    $exe = Install-DevSetupWingetTool -Component "PowerShell" -PackageId $packageId -Find { (Get-DevSetupPowerShellInstallation).Path } -Audit:$Audit `
        -FallbackInstall { Install-DevSetupPortableRuntime -Config $config -Tool powershell } `
        -ManualInstallHint "Install it from https://learn.microsoft.com/powershell/."
    if ($exe) { $installation = Get-DevSetupPowerShellVersion -Path $exe }
}

if ($installation) {
    Write-DevSetupStatus found "PowerShell" "installed $($installation.DisplayVersion) at $($installation.Path)"
    if ($latest) {
        if ($installation.Version -lt $latest -or ($installation.Version -eq $latest -and $installation.Prerelease)) {
            if (-not $Upgrade) {
                Write-DevSetupStatus update "PowerShell" "installed $($installation.DisplayVersion); latest stable $latest (run: .\setup.ps1 -UpgradePowerShell)"
            }
        } else {
            Write-DevSetupStatus found "PowerShell" "latest stable $latest; no upgrade needed (installed $($installation.DisplayVersion)); no downgrade performed"
        }
    }
    if (-not $Audit) {
        $env:Path = "$(Split-Path -Parent $installation.Path);$env:Path"
    }
    return $installation.Path
} elseif ($latest) {
    Write-DevSetupStatus found "PowerShell release" "latest stable $latest; PowerShell 7 is not installed"
}
