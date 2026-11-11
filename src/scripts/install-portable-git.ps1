<#
.SYNOPSIS
    Installs a portable Git for Windows build with no admin rights required.
.DESCRIPTION
    Downloads the latest PortableGit release from git-for-windows/git, extracts it
    to the configured install directory, adds it to the user-level PATH, and
    (optionally) points VS Code's "git.path" setting at it.

    Install directory, release URL, asset pattern, credential-helper values, and
    git identity all come from config/dev-setup.config.json.
#>
param(
    [string]$InstallDir,
    [switch]$ConfigureVSCode,
    [switch]$ForcePortable,
    [switch]$PrintPath,
    [switch]$Audit,
    [switch]$Uninstall,
    [switch]$CheckUpgrades
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig

if ($Uninstall) {
    # PortableGit uninstall would also need to unwind global credential/identity config
    # this script wrote, which isn't safe to automate. Leave Git out of -Uninstall.
    Write-DevSetupStatus warn "Git" "uninstall is not supported; remove the PortableGit folder manually if needed"
    return
}

if (-not $InstallDir) {
    $InstallDir = Expand-DevSetupPath (Get-DevSetupValue $config "user.git.installDir" (
        Get-DevSetupValue $config "advanced.git.defaultInstallDir" "$env:USERPROFILE\PortableGit"))
}
if (-not $ForcePortable) {
    $ForcePortable = [bool](Get-DevSetupValue $config "user.git.forcePortable" $false)
}

$releaseApiUrl = Get-DevSetupValue $config "advanced.git.portableReleaseApiUrl" "https://api.github.com/repos/git-for-windows/git/releases/latest"
$assetPattern = Get-DevSetupValue $config "advanced.git.portableAssetPattern" "PortableGit-*64-bit.7z.exe"

$portableGitExe = Join-Path $InstallDir "cmd\git.exe"
$pathGit = Get-Command git.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($pathGit) {
    $gitExe = $pathGit.Source
} else {
    $gitExe = $portableGitExe
}

$needsInstall = (-not (Test-Path $portableGitExe)) -and ($ForcePortable -or -not $pathGit)

if ($CheckUpgrades -and -not $pathGit -and (Test-Path $portableGitExe)) {
    # Only PortableGit is managed by this script; a system git on PATH is left alone.
    try {
        $latestRelease = Invoke-RestMethod -Uri $releaseApiUrl -Headers @{ "User-Agent" = "portable-git-setup" }
        $latestVersion = ($latestRelease.tag_name -replace '^v', '') -replace '\.windows.*', ''
        $installedVersion = ((& $portableGitExe --version) -replace 'git version ', '').Trim()
        if ($latestVersion -and $installedVersion -and ($installedVersion -ne $latestVersion)) {
            Write-DevSetupStatus update "Git" "newer PortableGit available: $latestVersion (installed $installedVersion)"
        }
    } catch {
        Write-DevSetupStatus warn "Git" "could not check for a newer PortableGit release: $($_.Exception.Message)"
    }
}

if ($Audit) {
    if ($pathGit -and -not $ForcePortable) {
        Write-DevSetupStatus found "Git" "$(& $gitExe --version) at $gitExe"
    } elseif (Test-Path $portableGitExe) {
        Write-DevSetupStatus found "Git" "PortableGit already at $portableGitExe"
    } else {
        $reason = if ($ForcePortable) { "user.git.forcePortable is true" } else { "git not found on PATH" }
        Write-DevSetupStatus install "Git" "would install PortableGit to $InstallDir ($reason)"
    }

    if (Test-Path $gitExe) {
        $pending = @(Get-DevSetupGitCredentialSetting $config |
            Where-Object { (& $gitExe config --global --get $_.Key 2>$null) -ne $_.Value } |
            ForEach-Object { $_.Key })
        if ($pending.Count) {
            Write-DevSetupStatus install "git cfg" "would set $($pending -join ', ')"
        } else {
            Write-DevSetupStatus found "git cfg" "credential settings already correct"
        }

        Write-DevSetupGitIdentityStatus $config $gitExe -Audit
    }
    if ($PrintPath -and (Test-Path $gitExe)) { $gitExe }
    return
}

if ($needsInstall) {
    Write-DevSetupStatus install "Git" "installing PortableGit to $InstallDir"
    $release = Invoke-RestMethod -Uri $releaseApiUrl -Headers @{ "User-Agent" = "portable-git-setup" }
    $asset = $release.assets | Where-Object { $_.name -like $assetPattern } | Select-Object -First 1
    if (-not $asset) {
        throw "Could not find an asset matching '$assetPattern' in the latest release."
    }

    $installerPath = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installerPath -UseBasicParsing
    Start-Process -FilePath $installerPath -ArgumentList "-y", "-o`"$InstallDir`"" -Wait -NoNewWindow
    if ($ForcePortable -or -not $pathGit) { $gitExe = $portableGitExe }
} else {
    Write-DevSetupStatus found "Git" "$(& $gitExe --version) at $gitExe"
}

if (-not (Test-Path $gitExe)) {
    throw "PortableGit setup failed: $gitExe not found."
}

$credentialSettings = Get-DevSetupGitCredentialSetting $config

if ($gitExe.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase)) {
    & $gitExe config --system --unset-all credential.helper 2> $null
}

$credentialChanges = 0
foreach ($setting in $credentialSettings) {
    if ((& $gitExe config --global --get $setting.Key) -eq $setting.Value) { continue }
    if ($setting.ReplaceAll) { & $gitExe config --global --replace-all $setting.Key $setting.Value }
    else { & $gitExe config --global $setting.Key $setting.Value }
    $credentialChanges++
}
if ($credentialChanges -gt 0) {
    Write-DevSetupStatus install "git cfg" "$credentialChanges credential value(s) changed"
} else {
    Write-DevSetupStatus found "git cfg" "credential settings already correct"
}

$userName = Get-DevSetupValue $config "user.git.userName"
$userEmail = Get-DevSetupValue $config "user.git.userEmail"
if ($userName) { & $gitExe config --global user.name $userName }
if ($userEmail) { & $gitExe config --global user.email $userEmail }
Write-DevSetupGitIdentityStatus $config $gitExe

Add-DevSetupUserPath (Join-Path $InstallDir "cmd")

if ($ConfigureVSCode) {
    Set-DevSetupVSCodeSetting $config (Get-DevSetupValue $config "advanced.vscode.managedSettingKeys.gitPath" "git.path") $gitExe
}

if ($PrintPath) { $gitExe }
