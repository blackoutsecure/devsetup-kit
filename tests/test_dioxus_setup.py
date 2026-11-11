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


class DioxusInstallerTests(unittest.TestCase):
    def fixture(self, root):
        scripts = root / "src" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("setup.sh", "setup.ps1"):
            shutil.copyfile(ROOT / name, root / name)
        for extension in ("sh", "ps1"):
            shutil.copyfile(
                ROOT / "src" / "scripts" / f"install-dioxus.{extension}",
                scripts / f"install-dioxus.{extension}",
            )
        config = json.loads((ROOT / "config" / "dev-setup.config.json").read_text())
        config["user"]["install"] = {name: False for name in config["user"]["install"]}
        config["user"]["install"]["dioxus"] = True
        config["user"]["checkUpgrades"] = False
        (root / "config").mkdir()
        (root / "config" / "dev-setup.config.json").write_text(json.dumps(config))
        (root / "dx-version").write_text("0.7.0")
        (root / "metadata.json").write_text(json.dumps({"crate": {"max_stable_version": "0.7.2"}}))
        (root / "cargo home" / "bin").mkdir(parents=True)
        return scripts, config

    def exercise(self, root, config, run, flags, profile, cargo, binary):
        config_path = root / "config" / "dev-setup.config.json"
        audit = run(flags["audit"])
        self.assertIn("would install dioxus-cli", audit)
        self.assertFalse((root / "calls").exists())
        self.assertFalse(profile.exists())
        for marker, message in (("cargo-failure", "fixture cargo failure"),
                                ("silent-install", "dx was not found")):
            (root / marker).touch()
            try:
                self.assertIn(message, run(success=False))
            finally:
                (root / marker).unlink()
        output = run()
        self.assertIn("Dioxus CLI", output)
        self.assertTrue(binary.is_file())
        calls = (root / "calls").read_text()
        self.assertIn("install --locked --bin dx --root", calls)
        self.assertFalse((root / "wrong-root").exists())
        before = profile.read_bytes()
        second = run()
        self.assertNotIn("[install]", second)
        self.assertNotIn("[warn]", second)
        self.assertEqual((root / "calls").read_text(), calls)
        self.assertEqual(profile.read_bytes(), before)

        for installed, update in (("0.7.0", True), ("0.8.0", False), ("0.7.2-rc.1", True)):
            (root / "dx-version").write_text(installed)
            output = run(flags["audit"], flags["check"])
            self.assertEqual("[update]" in output, update, output)
            self.assertEqual(profile.read_bytes(), before)
            self.assertEqual((root / "calls").read_text(), calls)
        (root / "dx-version").write_text("0.7.0")
        output = run(flags["check_only"], setup=True)
        self.assertIn("[update]", output)
        self.assertIn("Summary:", output)
        self.assertEqual((root / "calls").read_text(), calls)
        (root / "network-failure").touch()
        try:
            self.assertIn("fixture network failure",
                          run(flags["audit"], flags["check"], success=False))
        finally:
            (root / "network-failure").unlink()
        (root / "metadata.json").write_text('{"crate":{"max_stable_version":"invalid"}}')
        self.assertIn("Invalid latest stable", run(flags["audit"], flags["check"], success=False))
        (root / "metadata.json").write_text('{"crate":{"max_stable_version":"0.7.2"}}')
        (root / "version-failure").touch()
        try:
            self.assertIn("fixture version failure", run(flags["audit"], success=False))
        finally:
            (root / "version-failure").unlink()
        for setup in (False, True):
            self.assertIn("preserved", run(flags["uninstall"], flags["audit"], setup=setup))
            self.assertTrue(binary.exists())

        config["user"]["install"]["dioxus"] = False
        config["advanced"]["dioxus"]["cargoPackage"] = "--invalid"
        config_path.write_text(json.dumps(config))
        for options in ((), (flags["check_only"],), (flags["uninstall"],)):
            self.assertIn("user.install.dioxus is false", run(*options, setup=True))
        self.assertEqual((root / "calls").read_text(), calls)
        config["user"]["install"]["dioxus"] = True
        config_path.write_text(json.dumps(config))
        self.assertIn("Invalid Dioxus Cargo package", run(success=False))
        config["advanced"]["dioxus"]["cargoPackage"] = "dioxus-cli"
        config_path.write_text(json.dumps(config))
        cargo.unlink()
        self.assertIn("Dioxus CLI", run(flags["audit"]))
        binary.unlink()
        self.assertIn("Cargo is unavailable", run(flags["audit"]))
        self.assertIn("requires stable Rust and Cargo", run(success=False))
        config["user"]["install"]["rust"] = True
        config_path.write_text(json.dumps(config))
        self.assertIn("would install dioxus-cli", run(flags["audit"]))

    @unittest.skipUnless(BASH and os.name != "nt", "macOS/Linux Bash is required")
    def test_bash_audit_install_idempotence_upgrade_failures_and_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts, config = self.fixture(root)
            module = str(ROOT / "src" / "config.sh")
            (root / "src" / "config.sh").write_text(
                '. "$REAL_MODULE"\n'
                'devsetup_is_elevated() { return 1; }\n'
                'devsetup_homebrew_path() { return 1; }\n'
                'command() {\n'
                '    if [[ "$1" == -v && ( "$2" == cargo || "$2" == dx ) ]]; then return 1; fi\n'
                '    builtin command "$@"\n'
                '}\n'
            )
            cargo = root / "cargo home" / "bin" / "cargo"
            cargo.write_text(r"""#!/usr/bin/env bash
set -euo pipefail
[[ "$RUSTUP_TOOLCHAIN" == stable && "$RUSTUP_AUTO_INSTALL" == 0 ]]
[[ "$#" -eq 7 && "$1" == install && "$2" == --locked && "$3" == --bin && "$4" == dx ]]
[[ "$5" == --root && "$6" == "$CARGO_HOME" && "$7" == dioxus-cli ]]
printf '%s\n' "$*" >> "$TEST_ROOT/calls"
if [[ -f "$TEST_ROOT/cargo-failure" ]]; then echo 'fixture cargo failure' >&2; exit 7; fi
if [[ -f "$TEST_ROOT/silent-install" ]]; then exit 0; fi
cat > "$CARGO_HOME/bin/dx" <<'DX'
#!/usr/bin/env bash
if [[ -f "$TEST_ROOT/version-failure" ]]; then echo 'fixture version failure' >&2; exit 9; fi
printf 'dioxus %s\n' "$(cat "$TEST_ROOT/dx-version")"
DX
chmod +x "$CARGO_HOME/bin/dx"
""")
            cargo.chmod(0o755)
            (root / "tools").mkdir()
            curl = root / "tools" / "curl"
            curl.write_text(r"""#!/usr/bin/env bash
set -eu
[[ " $* " == *" --max-time 30 "* ]]
if [[ -f "$TEST_ROOT/network-failure" ]]; then echo 'fixture network failure' >&2; exit 22; fi
cat "$TEST_ROOT/metadata.json"
""")
            curl.chmod(0o755)
            env = {
                **os.environ, "HOME": str(root), "TEST_ROOT": str(root),
                "CARGO_HOME": str(root / "cargo home"),
                "CARGO_INSTALL_ROOT": str(root / "wrong-root"),
                "RUSTUP_TOOLCHAIN": "preserve-project-pin", "RUSTUP_AUTO_INSTALL": "1",
                "REAL_MODULE": module, "NO_COLOR": "1",
                "DEVSETUP_CONFIG_FILE": str(root / "config" / "dev-setup.config.json"),
                "DEVSETUP_STATUS_LOG": str(root / "status.log"),
                "PATH": os.pathsep.join((str(root / "tools"), str(Path(sys.executable).parent),
                                        os.environ.get("PATH", ""))),
            }

            def run(*options, success=True, setup=False):
                script = root / "setup.sh" if setup else scripts / "install-dioxus.sh"
                result = subprocess.run(
                    [BASH, str(script), *options], env=env, cwd=root,
                    capture_output=True, text=True, timeout=120, check=False,
                )
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result.stdout + result.stderr

            profile = root / (".zprofile" if sys.platform == "darwin" else ".profile")
            self.exercise(root, config, run, {
                "audit": "--audit", "check": "--check-upgrades",
                "check_only": "--check-upgrades-only", "uninstall": "--uninstall",
            }, profile, cargo, root / "cargo home" / "bin" / "dx")

    @unittest.skipUnless(POWERSHELL, "Windows PowerShell is required")
    def test_windows_audit_install_idempotence_upgrade_failures_and_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts, config = self.fixture(root)
            module = str(ROOT / "src" / "config.ps1").replace("'", "''")
            (root / "src" / "config.ps1").write_text(r"""
. 'REAL_MODULE'
function Get-DevSetupConfig {
    Get-Content (Join-Path $env:TEST_ROOT 'config\dev-setup.config.json') -Raw | ConvertFrom-Json
}
function Find-DevSetupRustExecutable {
    param($Name)
    $path = if ($Name -eq 'cargo') { Join-Path $env:TEST_ROOT 'cargo.ps1' }
        else { Join-Path $env:CARGO_HOME "bin\$Name.exe" }
    if (Test-Path $path) { return $path }
}
function Add-DevSetupUserPath {
    param($Directory, [switch]$Audit)
    $path = Join-Path $env:TEST_ROOT 'user-path'
    if ($Audit) { Write-DevSetupStatus install PATH "would add $Directory" }
    elseif (-not (Test-Path $path)) {
        Set-Content $path $Directory
        Write-DevSetupStatus install PATH "added $Directory"
    }
}
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    if ($TimeoutSec -ne 30) { throw 'Upgrade lookup must be bounded' }
    if (Test-Path (Join-Path $env:TEST_ROOT 'network-failure')) { throw 'fixture network failure' }
    Get-Content (Join-Path $env:TEST_ROOT 'metadata.json') -Raw | ConvertFrom-Json
}
""".replace("REAL_MODULE", module))
            cargo = root / "cargo.ps1"
            cargo.write_text(r"""
if ($env:RUSTUP_TOOLCHAIN -ne 'stable' -or $env:RUSTUP_AUTO_INSTALL -ne '0') { throw 'Unsafe toolchain inspection' }
if ($args.Count -ne 7 -or ($args[0..4] -join ' ') -ne 'install --locked --bin dx --root' -or $args[5] -ne $env:CARGO_HOME) { throw 'Unexpected Cargo arguments' }
Add-Content (Join-Path $env:TEST_ROOT 'calls') ($args -join ' ')
if (Test-Path (Join-Path $env:TEST_ROOT 'cargo-failure')) { throw 'fixture cargo failure' }
if (-not (Test-Path (Join-Path $env:TEST_ROOT 'silent-install'))) {
    Copy-Item (Join-Path $env:TEST_ROOT 'ready.exe') (Join-Path $env:CARGO_HOME 'bin\dx.exe')
}
exit 0
""")
            env = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
            env.update({
                "TEST_ROOT": str(root), "CARGO_HOME": str(root / "cargo home"),
                "CARGO_INSTALL_ROOT": str(root / "wrong-root"), "NO_COLOR": "1",
                "RUSTUP_TOOLCHAIN": "preserve-project-pin", "RUSTUP_AUTO_INSTALL": "1",
                "DEVSETUP_STATUS_LOG": str(root / "status.log"),
            })
            build = root / "build.ps1"
            build.write_text(r"""
Add-Type -TypeDefinition 'public class Dx { public static int Main() { var root = System.Environment.GetEnvironmentVariable("TEST_ROOT"); if (System.IO.File.Exists(System.IO.Path.Combine(root, "version-failure"))) { System.Console.Error.WriteLine("fixture version failure"); return 9; } System.Console.WriteLine("dioxus " + System.IO.File.ReadAllText(System.IO.Path.Combine(root, "dx-version")).Trim()); return 0; } }' -OutputAssembly (Join-Path $env:TEST_ROOT 'ready.exe') -OutputType ConsoleApplication
""")
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(build)],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            def run(*options, success=True, setup=False):
                script = root / "setup.ps1" if setup else scripts / "install-dioxus.ps1"
                result = subprocess.run(
                    [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(script), *options],
                    env=env, cwd=root, capture_output=True, text=True, timeout=120, check=False,
                )
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result.stdout + result.stderr

            self.exercise(root, config, run, {
                "audit": "-Audit", "check": "-CheckUpgrades",
                "check_only": "-CheckUpgradesOnly", "uninstall": "-Uninstall",
            }, root / "user-path", cargo, root / "cargo home" / "bin" / "dx.exe")


if __name__ == "__main__":
    unittest.main()
