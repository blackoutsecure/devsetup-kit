<#
.SYNOPSIS
    Ensures Python is available without admin rights or GUI installers.
.DESCRIPTION
    Version, winget package ID, install root, and uv download URL come from
    config/dev-setup.config.json. Emits the resolved interpreter path as the final
    pipeline value so callers can reuse it.
#>
param(
    [string]$PythonVersion,
    [switch]$ConfigureVSCode,
    [switch]$Audit,
    [switch]$Uninstall,
    [switch]$CheckUpgrades
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig

if (-not $PythonVersion) {
    $PythonVersion = Get-DevSetupValue $config "user.python.version" "3.14"
}
$versionGlob = "Python$($PythonVersion -replace '\.', '')*"
$installRoot = Expand-DevSetupPath (Get-DevSetupValue $config "advanced.python.windowsInstallRoot" "$env:LOCALAPPDATA\Programs\Python")
$wingetPackageId = (Get-DevSetupValue $config "advanced.python.wingetPackageId" "Python.Python.{version}") -replace '\{version\}', $PythonVersion

if ($Uninstall) {
    # Match the same detection order the installer uses, so uninstall targets
    # whichever mechanism actually put this version's CPython in place. The
    # configured install root is just a search-path hint (winget doesn't always
    # honor --scope user for every package), so ask winget directly instead.
    $wingetManaged = $false
    if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        $listOutput = & winget.exe list --id $wingetPackageId -e --accept-source-agreements 2>$null
        if ($LASTEXITCODE -eq 0 -and ($listOutput | Select-String -SimpleMatch $wingetPackageId)) {
            $wingetManaged = $true
        }
    }
    if ($wingetManaged) {
        Uninstall-DevSetupWingetTool -Component "Python" -PackageId $wingetPackageId -Audit:$Audit
        return
    }

    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    $uvManagedPath = if ($uvCommand) { (& $uvCommand.Source python find $PythonVersion 2>$null) } else { $null }
    # `uv python find` also resolves system interpreters it didn't install, so only
    # treat this as uv-managed when the resolved path actually lives under uv's own
    # data directory (e.g. ...\AppData\Roaming\uv\python\...).
    if ($uvManagedPath -and ($uvManagedPath -match '\\uv\\')) {
        if ($Audit) {
            Write-DevSetupStatus remove "Python" "would uninstall CPython $PythonVersion via uv"
        } else {
            & $uvCommand.Source python uninstall $PythonVersion
            Write-DevSetupStatus remove "Python" "uninstalled CPython $PythonVersion via uv"
        }
    } else {
        Write-DevSetupStatus warn "Python" "no uv- or winget-managed CPython $PythonVersion found to uninstall (a system Python, if any, is left alone)"
    }
    return
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$pythonExe = $null
if ($pythonCommand -and $pythonCommand.Source -notlike "*\Microsoft\WindowsApps\*") {
    $pythonExe = $pythonCommand.Source
}

if (-not $pythonExe) {
    $existingPython = Get-ChildItem (Join-Path $installRoot $versionGlob) -Recurse -Filter python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existingPython) {
        $pythonExe = $existingPython.FullName
    }
}

if ($Audit) {
    if ($pythonExe) {
        Write-DevSetupStatus found "Python" "$(& $pythonExe --version) at $pythonExe"
        if ($CheckUpgrades) { Test-DevSetupWingetUpgrade -Component "Python" -PackageId $wingetPackageId }
    } elseif (Get-Command winget.exe -ErrorAction SilentlyContinue) {
        Write-DevSetupStatus install "Python" "would install $wingetPackageId via winget"
    } else {
        Write-DevSetupStatus install "Python" "would bootstrap uv, then install CPython $PythonVersion"
    }
    return
}

if (-not $pythonExe) {
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($wingetCommand) {
        Write-DevSetupStatus install "Python" "installing $wingetPackageId via winget (per-user, no admin, no GUI)"
        & winget.exe install --id $wingetPackageId -e --scope user --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
        if ($LASTEXITCODE -eq 0) {
            $installed = Get-ChildItem (Join-Path $installRoot $versionGlob) -Recurse -Filter python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($installed) {
                $pythonExe = $installed.FullName
            }
        } else {
            Write-DevSetupStatus warn "Python" "winget could not install $wingetPackageId for the current user; falling back to user-local uv"
        }
    }
}

# Fall back to uv only when winget is unavailable or failed. Note: on machines with
# Defender Application Control / Exploit Guard ASR policies (common on managed corporate
# devices), executing a freshly downloaded uv.exe may be blocked by IT policy even though
# the download itself succeeds. winget-installed packages go through a trusted pipeline and
# are not subject to that block, so winget is preferred whenever it's available.
if (-not $pythonExe) {
    $uvPath = Expand-DevSetupPath (Get-DevSetupValue $config "advanced.python.uvWindowsPath" "$env:USERPROFILE\.local\bin\uv.exe")
    $uvInstallUrl = Get-DevSetupValue $config "advanced.python.uvInstallUrl.windows" "https://astral.sh/uv/install.ps1"
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    if (-not $uvCommand -and (Test-Path $uvPath)) {
        $uvCommand = $uvPath
    }

    if (-not $uvCommand) {
        Write-DevSetupStatus install "uv" "installing to $uvPath (user-local, no admin, no GUI)"
        Invoke-Expression (Invoke-RestMethod -Uri $uvInstallUrl)
        if (Test-Path $uvPath) {
            $uvCommand = $uvPath
        }
    }

    if (-not $uvCommand) {
        throw "Python is unavailable and neither winget nor uv could install it automatically. Install uv from https://docs.astral.sh/uv/ or provide uv.exe/winget in PATH. No GUI installer was launched."
    }

    $uvExe = if ($uvCommand -is [string]) { $uvCommand } else { $uvCommand.Source }
    & $uvExe python install $PythonVersion
    $pythonExe = (& $uvExe python find $PythonVersion).Trim()
}

if (-not (Test-Path $pythonExe)) {
    throw "Python setup failed: $pythonExe not found."
}

$pythonDirectory = Split-Path -Parent $pythonExe
Add-DevSetupUserPath $pythonDirectory -Prepend

if ($ConfigureVSCode) {
    Set-DevSetupVSCodeSetting $config (Get-DevSetupValue $config "advanced.vscode.managedSettingKeys.pythonInterpreter" "python.defaultInterpreterPath") $pythonExe
}

Write-DevSetupStatus found "Python" "$(& $pythonExe --version) at $pythonExe"
if ($CheckUpgrades) { Test-DevSetupWingetUpgrade -Component "Python" -PackageId $wingetPackageId }
$pythonExe
