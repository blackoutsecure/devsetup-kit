<#
.SYNOPSIS
    Installs the Dioxus CLI (dx) through Cargo in the current user's Cargo home.
.DESCRIPTION
    Uses stable Rust without changing defaults or repository pins. Audit and
    upgrade checks do not install. Uninstall preserves shared Cargo packages.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$package = Get-DevSetupValue $config "advanced.dioxus.cargoPackage" "dioxus-cli"
if ($package -cnotmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]*$') { throw "Invalid Dioxus Cargo package name: $package" }
$cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
$cargoBin = Join-Path $cargoHome "bin"
if ($Uninstall) {
    Write-DevSetupStatus skip "Dioxus CLI" "Cargo packages are preserved; remove manually with cargo uninstall $package --root `"$cargoHome`" if intended"
    return
}

$cargo = Find-DevSetupRustExecutable "cargo"
$dx = Find-DevSetupRustExecutable "dx"
if (-not $dx) {
    if ($Audit) {
        if ($cargo -or (Get-DevSetupValue $config "user.install.rust" $true)) {
            Write-DevSetupStatus install "Dioxus CLI" "would install $package with cargo install --locked --bin dx --root `"$cargoHome`" after stable Rust/Cargo are available"
            Add-DevSetupUserPath $cargoBin -Audit
        } else {
            Write-DevSetupStatus warn "Dioxus CLI" "missing and Cargo is unavailable; enable user.install.rust or install stable Rust/Cargo first"
        }
        return
    }
    if (-not $cargo) { throw "Dioxus CLI requires stable Rust and Cargo. Run the Rust setup step first." }
    Write-DevSetupStatus install "Dioxus CLI" "installing $package through Cargo (user root: $cargoHome; source compilation may take several minutes)"
    $previousPath = $env:Path
    $previousToolchain = $env:RUSTUP_TOOLCHAIN
    $previousAutoInstall = $env:RUSTUP_AUTO_INSTALL
    try {
        $env:Path = "$(Split-Path -Parent $cargo);$cargoBin;$previousPath"
        $env:RUSTUP_TOOLCHAIN = "stable"
        $env:RUSTUP_AUTO_INSTALL = "0"
        & $cargo install --locked --bin dx --root $cargoHome $package | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Cargo failed to install $package (exit $LASTEXITCODE)" }
    } finally {
        $env:Path = $previousPath
        $env:RUSTUP_TOOLCHAIN = $previousToolchain
        $env:RUSTUP_AUTO_INSTALL = $previousAutoInstall
    }
    $dx = Join-Path $cargoBin "dx.exe"
    if (-not (Test-Path -LiteralPath $dx -PathType Leaf)) {
        throw "Dioxus installation reported success but dx was not found at $dx."
    }
}

$version = (& $dx --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "dx --version failed (exit $LASTEXITCODE)" }
if ($version -notmatch '([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?)') {
    throw "Could not determine Dioxus CLI version from: $version"
}
$installed = $Matches[1]
Write-DevSetupStatus found "Dioxus CLI" "$version at $dx"
if ($dx -eq (Join-Path $cargoBin "dx.exe")) { Add-DevSetupUserPath $cargoBin -Audit:$Audit }
if ($CheckUpgrades) {
    $api = Get-DevSetupValue $config "advanced.dioxus.cratesApiBaseUrl" "https://crates.io/api/v1/crates"
    $metadata = Invoke-RestMethod -Uri "$api/$package" -TimeoutSec 30
    $latest = $metadata.crate.max_stable_version
    if ($latest -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw "Invalid latest stable Dioxus version: $latest" }
    $installedBase = [version](($installed -split '-', 2)[0])
    if ([version]$latest -gt $installedBase -or ([version]$latest -eq $installedBase -and $installed.Contains("-"))) {
        Write-DevSetupStatus update "Dioxus CLI" "installed $installed, latest stable $latest (run: cargo install $package --locked --root `"$cargoHome`")"
    } else {
        Write-DevSetupStatus found "Dioxus CLI" "installed $installed; latest stable $latest (no automatic upgrade)"
    }
}
