import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") if os.name == "nt" else None
BASH = shutil.which("bash")
if os.name == "nt":
    git = shutil.which("git")
    git_bash = Path(git).parent.parent / "bin" / "bash.exe" if git else None
    BASH = str(git_bash) if git_bash and git_bash.is_file() else None


class RustInstallerTests(unittest.TestCase):
    def fixture(self, root):
        scripts = root / "src" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("install-rust.ps1", "install-rust.sh"):
            shutil.copyfile(ROOT / "src" / "scripts" / name, scripts / name)
        for name in ("setup.ps1", "setup.sh"):
            shutil.copyfile(ROOT / name, root / name)
        (root / "components").write_text("cargo-host\nrustc-host\nrustfmt-host\n", encoding="utf-8")
        (root / "targets").write_text("host\n", encoding="utf-8")
        install = {
            name: False for name in json.loads(
                (ROOT / "config" / "dev-setup.config.json").read_text()
            )["user"]["install"]
        }
        install["rust"] = True
        (root / "config.json").write_text(json.dumps({
            "user": {
                "install": install, "checkUpgrades": False,
                "rust": {"components": ["rustfmt", "clippy", "rust-src"], "targets": []},
            },
        }))
        return scripts

    def exercise_component_requests(self, root, run, audit):
        (root / "fail").unlink(missing_ok=True)
        config = json.loads((root / "config.json").read_text())

        def request(components, targets):
            config["user"]["rust"] = {"components": components, "targets": targets}
            (root / "config.json").write_text(json.dumps(config))

        request(["rustc", "rust-docs", "rust-docs"], ["wasm32-unknown-unknown"])
        (root / "components").write_text("rustc-dev-host\n")
        (root / "targets").write_text("host\n")
        before = (root / "components").read_bytes()
        output = run(audit)
        self.assertIn("Rust rustc", output)
        self.assertIn("would add component", output)
        self.assertIn("would add wasm32-unknown-unknown", output)
        self.assertEqual((root / "components").read_bytes(), before)
        (root / "calls").write_text("")
        output = run()
        self.assertIn("Rust rust-docs", output)
        self.assertEqual((root / "calls").read_text().count("component add --toolchain stable-host rust-docs"), 1)
        self.assertIn("wasm32-unknown-unknown", (root / "targets").read_text())
        self.assertNotIn("[install]", run())

        for components, targets, message in (
            ("clippy", [], "must be an array"),
            ([42], [], "must be an array"),
            (["--force"], [], "Invalid Rust"),
            (["bad\nname"], [], "single-line"),
            (["miri"], [], "unavailable"),
            (["rust-src"], ["not-a-target"], "unavailable"),
        ):
            with self.subTest(components=components, targets=targets):
                request(components, targets)
                (root / "calls").write_text("")
                self.assertIn(message, run(success=False))
                calls = (root / "calls").read_text()
                self.assertNotIn("component add", calls)
                self.assertNotIn("target add", calls)

        request([], [])
        self.assertNotIn("Rust rust-docs", run())
        request(["rust-docs"], [])
        (root / "components").write_text("rustfmt-host\n")
        (root / "silent-add").touch()
        self.assertIn("was not installed", run(success=False))
        request([], ["wasm32-unknown-unknown"])
        (root / "targets").write_text("host\n")
        self.assertIn("was not installed", run(success=False))
        (root / "silent-add").unlink()
        request(None, None)
        self.assertIn("Rust clippy", run(audit))
        request(["rustfmt"], [])
        (root / "components").write_text("rustfmt-host\n")
        (root / "version-failure").touch()
        self.assertIn("fixture version failure", run(success=False))
        (root / "version-failure").unlink()

    def exercise_explicit_updates(self, root, run, flags):
        config = json.loads((root / "config.json").read_text())
        config["user"]["rust"] = {
            "components": ["rustfmt", "clippy", "rust-src"], "targets": [],
        }
        (root / "config.json").write_text(json.dumps(config))
        (root / "components").write_text("rustfmt-host\nclippy-host\nrust-src\n")
        (root / "calls").write_text("")
        output = run(flags["upgrade"], flags["audit"])
        self.assertIn("would update stable-host", output)
        self.assertNotIn("update stable-host", (root / "calls").read_text())
        output = run(flags["setup_upgrade"], flags["skip_check"], flags["audit"], setup=True)
        self.assertIn("would update stable-host", output)
        self.assertIn(flags["setup_upgrade"], output.split("APPLY:")[-1]
                      if "APPLY:" in output else output.split("Run this to apply them:")[-1])
        (root / "calls").write_text("")
        run(flags["setup_upgrade"], flags["check_only"], setup=True)
        self.assertNotIn("update stable-host", (root / "calls").read_text())

        output = run(flags["setup_upgrade"], flags["skip_check"], setup=True)
        self.assertIn("updating stable-host", output)
        calls = (root / "calls").read_text()
        self.assertIn("update stable-host --no-self-update", calls)
        self.assertNotIn("self update", calls)
        self.assertNotIn("default ", calls)
        (root / "calls").write_text("")
        self.assertNotIn("[install]", run(flags["upgrade"]))
        self.assertNotIn("update stable-host", (root / "calls").read_text())

        for marker in ("update-failure", "stale-update", "check-failure"):
            with self.subTest(marker=marker):
                (root / "updated").unlink(missing_ok=True)
                (root / marker).touch()
                run(flags["upgrade"], success=False)
                (root / marker).unlink()

        config["user"]["install"]["rust"] = False
        config["user"]["rust"]["components"] = "ignored-when-disabled"
        (root / "config.json").write_text(json.dumps(config))
        self.assertIn("user.install.rust is false", run(flags["setup_upgrade"], setup=True))
        self.assertIn("cannot be combined",
                      run(flags["uninstall"], flags["upgrade"], success=False))

    def exercise_cargo_support(self, root, run, audit):
        config = json.loads((root / "config.json").read_text())
        config["user"]["rust"] = {"components": ["clippy"], "targets": []}
        (root / "config.json").write_text(json.dumps(config))
        (root / "components").write_text("rustc-host\nclippy-host\n")
        (root / "calls").write_text("")
        self.assertIn("would add component", run(audit))
        self.assertNotIn("cargo clippy --version", (root / "calls").read_text())
        self.assertEqual((root / "components").read_text(), "rustc-host\nclippy-host\n")

        config["user"]["rust"] = {"components": [], "targets": []}
        (root / "config.json").write_text(json.dumps(config))
        (root / "components").write_text("")
        (root / "calls").write_text("")
        output = run(audit)
        self.assertIn("Rust cargo", output)
        self.assertIn("would add component", output)
        self.assertEqual((root / "components").read_text(), "")
        calls = (root / "calls").read_text()
        self.assertNotIn("component add", calls)
        self.assertNotIn("cargo --version", calls)
        self.assertNotIn("cargo build", calls)

        (root / "calls").write_text("")
        output = run()
        self.assertIn("Cargo compiled, linked, and ran", output)
        calls = (root / "calls").read_text()
        for component in ("cargo", "rustc"):
            self.assertEqual(
                calls.count(f"component add --toolchain stable-host {component}"), 1,
            )
        self.assertIn("cargo build --offline", calls)
        self.assertFalse(Path((root / "probe-dir").read_text().strip()).exists())
        (root / "calls").write_text("")
        second = run()
        self.assertNotIn("[install]", second)
        self.assertNotIn("[warn]", second)
        self.assertNotIn("component add", (root / "calls").read_text())

        (root / "cargo-failure").touch()
        try:
            output = run()
            self.assertIn("native build/run failed", output)
            self.assertIn("fixture cargo failure", output)
            self.assertFalse(Path((root / "probe-dir").read_text().strip()).exists())
        finally:
            (root / "cargo-failure").unlink()

    @unittest.skipUnless(POWERSHELL, "Windows PowerShell is required")
    def test_windows_bootstrap_verifies_digest_before_execution(self):
        for bad_hash in (False, True):
            with self.subTest(bad_hash=bad_hash), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                scripts = self.fixture(root)
                env = {
                    **os.environ, "FIXTURE": str(root),
                    "CARGO_HOME": str(root / "cargo"), "NO_COLOR": "1",
                    "BAD_HASH": "1" if bad_hash else "0",
                }
                env = {key: value for key, value in env.items() if key.lower() != "psmodulepath"}
                fixture_source = root / "build-fixture.ps1"
                fixture_source.write_text(r"""
Add-Type -TypeDefinition 'public class Bootstrap { public static void Main(string[] args) { System.Console.WriteLine("rustup bootstrap progress"); System.IO.File.WriteAllText(System.IO.Path.Combine(System.Environment.GetEnvironmentVariable("FIXTURE"), "executed"), string.Join(" ", args)); var bin = System.IO.Path.Combine(System.Environment.GetEnvironmentVariable("CARGO_HOME"), "bin"); System.IO.Directory.CreateDirectory(bin); System.IO.File.Copy(System.Environment.GetCommandLineArgs()[0], System.IO.Path.Combine(bin, "rustup.exe")); } }' -OutputAssembly (Join-Path $env:FIXTURE 'bootstrap.exe') -OutputType ConsoleApplication
""", encoding="utf-8")
                built = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(fixture_source)],
                    env=env, capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(built.returncode, 0, built.stderr)
                (root / "src" / "config.ps1").write_text(r"""
. 'REAL_MODULE'
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    if ($OutFile) { Copy-Item (Join-Path $env:FIXTURE 'bootstrap.exe') $OutFile }
    else {
        $digest = (Get-FileHash (Join-Path $env:FIXTURE 'bootstrap.exe') -Algorithm SHA256).Hash
        if ($env:BAD_HASH -eq '1') { $digest = '0' * 64 }
        return [pscustomobject]@{Content=[Text.Encoding]::UTF8.GetBytes("$digest rustup-init.exe")}
    }
}
function Install-DevSetupWingetTool {
    param($Component, $PackageId, $Find, [switch]$Audit, [switch]$CheckUpgrades, $ManualInstallHint, $FallbackInstall, $FallbackDescription)
    if ($env:RUSTUP_AUTO_INSTALL -ne '0') { throw 'Bootstrap inspection must not provision project overrides' }
    $result = @(& $FallbackInstall)
    if ($result.Count -ne 1 -or -not (Test-Path $result[0])) { throw 'Bootstrap leaked output instead of returning one executable path' }
    Write-Host 'PASS: verified bootstrap executed'
    exit 0
}
""".replace("REAL_MODULE", str(ROOT / "src" / "config.ps1").replace("'", "''")), encoding="utf-8")
                result = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-NonInteractive", "-File",
                     str(scripts / "install-rust.ps1")],
                    env=env, capture_output=True, text=True, timeout=30, check=False,
                )
                if bad_hash:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("SHA256 verification failed", result.stderr)
                    self.assertFalse((root / "executed").exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("PASS: verified bootstrap executed", result.stdout)
                    self.assertIn("rustup bootstrap progress", result.stdout)
                    self.assertEqual(
                        (root / "executed").read_text(),
                        "-y --no-modify-path --default-toolchain none --profile minimal",
                    )

    @unittest.skipUnless(POWERSHELL, "Windows PowerShell is required")
    def test_windows_winget_helper_returns_only_the_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tool.ps1").write_text("'fixture version'\n", encoding="utf-8")
            harness = root / "test.ps1"
            harness.write_text(r"""
$ErrorActionPreference = 'Stop'
. 'REAL_MODULE'
$global:installed = $false
function winget.exe {
    $global:installed = $true
    $global:LASTEXITCODE = 0
    'WinGet installation progress'
}
function Update-DevSetupSessionPath {}
$find = { if ($global:installed) { Join-Path $PSScriptRoot 'tool.ps1' } }
$result = @(Install-DevSetupWingetTool -Component fixture -PackageId fixture -Find $find -ManualInstallHint fixture)
if ($result.Count -ne 1 -or $result[0] -ne (Join-Path $PSScriptRoot 'tool.ps1')) {
    throw 'WinGet helper leaked installation output'
}
Write-Host 'PASS: one executable path'
""".replace("REAL_MODULE", str(ROOT / "src" / "config.ps1").replace("'", "''")), encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(harness)],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WinGet installation progress", result.stdout)
            self.assertIn("PASS: one executable path", result.stdout)

    @unittest.skipUnless(POWERSHELL, "Windows PowerShell is required")
    def test_windows_user_path_audit_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = Path(temp_dir) / "test.ps1"
            harness.write_text(r"""
$ErrorActionPreference = 'Stop'
. 'REAL_MODULE'
$before = [Environment]::GetEnvironmentVariable('Path', 'User')
Add-DevSetupUserPath (Join-Path $PSScriptRoot 'future-cargo-bin') -Audit
if ($before -ne [Environment]::GetEnvironmentVariable('Path', 'User')) {
    throw 'Audit changed the persistent user PATH'
}
Write-Host 'PASS: user PATH unchanged'
""".replace("REAL_MODULE", str(ROOT / "src" / "config.ps1").replace("'", "''")), encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(harness)],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("would add", result.stdout)
            self.assertIn("PASS: user PATH unchanged", result.stdout)

    @unittest.skipUnless(POWERSHELL, "Windows PowerShell is required")
    def test_windows_audit_repair_idempotence_and_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = self.fixture(root)
            (root / "src" / "config.ps1").write_text(r"""
. 'REAL_MODULE'
function Get-DevSetupConfig {
    Get-Content (Join-Path $env:FIXTURE 'config.json') -Raw | ConvertFrom-Json
}
function Install-DevSetupWingetTool {
    param($Component, $PackageId, $Find, [switch]$Audit, [switch]$CheckUpgrades, $ManualInstallHint, $FallbackInstall, $FallbackDescription)
    if ($env:RUSTUP_AUTO_INSTALL -ne '0') { throw 'Manager inspection must not provision project overrides' }
    return (Join-Path $env:FIXTURE 'rustup.ps1')
}
function Add-DevSetupUserPath {
    param($Directory, [switch]$Audit)
    if ($Audit) { Write-Host '[install] PATH would add cargo bin' }
    else { Write-Host '[found] PATH fixture' }
}
function Update-DevSetupSessionPath {}
""".replace("REAL_MODULE", str(ROOT / "src" / "config.ps1").replace("'", "''")), encoding="utf-8")
            (root / "rustup.ps1").write_text(r"""
$arguments = @($args)
Add-Content (Join-Path $env:FIXTURE 'calls') ($arguments -join ' ')
if ($env:RUSTUP_AUTO_INSTALL -ne '0') { throw 'Inspection must not provision repository overrides' }
switch ($arguments[0]) {
    '--version' { 'rustup fixture' }
    'show' {
        if ($env:RUSTUP_AUTO_INSTALL -ne '0') { throw 'Host inspection must not provision repository overrides' }
        'Default host: host'
    }
    'toolchain' {
        if ($arguments[1] -eq 'install') {
            if ($arguments[2] -ne 'stable-host') { throw 'Wrong stable host' }
            Remove-Item (Join-Path $env:FIXTURE 'no-stable')
            break
        }
        'stable-other-host'
        if (-not (Test-Path (Join-Path $env:FIXTURE 'no-stable'))) { 'stable-host' }
        '1.99.1-host (active, default)'
    }
    'component' {
        if ($arguments -notcontains 'stable-host') { throw 'Wrong component host' }
        if (Test-Path (Join-Path $env:FIXTURE 'no-stable')) { throw 'Stable host is missing' }
        if ($arguments[1] -eq 'list') {
            if ($arguments -contains '--installed') { Get-Content (Join-Path $env:FIXTURE 'components') }
            else { 'cargo-host'; 'rustfmt-host'; 'clippy-host'; 'rust-src'; 'rust-docs-host'; 'rustc-host'; 'rustc-dev-host' }
        } elseif (-not (Test-Path (Join-Path $env:FIXTURE 'silent-add'))) {
            Add-Content (Join-Path $env:FIXTURE 'components') $arguments[-1]
        }
    }
    'target' {
        if ($arguments -notcontains 'stable-host') { throw 'Wrong target host' }
        if ($arguments[1] -eq 'list') {
            if ($arguments -contains '--installed') { Get-Content (Join-Path $env:FIXTURE 'targets') }
            else { 'host (installed)'; 'wasm32-unknown-unknown' }
        } elseif (-not (Test-Path (Join-Path $env:FIXTURE 'silent-add'))) {
            Add-Content (Join-Path $env:FIXTURE 'targets') $arguments[-1]
        }
    }
    'update' {
        if (($arguments -join ' ') -ne 'update stable-host --no-self-update') { throw 'Unsafe update' }
        if (Test-Path (Join-Path $env:FIXTURE 'update-failure')) { exit 9 }
        if (-not (Test-Path (Join-Path $env:FIXTURE 'stale-update'))) {
            New-Item -ItemType File (Join-Path $env:FIXTURE 'updated') -Force | Out-Null
        }
    }
    'default' { throw 'Must not replace an existing default' }
    'run' {
        if ($arguments[1] -ne 'stable-host') { throw 'Wrong run host' }
        if ($arguments[-1] -eq '--version') {
            if ($arguments[2] -eq 'rustfmt' -and (Test-Path (Join-Path $env:FIXTURE 'version-failure'))) {
                [Console]::Error.WriteLine('fixture version failure')
                exit 7
            }
            $installedComponents = @(Get-Content (Join-Path $env:FIXTURE 'components'))
            if ($arguments[2] -eq 'rustfmt' -and $installedComponents -notcontains 'rustfmt-host' -and $installedComponents -notcontains 'rustfmt') {
                throw 'Rustfmt was inspected before installation'
            }
            if ($arguments -contains 'clippy' -and $installedComponents -notcontains 'clippy' -and $installedComponents -notcontains 'clippy-host') {
                throw 'Clippy was inspected before installation'
            }
            "$($arguments[2]) fixture"
        }
        elseif ($arguments[2] -eq 'cargo' -and $arguments[3] -eq 'build') {
            foreach ($flag in @('--offline', '--quiet', '--manifest-path', '--target-dir', '--target')) {
                if ($arguments -notcontains $flag) { throw "Cargo probe missing $flag" }
            }
            $manifest = $arguments[[array]::IndexOf($arguments, '--manifest-path') + 1]
            $targetDir = $arguments[[array]::IndexOf($arguments, '--target-dir') + 1]
            $probe = Split-Path $manifest
            if ((Get-Location).Path -ne $probe) { throw 'Cargo inherited the project working directory' }
            if ($arguments[[array]::IndexOf($arguments, '--target') + 1] -ne 'host') { throw 'Cargo probe must use the native host' }
            if ((Get-Content $manifest -Raw) -notmatch '\[workspace\]') { throw 'Cargo probe must be a standalone workspace' }
            if ($targetDir -ne (Join-Path $probe 'target')) { throw 'Cargo probe outputs must be isolated' }
            Set-Content (Join-Path $env:FIXTURE 'probe-dir') $probe
            if (Test-Path (Join-Path $env:FIXTURE 'cargo-failure')) {
                [Console]::Error.WriteLine('fixture cargo failure')
                exit 1
            }
            if (Test-Path (Join-Path $env:FIXTURE 'fail')) { Write-Output 'fixture linker missing'; exit 1 }
            $destination = Join-Path $targetDir 'host\debug'
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Copy-Item (Join-Path $env:FIXTURE 'ready.exe') (Join-Path $destination 'devsetup_probe.exe')
        } else {
            if (Test-Path (Join-Path $env:FIXTURE 'fail')) { Write-Output 'fixture linker missing'; exit 1 }
            $destination = $arguments[-1]
            Copy-Item (Join-Path $env:FIXTURE 'ready.exe') $destination
        }
    }
    'check' {
        if (Test-Path (Join-Path $env:FIXTURE 'check-failure')) { exit 8 }
        if (Test-Path (Join-Path $env:FIXTURE 'updated')) { 'stable-host - Up to date : 1.99.1' }
        else {
            'stable-host - Update available : 1.98.0 -> 1.99.1'
            exit 100
        }
        'rustup - Up to date : 1.29'
    }
    default { throw "Unexpected command: $arguments" }
}
exit 0
""", encoding="utf-8")
            env = {
                **os.environ, "FIXTURE": str(root), "NO_COLOR": "1",
                "DEVSETUP_STATUS_LOG": str(root / "status.log"),
            }
            env = {key: value for key, value in env.items() if key.lower() != "psmodulepath"}
            # Build only a disposable fixture executable, never a toolchain or machine install.
            fixture_source = root / "build-fixture.ps1"
            fixture_source.write_text(r"""
Add-Type -TypeDefinition 'public class Ready { public static void Main() { System.Console.WriteLine("rust-ready"); } }' -OutputAssembly (Join-Path $env:FIXTURE 'ready.exe') -OutputType ConsoleApplication
""", encoding="utf-8")
            built = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(fixture_source)],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(built.returncode, 0, built.stderr)

            def run(*args, success=True, setup=False):
                script = root / "setup.ps1" if setup else scripts / "install-rust.ps1"
                result = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-NonInteractive", "-File",
                     str(script), *args],
                    env=env, capture_output=True, text=True, timeout=120, check=False,
                )
                if success:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr

            original = (root / "components").read_bytes()
            audit = run("-Audit", "-CheckUpgrades")
            self.assertIn("would add", audit)
            self.assertIn("PATH would add", audit)
            self.assertIn("[update]", audit)
            self.assertIn("rustup update", audit)
            self.assertIn("update|Rust|", (root / "status.log").read_text())
            self.assertIn("readiness is unverified", audit)
            self.assertIn("Rust rustfmt version", audit)
            self.assertNotIn("Rust clippy version", audit)
            self.assertEqual((root / "components").read_bytes(), original)
            calls = (root / "calls").read_text()
            self.assertNotIn("component add", calls)
            self.assertNotIn("cargo build", calls)
            applied = run()
            self.assertIn("compiled, linked, and ran", applied)
            self.assertIn("Rust clippy version", applied)
            second = run()
            self.assertNotIn("[install]", second)
            self.assertNotIn("[warn]", second)
            (root / "no-stable").touch()
            self.assertIn("would install stable", run("-Audit"))
            self.assertTrue((root / "no-stable").exists())
            self.assertIn("installing stable", run())
            self.assertFalse((root / "no-stable").exists())
            (root / "fail").touch()
            self.assertIn("native build/run failed", run())
            self.assertIn("preserved", run("-Uninstall"))
            self.exercise_component_requests(root, run, "-Audit")
            self.exercise_cargo_support(root, run, "-Audit")
            self.exercise_explicit_updates(root, run, {
                "audit": "-Audit", "upgrade": "-Upgrade", "setup_upgrade": "-UpgradeRust",
                "skip_check": "-SkipUpgradeCheck", "check_only": "-CheckUpgradesOnly",
                "uninstall": "-Uninstall",
            })

    @unittest.skipUnless(BASH, "Bash is required")
    def test_bash_audit_repair_idempotence_and_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.fixture(root)
            (root / "src" / "config.sh").write_text("""
. "$REAL_CONFIG"
devsetup_is_elevated() { return 1; }
devsetup_status() {
    printf '[%s] %s %s\\n' "$1" "$2" "$3"
    printf '%s|%s|%s\\n' "$1" "$2" "$3" >> "$HOME/status.log"
}
devsetup_homebrew_path() {
    if [[ -x "$HOME/brew" ]]; then printf '%s\\n' "$HOME/brew"
    else return 1; fi
}
""", encoding="utf-8")
            (root / "rustup").write_text("""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$HOME/calls"
[[ "$RUSTUP_AUTO_INSTALL" == 0 ]] || exit 2
case "$1" in
--version) echo 'rustup fixture' ;;
show)
    [[ "$RUSTUP_AUTO_INSTALL" == 0 ]] || exit 2
    echo 'Default host: host' ;;
toolchain)
    if [[ "$2" == install ]]; then
        [[ "$3" == stable-host ]] || exit 2
        rm "$HOME/no-stable"
    else
        echo 'stable-other-host'
        if [[ ! -f "$HOME/no-stable" ]]; then echo 'stable-host'; fi
        echo '1.99.1-host (active, default)'
    fi ;;
component)
    [[ " $* " == *" stable-host "* && ! -f "$HOME/no-stable" ]] || exit 2
    if [[ "$2" == list ]]; then
        if [[ " $* " == *" --installed "* ]]; then cat "$HOME/components"
        else printf '%s\\n' cargo-host rustfmt-host clippy-host rust-src rust-docs-host rustc-host rustc-dev-host; fi
    elif [[ ! -f "$HOME/silent-add" ]]; then
        printf '%s\\n' "${@: -1}" >> "$HOME/components"
    fi ;;
target)
    [[ " $* " == *" stable-host "* ]] || exit 2
    if [[ "$2" == list ]]; then
        if [[ " $* " == *" --installed "* ]]; then cat "$HOME/targets"
        else printf '%s\\n' 'host (installed)' wasm32-unknown-unknown; fi
    elif [[ ! -f "$HOME/silent-add" ]]; then
        printf '%s\\n' "${@: -1}" >> "$HOME/targets"
    fi ;;
update)
    [[ "$*" == 'update stable-host --no-self-update' ]] || exit 2
    [[ ! -f "$HOME/update-failure" ]] || exit 9
    if [[ ! -f "$HOME/stale-update" ]]; then touch "$HOME/updated"; fi ;;
default) echo 'must preserve default' >&2; exit 1 ;;
run)
    [[ "$2" == stable-host ]] || exit 2
    if [[ "${@: -1}" == --version ]]; then
        if [[ "$3" == rustfmt && -f "$HOME/version-failure" ]]; then echo 'fixture version failure' >&2; exit 7; fi
        if [[ "$3" == rustfmt ]]; then grep -Eq '^rustfmt(-host)?$' "$HOME/components" || exit 3; fi
        if [[ " $* " == *" clippy "* ]]; then grep -Eq '^clippy(-host)?$' "$HOME/components" || exit 3; fi
        if [[ " $* " == *" clippy "* && -f "$HOME/check-cargo-proxies" ]]; then
            cargo-clippy --version
            exit
        fi
        echo "$3 fixture"
    elif [[ "$3" == cargo && "$4" == build ]]; then
        shift 4
        manifest="" target_dir="" target="" offline=0 quiet=0
        while [[ $# -gt 0 ]]; do
            case "$1" in
            --offline) offline=1 ;;
            --quiet) quiet=1 ;;
            --manifest-path) shift; manifest="$1" ;;
            --target-dir) shift; target_dir="$1" ;;
            --target) shift; target="$1" ;;
            *) echo "Unexpected Cargo argument: $1" >&2; exit 2 ;;
            esac
            shift
        done
        [[ "$offline" == 1 && "$quiet" == 1 && "$target" == host ]] || exit 2
        [[ "$PWD/Cargo.toml" == "$manifest" && "$PWD/target" == "$target_dir" ]] || exit 2
        grep -Fq '[workspace]' "$manifest" || exit 2
        printf '%s\\n' "$PWD" > "$HOME/probe-dir"
        if [[ -f "$HOME/cargo-failure" ]]; then echo 'fixture cargo failure' >&2; exit 1; fi
        if [[ -f "$HOME/fail" ]]; then echo 'fixture linker missing' >&2; exit 1; fi
        mkdir -p "$target_dir/host/debug"
        printf '#!/usr/bin/env bash\\necho rust-ready\\n' > "$target_dir/host/debug/devsetup_probe"
        chmod +x "$target_dir/host/debug/devsetup_probe"
    elif [[ -f "$HOME/fail" ]]; then echo 'fixture linker missing' >&2; exit 1
    else
        printf '#!/usr/bin/env bash\\necho rust-ready\\n' > "${@: -1}"
        chmod +x "${@: -1}"
    fi ;;
check)
    [[ ! -f "$HOME/check-failure" ]] || exit 8
    if [[ -f "$HOME/updated" ]]; then echo 'stable-host - Up to date : 1.99.1'
    else
        echo 'stable-host - Update available : 1.98.0 -> 1.99.1'
        exit 100
    fi
    echo 'rustup - Up to date : 1.29' ;;
*) exit 2 ;;
esac
""", encoding="utf-8")
            env = {
                **os.environ, "TEST_HOME": str(root), "NO_COLOR": "1",
                "REAL_CONFIG": str(ROOT / "src" / "config.sh"),
                "DEVSETUP_CONFIG_FILE": str(root / "config.json"),
                "FIXTURE_PYTHON": sys.executable,
            }
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            (root / "python3").write_text('#!/usr/bin/env bash\nexec "$FIXTURE_PYTHON" "$@"\n')
            bash_setup = """
if command -v cygpath >/dev/null 2>&1; then
    export HOME="$(cygpath -u "$TEST_HOME")"
    export REAL_CONFIG="$(cygpath -u "$REAL_CONFIG")"
    export DEVSETUP_CONFIG_FILE="$(cygpath -u "$DEVSETUP_CONFIG_FILE")"
else
    export HOME="$TEST_HOME"
fi
export PATH="$HOME:$PATH"
uname() { echo Linux; }
export -f uname
chmod +x "$HOME/rustup" "$HOME/python3"
bash "$FIXTURE_SCRIPT" "$@"
"""

            def run(*args, success=True, setup=False):
                env["FIXTURE_SCRIPT"] = "setup.sh" if setup else "src/scripts/install-rust.sh"
                result = subprocess.run(
                    [BASH, "-c", bash_setup, "fixture", *args], cwd=root, env=env,
                    capture_output=True, text=True, timeout=120, check=False,
                )
                if success:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr

            original = (root / "components").read_bytes()
            audit = run("--audit", "--check-upgrades")
            self.assertIn("would add", audit)
            self.assertIn("would add Rust tools", audit)
            self.assertIn("[update]", audit)
            self.assertIn("rustup update", audit)
            self.assertIn("update|Rust|", (root / "status.log").read_text())
            self.assertIn("Rust rustfmt version", audit)
            self.assertNotIn("Rust clippy version", audit)
            self.assertEqual((root / "components").read_bytes(), original)
            self.assertFalse((root / ".profile").exists())
            self.assertNotIn("component add", (root / "calls").read_text())
            applied = run()
            self.assertIn("compiled, linked, and ran", applied)
            self.assertIn("Rust clippy version", applied)
            before = (root / ".profile").read_bytes()
            second = run()
            self.assertNotIn("[install]", second)
            self.assertNotIn("[warn]", second)
            self.assertEqual((root / ".profile").read_bytes(), before)
            (root / "no-stable").touch()
            self.assertIn("would install stable", run("--audit"))
            self.assertTrue((root / "no-stable").exists())
            self.assertIn("installing stable", run())
            self.assertFalse((root / "no-stable").exists())
            (root / "fail").touch()
            self.assertIn("native build/run failed", run())
            self.assertIn("preserved", run("--uninstall"))
            self.exercise_component_requests(root, run, "--audit")
            self.exercise_cargo_support(root, run, "--audit")
            self.exercise_explicit_updates(root, run, {
                "audit": "--audit", "upgrade": "--upgrade", "setup_upgrade": "--upgrade-rust",
                "skip_check": "--skip-upgrade-check", "check_only": "--check-upgrades-only",
                "uninstall": "--uninstall",
            })
            if os.name != "nt":
                config = json.loads((root / "config.json").read_text())
                config["user"]["install"]["rust"] = True
                config["user"]["rust"] = {"components": ["clippy"], "targets": []}
                (root / "config.json").write_text(json.dumps(config))
                proxy_bin = root / "homebrew" / "opt" / "rustup" / "bin"
                proxy_bin.mkdir(parents=True)
                (root / "rustup").rename(proxy_bin / "rustup")
                (root / "rustup").symlink_to(proxy_bin / "rustup")
                (proxy_bin / "cargo-clippy").write_text("#!/usr/bin/env bash\necho 'clippy fixture'\n")
                (proxy_bin / "cargo-clippy").chmod(0o755)
                (root / "brew").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$HOME/homebrew"\n')
                (root / "brew").chmod(0o755)
                (root / "check-cargo-proxies").touch()
                before = (root / ".profile").read_bytes()
                self.assertIn("clippy fixture", run("--audit"))
                self.assertEqual((root / ".profile").read_bytes(), before)
                self.assertIn("added Rust tools", run())
                self.assertIn(str(proxy_bin), (root / ".profile").read_text())
                self.assertNotIn("[install]", run())

    def test_all_entrypoint_modes_are_wired(self):
        for name, installer in (("setup.ps1", "install-rust.ps1"), ("setup.sh", "install-rust.sh")):
            text = (ROOT / name).read_text()
            self.assertEqual(text.count(installer), 3)
            self.assertIn("user.install.rust is false", text)
        config = json.loads((ROOT / "config" / "dev-setup.config.json").read_text())
        self.assertEqual(config["advanced"]["rust"]["wingetPackageId"], "Rustlang.Rustup")
        self.assertEqual(config["advanced"]["rust"]["homebrewFormula"], "rustup")
        self.assertEqual(config["user"]["rust"]["components"], ["rustfmt", "clippy", "rust-src"])
        self.assertEqual(config["user"]["rust"]["targets"], [])
        self.assertIn("-Upgrade:$UpgradeRust", (ROOT / "setup.ps1").read_text())
        self.assertIn("--upgrade-rust) upgrade_rust=1", (ROOT / "setup.sh").read_text())

    @unittest.skipUnless(BASH, "Bash is required")
    def test_bash_list_reader_validation_and_deduplication(self):
        readers = ["python"]
        if shutil.which("jq"):
            readers.append("jq")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "python3").write_text('#!/usr/bin/env bash\nexec "$FIXTURE_PYTHON" "$@"\n')
            for reader in readers:
                with self.subTest(reader=reader):
                    env = {
                        **os.environ, "TEST_HOME": str(root), "TEST_READER": reader,
                        "REAL_CONFIG": str(ROOT / "src" / "config.sh"),
                        "FIXTURE_PYTHON": sys.executable,
                        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
                    }
                    result = subprocess.run(
                        [BASH, "-c", r"""
set -euo pipefail
if command -v cygpath >/dev/null 2>&1; then
    export HOME="$(cygpath -u "$TEST_HOME")"
    REAL_CONFIG="$(cygpath -u "$REAL_CONFIG")"
else export HOME="$TEST_HOME"; fi
export PATH="$HOME:$PATH"
chmod +x "$HOME/python3"
. "$REAL_CONFIG"
DEVSETUP_READER="$TEST_READER"
DEVSETUP_CONFIG_FILE="$HOME/request.json"
printf '%s' '{"user":{"rust":{"components":["rustfmt","clippy","rustfmt"]}}}' > "$DEVSETUP_CONFIG_FILE"
[[ "$(devsetup_config_list user.rust.components)" == $'rustfmt\nclippy' ]]
printf '%s' '{"user":{"rust":{"components":[]}}}' > "$DEVSETUP_CONFIG_FILE"
[[ -z "$(devsetup_config_list user.rust.components rust-src)" ]]
printf '%s' '{"user":{"rust":{"components":null}}}' > "$DEVSETUP_CONFIG_FILE"
[[ "$(devsetup_config_list user.rust.components rust-src)" == rust-src ]]
for value in '"clippy"' '[42]' '[""]' '["bad\nname"]' '{}'; do
    printf '{"user":{"rust":{"components":%s}}}' "$value" > "$DEVSETUP_CONFIG_FILE"
    if devsetup_config_list user.rust.components; then exit 1; fi
done
echo 'PASS: validated list reader'
"""],
                        cwd=root, env=env, capture_output=True, text=True, timeout=120, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("PASS: validated list reader", result.stdout)


if __name__ == "__main__":
    unittest.main()
