<#
.SYNOPSIS
    Sets up Git, Node.js, Python, and VS Code settings without admin rights or GUI installers.
.DESCRIPTION
    Bootstraps user-local PortableGit when needed (which also configures the
    credential helper), installs Node.js and Python, and applies VS Code
    settings last. Python setup runs natively in PowerShell rather than through
    Git Bash, since PortableGit's minimal Bash/coreutils are not a reliable
    environment for running installer scripts.

    Every tunable lives in config/dev-setup.config.json. Parameters here override
    it for a single run. The final step runs src/configure-vscode.py, which stores
    the syncable VS Code settings including Dev Containers defaults. Dev containers
    stay opt-in; nothing is containerized by this script.
#>
param(
    [string]$GitInstallDir,
    [string]$PythonVersion,
    [switch]$SkipVSCodeSettings,
    [switch]$SkipSettingsSync,
    [switch]$SkipUpgradeCheck,
    [switch]$CheckUpgradesOnly,
    [switch]$UpgradePowerShell,
    [switch]$UpgradeRust,
    [switch]$Uninstall,
    [switch]$Audit
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "src\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:($Audit -or ($CheckUpgradesOnly -and -not $Uninstall))

if ($Uninstall -and $UpgradePowerShell) {
    throw "-Uninstall and -UpgradePowerShell cannot be combined."
}
if ($Uninstall -and $UpgradeRust) { throw "-Uninstall and -UpgradeRust cannot be combined." }

function Write-DevSetupSection {
    param([Parameter(Mandatory)][string]$Title)

    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
    Write-Host ("  {0}" -f $Title.ToUpperInvariant()) -ForegroundColor Cyan
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
}

function Write-DevSetupHeader {
    param([Parameter(Mandatory)]$Config, [Parameter(Mandatory)][string]$Mode)

    Write-DevSetupSection "Blackout Secure Dev Setup Kit"
    Write-Host "  Author:          Blackout Secure"
    Write-Host "  Standard:        Config-driven developer environment setup"
    Write-Host "  Standard version: 1"
    Write-Host "  Script:           setup.ps1"
    Write-Host "  PowerShell:       $($PSVersionTable.PSVersion)"
    Write-Host "  Run mode:         $Mode"
    Write-Host "  Repository root:  $DevSetupRoot"
    Write-Host "  Configuration:    $DevSetupConfigPath"
    Write-Host "  Python target:    $(Get-DevSetupValue $Config 'user.python.version' '3.14')"
}

function Write-DevSetupConfiguration {
    param(
        [Parameter(Mandatory)]$Config,
        [Parameter(Mandatory)][string]$GitInstallDir,
        [Parameter(Mandatory)][string]$PythonVersion,
        [Parameter(Mandatory)][bool]$ConfigureVSCode,
        [Parameter(Mandatory)][bool]$CheckUpgrades
    )

    Write-DevSetupSection "Configuration"
    Write-Host "  Resolved runtime variables:"
    Write-Host "    GitInstallDir   = $GitInstallDir"
    Write-Host "    PythonVersion   = $PythonVersion"
    Write-Host "    ConfigureVSCode = $ConfigureVSCode"
    Write-Host "    CheckUpgrades   = $CheckUpgrades"
    Write-Host "    UpgradePowerShell = $UpgradePowerShell (explicit opt-in; read-only modes take precedence)"
    Write-Host "    UpgradeRust     = $UpgradeRust (stable only; no rustup self-update)"
    Write-Host "    Audit           = $Audit"
    Write-Host "    Uninstall       = $Uninstall"
    Write-Host "    Config file     = $DevSetupConfigPath"
    Write-Host ""
    Write-Host "  Loaded configuration:"
    $profiles = @(Get-DevSetupValue $Config 'user.vscode.profiles' @('stable', 'insiders'))
    $extensions = @(Get-DevSetupValue $Config 'user.vscode.extensions.install' @())
    $mcpServers = Get-DevSetupValue $Config 'user.mcp.servers' ([pscustomobject]@{})
    $mcpCount = @($mcpServers.PSObject.Properties).Count
    Write-Host "    Install tools:   Git=$((Get-DevSetupValue $Config 'user.install.git' $true)), Node=$((Get-DevSetupValue $Config 'user.install.node' $true)), Prettier=$((Get-DevSetupValue $Config 'user.install.prettier' $true)), Python=$((Get-DevSetupValue $Config 'user.install.python' $true)), PHP=$((Get-DevSetupValue $Config 'user.install.php' $true))"
    Write-Host "                     GitHub CLI=$((Get-DevSetupValue $Config 'user.install.githubCli' $true))"
    $rustEnabled = Get-DevSetupValue $Config "user.install.rust" $true
    $rustComponents = @()
    $rustTargets = @()
    if ($rustEnabled) {
        $rustComponents = @(Get-DevSetupStringList $Config "user.rust.components" @("rustfmt", "clippy", "rust-src"))
        $rustTargets = @(Get-DevSetupStringList $Config "user.rust.targets")
    }
    Write-Host "                     Rust=$rustEnabled (stable; components=$($rustComponents -join ','); targets=$($rustTargets -join ','))"
    Write-Host "                     Dioxus CLI (dx)=$((Get-DevSetupValue $Config 'user.install.dioxus' $true))"
    Write-Host "                     PowerShell=$((Get-DevSetupValue $Config 'user.install.powershell' $true)), ShellCheck=$((Get-DevSetupValue $Config 'user.install.shellcheck' $true)), ripgrep=$((Get-DevSetupValue $Config 'user.install.ripgrep' $true)), BusyBox=$((Get-DevSetupValue $Config 'user.install.busybox' $true)), Packer=$((Get-DevSetupValue $Config 'user.install.packer' $true)), GPG=$((Get-DevSetupValue $Config 'user.install.gpg' $true))"
    Write-Host "    VS Code:         settings=$((Get-DevSetupValue $Config 'user.install.vscodeSettings' $true)), profiles=$($profiles -join ', '), extensions=$($extensions.Count) managed"
    Write-Host "    User Sync:       enabled=$((Get-DevSetupValue $Config 'user.vscode.settingsSync.syncAfterSetup' $true)), provider=$((Get-DevSetupValue $Config 'user.vscode.settingsSync.requiredProvider' 'github')), skip=$SkipSettingsSync"
    Write-Host "    MCP servers:     $mcpCount configured"
    Write-Host "    Dev containers:  defaults=$((Get-DevSetupValue $Config 'user.install.devcontainerDefaults' $true)), base=$((Get-DevSetupValue $Config 'user.devcontainers.baseImage' 'not configured'))"
    Write-Host "    Config sections: user, advanced"
}

$configPath = $DevSetupConfigPath
$config = Get-DevSetupConfig $configPath
$scripts = Join-Path $PSScriptRoot "src\scripts"

$statusLog = Join-Path ([System.IO.Path]::GetTempPath()) ("devsetup-status-{0}.log" -f [guid]::NewGuid())
New-Item -Path $statusLog -ItemType File -Force | Out-Null
$env:DEVSETUP_STATUS_LOG = $statusLog

if (-not $GitInstallDir) {
    $GitInstallDir = Expand-DevSetupPath (Get-DevSetupValue $config "user.git.installDir" (
        Get-DevSetupValue $config "advanced.git.defaultInstallDir" "$env:USERPROFILE\PortableGit"))
}
if (-not $PythonVersion) {
    $PythonVersion = Get-DevSetupValue $config "user.python.version" "3.14"
}

$applyCommand = ".\setup.ps1"
if ($Uninstall) { $applyCommand += " -Uninstall" }
if ($PSBoundParameters.ContainsKey("PythonVersion")) {
    $applyCommand += " -PythonVersion '$($PythonVersion.Replace("'", "''"))'"
}
if (-not $Uninstall -and $PSBoundParameters.ContainsKey("GitInstallDir")) {
    $applyCommand += " -GitInstallDir '$($GitInstallDir.Replace("'", "''"))'"
}
if ($SkipVSCodeSettings) { $applyCommand += " -SkipVSCodeSettings" }
if ($SkipSettingsSync) { $applyCommand += " -SkipSettingsSync" }
if ($SkipUpgradeCheck) { $applyCommand += " -SkipUpgradeCheck" }
if (-not $CheckUpgradesOnly) {
    if ($UpgradePowerShell) { $applyCommand += " -UpgradePowerShell" }
    if ($UpgradeRust) { $applyCommand += " -UpgradeRust" }
}

$configureVSCode = (-not $SkipVSCodeSettings) -and (Get-DevSetupValue $config "user.install.vscodeSettings" $true)
$checkUpgrades = $CheckUpgradesOnly -or ((-not $SkipUpgradeCheck) -and (Get-DevSetupValue $config "user.checkUpgrades" $true))
$gitExe = $null
$pythonExe = $null
$phpExe = $null
$powerShellExe = $null
$runMode = if ($Uninstall) { "Uninstall" } elseif ($CheckUpgradesOnly) { "Upgrade check" } elseif ($Audit) { "Audit" } else { "Setup" }

Write-DevSetupHeader -Config $config -Mode $runMode
Write-DevSetupConfiguration -Config $config -GitInstallDir $GitInstallDir -PythonVersion $PythonVersion -ConfigureVSCode $configureVSCode -CheckUpgrades $checkUpgrades
Write-DevSetupSection "Live Activity"

if ($Uninstall) {
    Write-Host "Uninstalling (each step only removes tools this kit manages; Git is never removed):"
    if (Get-DevSetupValue $config "user.install.git" $true) {
        & (Join-Path $scripts "install-portable-git.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.githubCli" $true) {
        & (Join-Path $scripts "install-github-cli.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.prettier" $true) {
        & (Join-Path $scripts "install-prettier.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.node" $true) {
        & (Join-Path $scripts "install-node.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.python" $true) {
        & (Join-Path $scripts "install-python.ps1") -PythonVersion $PythonVersion -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.php" $true) {
        & (Join-Path $scripts "install-php.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.rust" $true) {
        & (Join-Path $scripts "install-rust.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.dioxus" $true) {
        & (Join-Path $scripts "install-dioxus.ps1") -Uninstall -Audit:$Audit
    } else {
        Write-DevSetupStatus skip "Dioxus CLI" "user.install.dioxus is false"
    }
    if (Get-DevSetupValue $config "user.install.powershell" $true) {
        & (Join-Path $scripts "install-powershell.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.shellcheck" $true) {
        & (Join-Path $scripts "install-shellcheck.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.ripgrep" $true) {
        & (Join-Path $scripts "install-ripgrep.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.busybox" $true) {
        & (Join-Path $scripts "install-busybox.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.packer" $true) {
        & (Join-Path $scripts "install-packer.ps1") -Uninstall -Audit:$Audit
    }
    if (Get-DevSetupValue $config "user.install.gpg" $true) {
        & (Join-Path $scripts "install-gpg.ps1") -Uninstall -Audit:$Audit
    }

    Write-Host ""
    if ($Audit) {
        Write-Host "Uninstall audit complete. Nothing was removed. Re-run with -Uninstall (without -Audit) to apply."
    } else {
        Write-Host "Uninstall complete."
    }
    Write-DevSetupSummary -LogPath $statusLog -Audit:$Audit -ApplyCommand $applyCommand
    Remove-Item $statusLog -ErrorAction SilentlyContinue
    Remove-Item Env:\DEVSETUP_STATUS_LOG -ErrorAction SilentlyContinue
    return
}

if ($CheckUpgradesOnly) {
    Write-Host "Checking for upgrades (detect only - nothing will be installed or changed):"
    if (Get-DevSetupValue $config "user.install.git" $true) {
        & (Join-Path $scripts "install-portable-git.ps1") -InstallDir $GitInstallDir -Audit -CheckUpgrades | Out-Null
    }
    if (Get-DevSetupValue $config "user.install.githubCli" $true) {
        & (Join-Path $scripts "install-github-cli.ps1") -Audit -CheckUpgrades | Out-Null
    }
    if (Get-DevSetupValue $config "user.install.node" $true) {
        & (Join-Path $scripts "install-node.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.prettier" $true) {
        & (Join-Path $scripts "install-prettier.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.python" $true) {
        & (Join-Path $scripts "install-python.ps1") -PythonVersion $PythonVersion -Audit -CheckUpgrades | Out-Null
    }
    if (Get-DevSetupValue $config "user.install.php" $true) {
        & (Join-Path $scripts "install-php.ps1") -Audit -CheckUpgrades | Out-Null
    }
    if (Get-DevSetupValue $config "user.install.rust" $true) {
        & (Join-Path $scripts "install-rust.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.dioxus" $true) {
        & (Join-Path $scripts "install-dioxus.ps1") -Audit -CheckUpgrades
    } else {
        Write-DevSetupStatus skip "Dioxus CLI" "user.install.dioxus is false"
    }
    if (Get-DevSetupValue $config "user.install.powershell" $true) {
        & (Join-Path $scripts "install-powershell.ps1") -Audit -CheckUpgrades | Out-Null
    }
    if (Get-DevSetupValue $config "user.install.shellcheck" $true) {
        & (Join-Path $scripts "install-shellcheck.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.ripgrep" $true) {
        & (Join-Path $scripts "install-ripgrep.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.busybox" $true) {
        & (Join-Path $scripts "install-busybox.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.packer" $true) {
        & (Join-Path $scripts "install-packer.ps1") -Audit -CheckUpgrades
    }
    if (Get-DevSetupValue $config "user.install.gpg" $true) {
        & (Join-Path $scripts "install-gpg.ps1") -Audit -CheckUpgrades
    }

    Write-Host ""
    Write-Host "Upgrade check complete. Nothing was installed or changed."
    Write-DevSetupSummary -LogPath $statusLog -Audit -ApplyCommand $applyCommand
    Remove-Item $statusLog -ErrorAction SilentlyContinue
    Remove-Item Env:\DEVSETUP_STATUS_LOG -ErrorAction SilentlyContinue
    return
}

if ($Audit) {
    Write-Host "Auditing (detect only - nothing will be installed or changed):"
} else {
    Write-Host "Running setup (each step is skipped when already satisfied):"
}

Write-DevSetupStatus skip "WSL" "not installed or invoked by setup.ps1 (see setup-wsl.ps1 for existing WSL user setup)"

if (Get-DevSetupValue $config "user.install.git" $true) {
    $gitExe = & (Join-Path $scripts "install-portable-git.ps1") -InstallDir $GitInstallDir -ConfigureVSCode:$configureVSCode -PrintPath:$configureVSCode -Audit:$Audit -CheckUpgrades:$checkUpgrades |
        Select-Object -Last 1
} else {
    Write-DevSetupStatus skip "Git" "user.install.git is false"
}

if (Get-DevSetupValue $config "user.install.githubCli" $true) {
    & (Join-Path $scripts "install-github-cli.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades | Out-Null
} else {
    Write-DevSetupStatus skip "GitHub CLI" "user.install.githubCli is false"
}

if (Get-DevSetupValue $config "user.install.node" $true) {
    & (Join-Path $scripts "install-node.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "Node.js" "user.install.node is false"
}

if (Get-DevSetupValue $config "user.install.prettier" $true) {
    & (Join-Path $scripts "install-prettier.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "Prettier" "user.install.prettier is false"
}

if (Get-DevSetupValue $config "user.install.python" $true) {
    # install-python.ps1 emits the resolved interpreter path as its last output.
    $pythonExe = & (Join-Path $scripts "install-python.ps1") -PythonVersion $PythonVersion -ConfigureVSCode:$configureVSCode -Audit:$Audit -CheckUpgrades:$checkUpgrades |
        Select-Object -Last 1
} else {
    Write-DevSetupStatus skip "Python" "user.install.python is false"
}

if (Get-DevSetupValue $config "user.install.rust" $true) {
    & (Join-Path $scripts "install-rust.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades -Upgrade:$UpgradeRust
} else {
    Write-DevSetupStatus skip "Rust" "user.install.rust is false"
}

if (Get-DevSetupValue $config "user.install.dioxus" $true) {
    & (Join-Path $scripts "install-dioxus.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "Dioxus CLI" "user.install.dioxus is false"
}

if (Get-DevSetupValue $config "user.install.php" $true) {
    $phpExe = & (Join-Path $scripts "install-php.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades | Select-Object -Last 1
} else {
    Write-DevSetupStatus skip "PHP" "user.install.php is false"
}

if (Get-DevSetupValue $config "user.install.powershell" $true) {
    $powerShellExe = & (Join-Path $scripts "install-powershell.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades -Upgrade:$UpgradePowerShell | Select-Object -Last 1
} else {
    Write-DevSetupStatus skip "PowerShell" "user.install.powershell is false"
}

if (Get-DevSetupValue $config "user.install.shellcheck" $true) {
    & (Join-Path $scripts "install-shellcheck.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "ShellCheck" "user.install.shellcheck is false"
}

if (Get-DevSetupValue $config "user.install.ripgrep" $true) {
    & (Join-Path $scripts "install-ripgrep.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "ripgrep" "user.install.ripgrep is false"
}

if (Get-DevSetupValue $config "user.install.busybox" $true) {
    & (Join-Path $scripts "install-busybox.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "BusyBox" "user.install.busybox is false"
}

if (Get-DevSetupValue $config "user.install.packer" $true) {
    & (Join-Path $scripts "install-packer.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
} else {
    Write-DevSetupStatus skip "Packer" "user.install.packer is false"
}

if (Get-DevSetupValue $config "user.install.gpg" $true) {
    try {
        & (Join-Path $scripts "install-gpg.ps1") -Audit:$Audit -CheckUpgrades:$checkUpgrades
    } catch {
        Write-DevSetupStatus warn "GPG" $_.Exception.Message
    }
} else {
    Write-DevSetupStatus skip "GPG" "user.install.gpg is false"
}

if (-not $configureVSCode) {
    $reason = if ($SkipVSCodeSettings) { "-SkipVSCodeSettings was passed" } else { "user.install.vscodeSettings is false" }
    Write-DevSetupStatus skip "vscode" $reason
}

if ($configureVSCode) {
    if (-not ($pythonExe -and (Test-Path $pythonExe))) {
        # install-python.ps1 updates the user-level PATH, which the current session
        # does not inherit, so rebuild $env:Path before looking for the interpreter.
        $env:Path = ((
            [Environment]::GetEnvironmentVariable("Path", "Machine"),
            [Environment]::GetEnvironmentVariable("Path", "User")
        ) | Where-Object { $_ }) -join ";"
        $pythonExe = Get-Command python.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike "*\Microsoft\WindowsApps\*" } |
            Select-Object -First 1 -ExpandProperty Source
    }

    if ($pythonExe) {
        $arguments = @((Join-Path $PSScriptRoot "src\configure-vscode.py"), "--config", $configPath, "--python-path", $pythonExe)
        if ($gitExe -and (Test-Path $gitExe)) { $arguments += @("--git-path", $gitExe) }
        if ($phpExe -and (Test-Path $phpExe)) { $arguments += @("--php-path", $phpExe) }
        if ($powerShellExe -and (Test-Path $powerShellExe)) { $arguments += @("--powershell-path", $powerShellExe) }
        if ($Audit) { $arguments += "--dry-run" }
        if ($SkipSettingsSync) { $arguments += "--skip-settings-sync" }
        & $pythonExe $arguments
        if ($LASTEXITCODE -ne 0) {
            throw "VS Code configuration failed (exit code $LASTEXITCODE). Review the output above before retrying."
        }
    } else {
        Write-DevSetupStatus warn "vscode" "Python not on PATH; run src/configure-vscode.py manually from a new terminal"
    }
}

Write-Host ""
if ($Audit) {
    Write-Host "Audit complete. Nothing was installed or changed. Re-run without -Audit to apply."
} else {
    Write-Host "Setup complete."
    Write-DevSetupStatus skip "restart" "VS Code and terminal sessions remain open. If PATH or extensions need a restart, save your work and reopen VS Code or start a new terminal yourself when ready."
}

Write-DevSetupSummary -LogPath $statusLog -Audit:$Audit -ApplyCommand $applyCommand
Remove-Item $statusLog -ErrorAction SilentlyContinue
Remove-Item Env:\DEVSETUP_STATUS_LOG -ErrorAction SilentlyContinue
