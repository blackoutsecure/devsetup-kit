import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell") if os.name == "nt" else shutil.which("pwsh")
BASH = "/bin/bash" if sys.platform == "darwin" else shutil.which("bash")
if os.name == "nt":
    git = shutil.which("git")
    git_bash = Path(git).parent.parent / "bin" / "bash.exe" if git else None
    BASH = str(git_bash) if git_bash and git_bash.is_file() else None


class PowerShellWiringTests(unittest.TestCase):
    def test_upgrade_is_explicit_and_wired_on_both_platforms(self):
        windows = (ROOT / "setup.ps1").read_text()
        unix = (ROOT / "setup.sh").read_text()
        self.assertIn("[switch]$UpgradePowerShell", windows)
        self.assertIn("-Upgrade:$UpgradePowerShell", windows)
        self.assertIn("--upgrade-powershell) upgrade_powershell=1", unix)


@unittest.skipUnless(POWERSHELL, "PowerShell is required")
class WindowsPowerShellInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scripts = self.root / "src" / "scripts"
        self.scripts.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "src" / "scripts" / "install-powershell.ps1",
            self.scripts / "install-powershell.ps1",
        )
        shutil.copyfile(ROOT / "setup.ps1", self.root / "setup.ps1")
        self.version("7.6.9", "7.6.10")
        (self.root / "installed.ps1").write_text(
            '$global:LASTEXITCODE = 0\n'
            '"PowerShell $(Get-Content (Join-Path $env:FIXTURE \'version\'))"\n'
        )
        module = str(ROOT / "src" / "config.ps1").replace("'", "''")
        (self.root / "src" / "config.ps1").write_text(r"""
. 'REAL_MODULE'
$script:portableInstaller = ${function:Install-DevSetupPortableRuntime}
function Get-DevSetupConfig {
    $install = [ordered]@{}
    foreach ($tool in @('git', 'githubCli', 'node', 'prettier', 'python', 'rust', 'dioxus', 'php',
        'powershell', 'shellcheck', 'ripgrep', 'busybox', 'packer', 'gpg', 'vscodeSettings')) {
        $install[$tool] = $false
    }
    $install.powershell = -not (Test-Path (Join-Path $env:FIXTURE 'disabled'))
    [pscustomobject]@{
        user=[pscustomobject]@{install=[pscustomobject]$install; checkUpgrades=$false}
        advanced=[pscustomobject]@{powershell=[pscustomobject]@{
            portableInstallDir=(Join-Path $env:FIXTURE 'runtime')
        }}
    }
}
function Get-Command {
    [CmdletBinding()]
    param([string]$Name, [switch]$All)
    if ($Name -eq 'pwsh.exe') {
        if (Test-Path (Join-Path $env:FIXTURE 'missing')) { return }
        $pointer = Join-Path $env:FIXTURE 'upgrade-path'
        $path = if (Test-Path $pointer) { Get-Content $pointer } else { Join-Path $env:FIXTURE 'installed.ps1' }
        return [pscustomobject]@{Source=$path}
    }
    Microsoft.PowerShell.Core\Get-Command @PSBoundParameters
}
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    if ($TimeoutSec -ne 30) { throw 'Release request must be bounded' }
    if (Test-Path (Join-Path $env:FIXTURE 'network-failure')) { throw 'fixture network failure' }
    Get-Content (Join-Path $env:FIXTURE 'release.json') -Raw | ConvertFrom-Json
}
function Install-DevSetupPortableRuntime {
    param($Config, $Tool, $InstallDirectory, $ReleaseMetadata)
    if (Test-Path (Join-Path $env:FIXTURE 'upgrade-failure')) { throw 'fixture upgrade failure' }
    $version = $ReleaseMetadata.tag_name -replace '^v', ''
    if ($Tool -ne 'powershell' -or $InstallDirectory -ne (Join-Path (Join-Path $env:FIXTURE 'runtime') $version)) {
        throw 'Upgrade did not select a versioned user-local directory'
    }
    Add-Content (Join-Path $env:FIXTURE 'upgrades') $version
    New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
    $path = Join-Path $InstallDirectory 'pwsh.ps1'
    if (Test-Path (Join-Path $env:FIXTURE 'wrong-version')) { $version = '7.6.0' }
    Set-Content $path ('$global:LASTEXITCODE = 0; "PowerShell ' + $version + '"')
    Set-Content (Join-Path $env:FIXTURE 'upgrade-path') $path
    return $path
}
function Install-DevSetupWingetTool {
    param($Component, $PackageId, $Find, [switch]$Audit, $FallbackInstall, $ManualInstallHint)
    if (-not $Audit) { throw 'Unexpected real package-manager installation' }
    Write-DevSetupStatus install PowerShell 'would install PowerShell 7'
}
if ($env:TEST_REAL_PORTABLE -eq '1') {
    Set-Item -LiteralPath Function:\Install-DevSetupPortableRuntime -Value $script:portableInstaller
    function Add-DevSetupUserPath { param($Directory, [switch]$Prepend) }
    function Invoke-WebRequest {
        param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
        Copy-Item (Join-Path $env:FIXTURE 'runtime.zip') $OutFile
    }
}
""".replace("REAL_MODULE", module))

    def version(self, installed, latest, **metadata):
        (self.root / "version").write_text(installed)
        (self.root / "release.json").write_text(json.dumps({
            "tag_name": f"v{latest}", "draft": False, "prerelease": False, **metadata,
        }))

    def run_installer(self, *options, success=True, setup=False, real_portable=False):
        env = {
            key: value for key, value in os.environ.items()
            if key.lower() not in ("psmodulepath", "devsetup_status_log")
        }
        env.update(FIXTURE=str(self.root), NO_COLOR="1")
        env["TEST_REAL_PORTABLE"] = "1" if real_portable else "0"
        script = self.root / "setup.ps1" if setup else self.scripts / "install-powershell.ps1"
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-File",
             str(script), *options],
            env=env, capture_output=True, text=True, timeout=120, check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def snapshot(self):
        return {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

    def test_reports_installed_and_latest_without_upgrading(self):
        output = self.run_installer("-CheckUpgrades")
        self.assertIn("installed 7.6.9; latest stable 7.6.10", output)
        self.assertIn("-UpgradePowerShell", output)
        self.assertFalse((self.root / "upgrades").exists())

    def test_audit_apply_second_run_and_preserved_installation(self):
        before = self.snapshot()
        output = self.run_installer("-Upgrade", "-Audit")
        self.assertIn("would install stable 7.6.10 side-by-side", output)
        self.assertEqual(self.snapshot(), before)
        output = self.run_installer("-Upgrade")
        self.assertIn("upgraded to 7.6.10", output)
        self.assertNotIn("[update]", output)
        self.assertEqual((self.root / "version").read_text(), "7.6.9")
        before = self.snapshot()
        output = self.run_installer("-Upgrade")
        self.assertIn("no upgrade needed", output)
        self.assertNotIn("[install]", output)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.root / "upgrades").read_text().splitlines(), ["7.6.10"])

    def test_equal_and_newer_installs_are_never_downgraded(self):
        for installed in ("7.6.10", "7.7.0", "7.7.0-preview.1", "7.6.10+build"):
            with self.subTest(installed=installed):
                self.version(installed, "7.6.10")
                output = self.run_installer("-Upgrade")
                self.assertIn("no upgrade needed", output)
                self.assertFalse((self.root / "upgrades").exists())

    def test_same_version_preview_upgrades_to_stable(self):
        self.version("7.6.10-preview.1", "7.6.10")
        self.assertIn("upgraded to 7.6.10", self.run_installer("-Upgrade"))

    def test_release_errors_warn_checks_and_fail_explicit_upgrades(self):
        (self.root / "network-failure").touch()
        self.assertIn("latest stable version could not be detected",
                      self.run_installer("-CheckUpgrades"))
        self.run_installer("-Upgrade", success=False)
        self.assertFalse((self.root / "upgrades").exists())

    def test_prerelease_and_invalid_metadata_are_rejected(self):
        for latest, metadata in (("7.7.0-preview.1", {}), ("7.7.0", {"prerelease": True}),
                                 ("7.7.0", {"draft": True}), ("invalid", {})):
            with self.subTest(latest=latest, metadata=metadata):
                self.version("7.6.9", latest, **metadata)
                self.run_installer("-Upgrade", success=False)
                self.assertFalse((self.root / "upgrades").exists())

    def test_failed_or_wrong_version_upgrades_are_not_success(self):
        (self.root / "upgrade-failure").touch()
        self.assertIn("fixture upgrade failure", self.run_installer("-Upgrade", success=False))
        (self.root / "upgrade-failure").unlink()
        (self.root / "wrong-version").touch()
        self.assertIn("verification failed", self.run_installer("-Upgrade", success=False))

    def test_missing_audit_and_conflicting_flags_do_not_install(self):
        (self.root / "missing").touch()
        before = self.snapshot()
        self.assertIn("not installed", self.run_installer("-Audit", "-CheckUpgrades"))
        self.assertIn("cannot be combined",
                      self.run_installer("-Uninstall", "-Upgrade", success=False))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_installed_version_is_an_error(self):
        self.version("unreadable", "7.6.10")
        self.assertIn("Cannot detect", self.run_installer("-CheckUpgrades", success=False))

    def test_setup_readonly_modes_and_disabled_gate(self):
        before = self.snapshot()
        output = self.run_installer("-UpgradePowerShell", "-Audit", "-SkipUpgradeCheck",
                                    setup=True)
        self.assertIn("would install stable 7.6.10", output)
        self.assertIn(r"APPLY: .\setup.ps1 -UpgradePowerShell", output)
        self.assertEqual(self.snapshot(), before)
        output = self.run_installer("-UpgradePowerShell", "-CheckUpgradesOnly", setup=True)
        self.assertIn("installed 7.6.9; latest stable 7.6.10", output)
        self.assertNotIn("would install stable", output)
        self.assertEqual(self.snapshot(), before)
        (self.root / "disabled").touch()
        output = self.run_installer("-UpgradePowerShell", setup=True)
        self.assertIn("user.install.powershell is false", output)
        self.assertFalse((self.root / "upgrades").exists())

    def test_setup_applies_explicit_upgrade_when_routine_checks_are_disabled(self):
        output = self.run_installer("-UpgradePowerShell", "-SkipUpgradeCheck", setup=True)
        self.assertIn("upgraded to 7.6.10", output)
        self.assertIn("Setup complete.", output)
        output = self.run_installer("-UpgradePowerShell", "-SkipUpgradeCheck", setup=True)
        self.assertNotIn("[install]", output)

    @unittest.skipUnless(os.name == "nt", "Windows executable fixture")
    def test_real_portable_upgrade_runs_and_is_rediscovered_without_path_changes(self):
        executable = self.root / "pwsh.exe"
        quoted_executable = str(executable).replace("'", "''")
        build = self.root / "build.ps1"
        build.write_text(
            "Add-Type -TypeDefinition 'public class Fixture { "
            'public static void Main() { System.Console.WriteLine("PowerShell 7.6.10"); } '
            "}' -OutputType ConsoleApplication -OutputAssembly "
            f"'{quoted_executable}'\n"
        )
        built = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(build)],
            env={
                key: value for key, value in os.environ.items()
                if key.lower() != "psmodulepath"
            },
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        archive = self.root / "runtime.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(executable, "pwsh.exe")
        architecture = "arm64" if "ARM64" in (
            os.environ.get("PROCESSOR_ARCHITECTURE", "")
            + os.environ.get("PROCESSOR_ARCHITEW6432", "")
        ) else "x64"
        (self.root / "release.json").write_text(json.dumps({
            "tag_name": "v7.6.10", "prerelease": False, "draft": False,
            "assets": [{
                "name": f"PowerShell-7.6.10-win-{architecture}.zip",
                "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
                "browser_download_url": "https://example.test/runtime.zip",
            }],
        }))
        output = self.run_installer("-Upgrade", real_portable=True)
        installed = self.root / "runtime" / "7.6.10" / "pwsh.exe"
        reported = Path(output.strip().splitlines()[-1])
        self.assertTrue(installed.samefile(reported), output)
        self.assertEqual(installed.read_bytes(), executable.read_bytes())
        before = installed.stat().st_mtime_ns
        output = self.run_installer("-Upgrade", real_portable=True)
        self.assertIn("no upgrade needed", output)
        self.assertNotIn("[install]", output)
        self.assertEqual(installed.stat().st_mtime_ns, before)
        self.assertEqual((self.root / "version").read_text(), "7.6.9")
        self.assertFalse(list((self.root / "runtime").glob(".devsetup-*")))


