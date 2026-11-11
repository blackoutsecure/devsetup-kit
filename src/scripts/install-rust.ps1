<#
.SYNOPSIS
    Ensures rustup, stable Rust, and editor components are available per user.
.DESCRIPTION
    Preserves existing default toolchains. Audit never installs or compiles.
    Uninstall deliberately leaves shared Rust toolchains and Cargo packages alone.
#>
param([switch]$Audit, [switch]$Uninstall, [switch]$CheckUpgrades, [switch]$Upgrade)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig

if ($Uninstall -and $Upgrade) { throw "-Uninstall and -Upgrade cannot be combined." }
if ($Uninstall) {
    Write-DevSetupStatus skip "Rust" "shared rustup toolchains and Cargo packages are preserved; remove manually with rustup self uninstall if intended"
    return
}

$components = @(Get-DevSetupStringList $config "user.rust.components" @("rustfmt", "clippy", "rust-src"))
$targets = @(Get-DevSetupStringList $config "user.rust.targets")
foreach ($name in @($components) + @($targets)) {
    if ($name -cnotmatch '^[a-z][a-z0-9_.-]*$') {
        throw "Invalid Rust component or target name: '$name'. Use names reported by rustup component list or rustup target list."
    }
}
$components = @((@("cargo", "rustc") + $components) | Select-Object -Unique)
$selection = "components [$($components -join ', ')], targets [$($targets -join ', ')]"
$cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
$rustupHome = if ($env:RUSTUP_HOME) { $env:RUSTUP_HOME } else { Join-Path $env:USERPROFILE ".rustup" }
Write-DevSetupStatus found "Rust homes" "Cargo: $cargoHome; rustup: $rustupHome (current-user permissions; no elevation requested)"
$cargoBin = Join-Path $cargoHome "bin"
$packageId = Get-DevSetupValue $config "advanced.rust.wingetPackageId" "Rustlang.Rustup"
$find = {
    Find-DevSetupRustExecutable "rustup"
}
$fallback = {
    $architecture = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $hostTriple = switch ($architecture) {
        "AMD64" { "x86_64-pc-windows-msvc" }
        "ARM64" { "aarch64-pc-windows-msvc" }
        "x86" { "i686-pc-windows-msvc" }
        default { throw "Unsupported Rust bootstrap architecture: $architecture" }
    }
    $baseUrl = Get-DevSetupValue $config "advanced.rust.bootstrapBaseUrl" "https://static.rust-lang.org/rustup/dist"
    $url = "$baseUrl/$hostTriple/rustup-init.exe"
    $stage = Join-Path ([IO.Path]::GetTempPath()) ("devsetup-rustup-{0}" -f [guid]::NewGuid())
    New-Item -Path $stage -ItemType Directory | Out-Null
    try {
        $installer = Join-Path $stage "rustup-init.exe"
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -TimeoutSec 120
        $digest = (Invoke-WebRequest -Uri "$url.sha256" -UseBasicParsing -TimeoutSec 120).Content
        if ($digest -is [byte[]]) { $digest = [Text.Encoding]::UTF8.GetString($digest) }
        if ("$digest" -notmatch '^\s*([a-fA-F0-9]{64})(?:\s|$)') { throw "Invalid official rustup SHA256 response" }
        $expected = $Matches[1]
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expected) { throw "Rustup SHA256 verification failed" }
        Write-DevSetupStatus install "rustup" "running official SHA256-verified user installer; no toolchain or linker default override"
        & $installer -y --no-modify-path --default-toolchain none --profile minimal | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Rustup installer failed (exit $LASTEXITCODE)" }
        & $find
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
$autoInstall = $env:RUSTUP_AUTO_INSTALL
try {
    $env:RUSTUP_AUTO_INSTALL = "0"
    $rustup = Install-DevSetupWingetTool -Component "rustup" -PackageId $packageId -Find $find -Audit:$Audit -CheckUpgrades:$CheckUpgrades `
        -FallbackInstall $fallback `
        -FallbackDescription "the official SHA256-verified user-local rustup installer" `
        -ManualInstallHint "Install rustup per-user from https://rustup.rs/; Windows native compilation also needs a working linker."
} finally {
    $env:RUSTUP_AUTO_INSTALL = $autoInstall
}
if ($Audit) { Add-DevSetupUserPath $cargoBin -Audit }
if (-not $rustup) {
    Write-DevSetupStatus install "Rust" "would provision stable with $selection after rustup installation"
    Write-DevSetupStatus skip "Rust build" "linker readiness is unverified; audit does not compile or run code"
    return
}

function Invoke-Rustup {
    param([string[]]$Arguments)
    $autoInstall = $env:RUSTUP_AUTO_INSTALL
    $previousPath = $env:Path
    try {
        $env:RUSTUP_AUTO_INSTALL = "0"
        $env:Path = "$cargoBin;$(Split-Path -Parent $rustup);$previousPath"
        & $rustup @Arguments
        if ($LASTEXITCODE -ne 0) { throw "rustup $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
    } finally {
        $env:RUSTUP_AUTO_INSTALL = $autoInstall
        $env:Path = $previousPath
    }
}

$defaultHost = @(Invoke-Rustup -Arguments @("show") | ForEach-Object {
    if ($_ -match '^Default host:\s+(\S+)\s*$') { $Matches[1] }
})
if ($defaultHost.Count -ne 1) { throw "Could not resolve rustup's default host" }
$stableToolchain = "stable-$($defaultHost[0])"
$toolchains = @(Invoke-Rustup -Arguments @("toolchain", "list"))
$hasStable = @($toolchains | Where-Object { ($_ -split '\s+', 2)[0] -eq $stableToolchain }).Count -gt 0
if (-not $hasStable) {
    if ($Audit) {
        Write-DevSetupStatus install "Rust stable" "would install stable with $selection; existing defaults remain unchanged"
        Write-DevSetupStatus skip "Rust build" "linker readiness is unverified; audit does not compile or run code"
        return
    }
    Write-DevSetupStatus install "Rust stable" "installing stable with minimal profile"
    Invoke-Rustup -Arguments @("toolchain", "install", $stableToolchain, "--profile", "minimal", "--no-self-update") | Out-Host
}

$upgradeLines = @()
if ($CheckUpgrades -or $Upgrade) {
    $upgradeLines = @(Invoke-Rustup -Arguments @("check"))
    $stablePattern = '^' + [regex]::Escape($stableToolchain) + '\s+-\s+'
    $stableStatus = @($upgradeLines | Where-Object { $_ -match $stablePattern })
    if ($Upgrade -and ($stableStatus.Count -ne 1 -or $stableStatus[0] -notmatch '(update available|up to date)')) {
        throw "Could not determine the latest stable Rust version from rustup check."
    }
    if ($Upgrade -and $stableStatus[0] -match 'update available') {
        if ($Audit) {
            Write-DevSetupStatus install "Rust stable" "would update $stableToolchain and its installed components/targets; rustup itself, other toolchains and defaults are preserved"
        } else {
            Write-DevSetupStatus install "Rust stable" "updating $stableToolchain and its installed components/targets without rustup self-update"
            Invoke-Rustup -Arguments @("update", $stableToolchain, "--no-self-update") | Out-Host
            $upgradeLines = @(Invoke-Rustup -Arguments @("check"))
            if (@($upgradeLines | Where-Object { $_ -match ($stablePattern + 'up to date') }).Count -ne 1) {
                throw "Rust update verification failed: rustup check does not report $stableToolchain up to date."
            }
        }
    }
}

if (@($toolchains | Where-Object { $_ -match '\([^)]*\bdefault\b[^)]*\)' }).Count -eq 0) {
    if ($Audit) {
        Write-DevSetupStatus install "Rust default" "would select stable because no default toolchain exists"
    } else {
        Write-DevSetupStatus install "Rust default" "selecting stable because no default toolchain exists"
        Invoke-Rustup -Arguments @("default", $stableToolchain) | Out-Host
    }
}

function Test-RustEntry {
    param([string[]]$Entries, [string]$Name, [switch]$Component)
    $names = @($Entries | ForEach-Object { ($_ -split '\s+', 2)[0] })
    return $names -ccontains $Name -or ($Component -and $names -ccontains "$Name-$($defaultHost[0])")
}

$available = @(Invoke-Rustup -Arguments @("component", "list", "--toolchain", $stableToolchain))
foreach ($component in $components) {
    if (-not (Test-RustEntry $available $component -Component)) {
        throw "Rust component '$component' is unavailable for $stableToolchain. No requested components or targets were added."
    }
}
if ($targets.Count -gt 0) {
    $availableTargets = @(Invoke-Rustup -Arguments @("target", "list", "--toolchain", $stableToolchain))
    foreach ($target in $targets) {
        if (-not (Test-RustEntry $availableTargets $target)) {
            throw "Rust target '$target' is unavailable for $stableToolchain. No requested components or targets were added."
        }
    }
}
$installed = @(Invoke-Rustup -Arguments @("component", "list", "--installed", "--toolchain", $stableToolchain))
foreach ($component in $components) {
    if (Test-RustEntry $installed $component -Component) {
        Write-DevSetupStatus found "Rust $component" "installed for stable"
    } elseif ($Audit) {
        Write-DevSetupStatus install "Rust $component" "would add component to stable"
    } else {
        Invoke-Rustup -Arguments @("component", "add", "--toolchain", $stableToolchain, $component) | Out-Host
        $installed = @(Invoke-Rustup -Arguments @("component", "list", "--installed", "--toolchain", $stableToolchain))
        if (-not (Test-RustEntry $installed $component -Component)) {
            throw "Rust component '$component' was not installed after rustup reported success."
        }
        Write-DevSetupStatus install "Rust $component" "added to stable"
    }
}
if ($targets.Count -gt 0) {
    $installedTargets = @(Invoke-Rustup -Arguments @("target", "list", "--installed", "--toolchain", $stableToolchain))
    foreach ($target in $targets) {
        if (Test-RustEntry $installedTargets $target) {
            Write-DevSetupStatus found "Rust target" "$target installed for stable"
        } elseif ($Audit) {
            Write-DevSetupStatus install "Rust target" "would add $target to stable"
        } else {
            Invoke-Rustup -Arguments @("target", "add", "--toolchain", $stableToolchain, $target) | Out-Host
            $installedTargets = @(Invoke-Rustup -Arguments @("target", "list", "--installed", "--toolchain", $stableToolchain))
            if (-not (Test-RustEntry $installedTargets $target)) {
                throw "Rust target '$target' was not installed after rustup reported success."
            }
            Write-DevSetupStatus install "Rust target" "added $target to stable"
        }
    }
}
foreach ($tool in @("rustc", "cargo")) {
    if (Test-RustEntry $installed $tool -Component) {
        $version = Invoke-Rustup -Arguments @("run", $stableToolchain, $tool, "--version")
        Write-DevSetupStatus found "Rust $tool" "$version"
    }
}
if ((Test-RustEntry $components "rustfmt" -Component) -and (Test-RustEntry $installed "rustfmt" -Component)) {
    Write-DevSetupStatus found "Rust rustfmt version" "$(Invoke-Rustup -Arguments @('run', $stableToolchain, 'rustfmt', '--version'))"
}
if ((Test-RustEntry $components "clippy" -Component) -and (Test-RustEntry $installed "clippy" -Component) -and
    (Test-RustEntry $installed "cargo" -Component)) {
    Write-DevSetupStatus found "Rust clippy version" "$(Invoke-Rustup -Arguments @('run', $stableToolchain, 'cargo', 'clippy', '--version'))"
}
if ((Test-RustEntry $components "rust-analyzer" -Component) -and (Test-RustEntry $installed "rust-analyzer" -Component)) {
    Write-DevSetupStatus found "Rust analyzer version" "$(Invoke-Rustup -Arguments @('run', $stableToolchain, 'rust-analyzer', '--version'))"
}
if ($CheckUpgrades -or $Upgrade) {
    foreach ($line in $upgradeLines) {
        if ($line -match 'update available') {
            Write-DevSetupStatus update "Rust" "$line (stable: .\setup.ps1 -UpgradeRust; other toolchains/rustup update separately)"
        } elseif ($line -match 'up to date') {
            Write-DevSetupStatus found "Rust" "$line"
        } elseif ($line.Trim()) {
            Write-DevSetupStatus warn "Rust" "upgrade check: $line"
        }
    }
}

if ($Audit) {
    Write-DevSetupStatus skip "Rust build" "linker readiness is unverified; audit does not compile or run code"
    return
}

Add-DevSetupUserPath $cargoBin
Update-DevSetupSessionPath
$probe = Join-Path ([IO.Path]::GetTempPath()) ("devsetup-rust-{0}" -f [guid]::NewGuid())
New-Item -ItemType Directory -Path $probe | Out-Null
try {
    $source = Join-Path $probe "probe.rs"
    $manifest = Join-Path $probe "Cargo.toml"
    $targetDir = Join-Path $probe "target"
    $binary = Join-Path $targetDir "$($defaultHost[0])\debug\devsetup_probe.exe"
    Set-Content -LiteralPath $source -Value 'fn main() { println!("rust-ready"); }' -Encoding ASCII
    Set-Content -LiteralPath $manifest -Encoding ASCII -Value @'
[package]
name = "devsetup_probe"
version = "0.0.0"
edition = "2021"

[workspace]

[[bin]]
name = "devsetup_probe"
path = "probe.rs"
'@
    try {
        Push-Location $probe
        try {
            Invoke-Rustup -Arguments @("run", $stableToolchain, "cargo", "build", "--offline", "--quiet",
                "--target", $defaultHost[0], "--manifest-path", $manifest, "--target-dir", $targetDir) | Out-Host
        } finally {
            Pop-Location
        }
        $output = & $binary 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -or $output.Trim() -ne "rust-ready") { throw "compiled probe did not run successfully: $output" }
        Write-DevSetupStatus found "Rust build" "Cargo compiled, linked, and ran a native executable with stable"
    } catch {
        Write-DevSetupStatus warn "Rust build" "toolchain installed but Cargo native build/run failed: $($_.Exception.Message). Check Cargo configuration; MSVC needs C++ Build Tools and GNU needs compatible MinGW tools. No admin install or global linker override was attempted."
    }
} finally {
    Remove-Item -LiteralPath $probe -Recurse -Force
}