@unittest.skipUnless(BASH, "Bash is required")
class BashPowerShellInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        scripts = self.root / "src" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "src" / "scripts" / "install-powershell.sh",
            scripts / "install-powershell.sh",
        )
        shutil.copyfile(ROOT / "setup.sh", self.root / "setup.sh")
        (self.root / "src" / "config.sh").write_text("""
. "$REAL_CONFIG"
devsetup_is_elevated() { return 1; }
devsetup_config() { printf '%s' "$2"; }
devsetup_config_reader() { printf '%s' "$FIXTURE_PYTHON"; }
devsetup_status() {
    printf '[%s] %s %s\\n' "$1" "$2" "$3"
    if [[ -n "${DEVSETUP_STATUS_LOG:-}" ]]; then
        printf '%s|%s|%s\\n' "$1" "$2" "$3" >> "$DEVSETUP_STATUS_LOG"
    fi
}
devsetup_activate_homebrew() { [[ ! -f "$HOME/no-brew" ]]; }
devsetup_enabled() { [[ "$1" == user.install.powershell && ! -f "$HOME/disabled" ]]; }
""")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "pwsh").write_text("""#!/usr/bin/env bash
if [[ -f "$HOME/version-failure" ]]; then echo 'fixture version failure' >&2; exit 7; fi
printf 'PowerShell %s\\n' "$(cat "$HOME/version")"
""")
        (self.bin / "python3").write_text("""#!/usr/bin/env bash
exec "$FIXTURE_PYTHON" "$@"
""")
        (self.bin / "curl").write_text("""#!/usr/bin/env bash
if [[ -f "$HOME/network-failure" ]]; then exit 7; fi
cat "$HOME/release.json"
""")
        (self.bin / "brew").write_text("""#!/usr/bin/env bash
set -eu
case "$1" in
--prefix)
    if [[ -f "$HOME/global-prefix" ]]; then
        dirname "$HOME"
    elif [[ $# -gt 1 ]]; then
        printf '%s/.linuxbrew/opt/powershell\\n' "$HOME"
    else printf '%s/.linuxbrew\\n' "$HOME"; fi ;;
list) [[ ! -f "$HOME/not-managed" ]] ;;
upgrade)
    [[ "$*" == 'upgrade --formula powershell' ]] || exit 2
    [[ "$NONINTERACTIVE" == 1 ]] || exit 2
    [[ ! -f "$HOME/upgrade-failure" ]] || exit 9
    printf 'upgrade\\n' >> "$HOME/upgrades"
    if [[ ! -f "$HOME/stale" ]]; then cp "$HOME/latest" "$HOME/version"; fi ;;
*) exit 2 ;;
esac
""")
        formula_bin = self.root / ".linuxbrew" / "opt" / "powershell" / "bin"
        formula_bin.mkdir(parents=True)
        shutil.copyfile(self.bin / "pwsh", formula_bin / "pwsh")
        self.version("7.6.9", "7.6.10")

    def version(self, installed, latest, **metadata):
        (self.root / "version").write_text(installed)
        (self.root / "latest").write_text(latest)
        (self.root / "release.json").write_text(json.dumps({
            "tag_name": f"v{latest}", "draft": False, "prerelease": False, **metadata,
        }))

    def run_installer(self, *options, success=True, setup=False):
        env = {
            **os.environ, "TEST_HOME": str(self.root), "NO_COLOR": "1",
            "FIXTURE_SCRIPT": "setup.sh" if setup else "src/scripts/install-powershell.sh",
            "REAL_CONFIG": str(ROOT / "src" / "config.sh"),
            "FIXTURE_PYTHON": sys.executable,
        }
        env.pop("DEVSETUP_STATUS_LOG", None)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            [BASH, "-c", """
if command -v cygpath >/dev/null 2>&1; then
    export HOME="$(cygpath -u "$TEST_HOME")"
    export REAL_CONFIG="$(cygpath -u "$REAL_CONFIG")"
else export HOME="$TEST_HOME"; fi
export PATH="$HOME/bin:$PATH"
chmod +x "$HOME/bin/"* "$HOME/.linuxbrew/opt/powershell/bin/pwsh"
uname() { echo Linux; }
export -f uname
bash "$FIXTURE_SCRIPT" "$@"
""", "fixture", *options],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=120, check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_version_check_does_not_pollute_print_path(self):
        result = self.run_installer("--check-upgrades", "--print-path")
        self.assertTrue(result.stdout.strip().endswith("/bin/pwsh"), result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertIn("installed 7.6.9; latest stable 7.6.10", result.stderr)
        self.assertFalse((self.root / "upgrades").exists())

    def test_audit_apply_and_idempotent_second_run(self):
        result = self.run_installer("--upgrade", "--audit")
        self.assertIn("would upgrade", result.stderr)
        self.assertFalse((self.root / "upgrades").exists())
        self.assertEqual((self.root / "version").read_text(), "7.6.9")
        result = self.run_installer("--upgrade", "--print-path")
        self.assertIn("upgraded to 7.6.10", result.stderr)
        self.assertNotIn("[update]", result.stderr)
        self.assertTrue(result.stdout.strip().endswith("/opt/powershell/bin/pwsh"))
        result = self.run_installer("--upgrade")
        self.assertIn("no upgrade needed", result.stderr)
        self.assertNotIn("[install]", result.stderr)
        self.assertEqual((self.root / "upgrades").read_text().splitlines(), ["upgrade"])

    def test_no_downgrades_and_same_version_preview_upgrades(self):
        for installed in ("7.6.10", "7.7.0", "7.7.0-preview.1", "7.6.10+build-hash"):
            with self.subTest(installed=installed):
                self.version(installed, "7.6.10")
                self.assertIn("no upgrade needed", self.run_installer("--upgrade").stderr)
                self.assertFalse((self.root / "upgrades").exists())
        self.version("7.6.10-preview.1", "7.6.10")
        self.assertIn("upgraded to 7.6.10", self.run_installer("--upgrade").stderr)

    def test_unmanaged_system_and_unavailable_homebrew_are_not_modified(self):
        for marker in ("not-managed", "global-prefix", "no-brew"):
            with self.subTest(marker=marker):
                path = self.root / marker
                path.touch()
                result = self.run_installer("--upgrade", success=False)
                self.assertIn("[warn]", result.stderr)
                self.assertFalse((self.root / "upgrades").exists())
                path.unlink()

    def test_release_and_upgrade_failures_are_not_success(self):
        (self.root / "network-failure").touch()
        self.assertIn("could not be detected",
                      self.run_installer("--check-upgrades").stderr)
        self.run_installer("--upgrade", success=False)
        (self.root / "network-failure").unlink()
        for marker in ("upgrade-failure", "stale"):
            with self.subTest(marker=marker):
                path = self.root / marker
                path.touch()
                self.run_installer("--upgrade", success=False)
                self.assertEqual((self.root / "version").read_text(), "7.6.9")
                path.unlink()

    def test_invalid_and_prerelease_metadata_are_rejected(self):
        for latest, metadata in (("7.7.0-preview.1", {}), ("7.7.0", {"prerelease": True}),
                                 ("invalid", {})):
            with self.subTest(latest=latest, metadata=metadata):
                self.version("7.6.9", latest, **metadata)
                self.run_installer("--upgrade", success=False)
                self.assertFalse((self.root / "upgrades").exists())

    def test_conflicting_flags_fail_without_mutation(self):
        result = self.run_installer("--uninstall", "--upgrade", success=False)
        self.assertIn("cannot be combined", result.stderr)
        self.assertFalse((self.root / "upgrades").exists())

    def test_setup_readonly_modes_and_disabled_gate(self):
        result = self.run_installer("--upgrade-powershell", "--audit",
                                    "--skip-upgrade-check", setup=True)
        self.assertIn("would upgrade", result.stderr)
        self.assertIn("Run this to apply them: ./setup.sh --skip-upgrade-check --upgrade-powershell", result.stdout)
        self.assertFalse((self.root / "upgrades").exists())
        result = self.run_installer("--upgrade-powershell", "--check-upgrades-only",
                                    "--audit", setup=True)
        self.assertIn("latest stable 7.6.10", result.stderr)
        self.assertNotIn("would upgrade", result.stderr)
        self.assertFalse((self.root / "upgrades").exists())
        (self.root / "disabled").touch()
        result = self.run_installer("--upgrade-powershell", "--audit", setup=True)
        self.assertIn("user.install.powershell is false", result.stdout)
        self.assertFalse((self.root / "upgrades").exists())

    def test_setup_without_upgrade_completes_audit_and_repeat_runs(self):
        for options in (("--audit", "--skip-upgrade-check"),
                        ("--skip-upgrade-check",), ("--skip-upgrade-check",)):
            with self.subTest(options=options):
                result = self.run_installer(*options, setup=True)
                self.assertIn("Summary:", result.stdout)
                self.assertIn("installed 7.6.9", result.stderr)
                self.assertNotIn("[install]", result.stderr)
                self.assertNotIn("[warn]", result.stderr)
                self.assertEqual((self.root / "version").read_text(), "7.6.9")
                self.assertFalse((self.root / "upgrades").exists())
                if "--audit" in options:
                    self.assertIn("Audit complete.", result.stdout)
                    self.assertIn("Recommendation:", result.stdout)
                else:
                    self.assertIn("Setup complete.", result.stdout)

    def test_setup_version_failure_does_not_report_completion(self):
        (self.root / "version-failure").touch()
        for options in (("--audit", "--skip-upgrade-check"), ("--skip-upgrade-check",)):
            with self.subTest(options=options):
                result = self.run_installer(*options, setup=True, success=False)
                self.assertIn("Cannot detect the PowerShell version", result.stderr)
                self.assertNotIn("Summary:", result.stdout)
                self.assertNotIn("Setup complete.", result.stdout)


if __name__ == "__main__":
    unittest.main()
