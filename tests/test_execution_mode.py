import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "execution_mode_vscode", ROOT / "src" / "configure-vscode.py"
)
assert SPEC is not None and SPEC.loader is not None
VSCODE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VSCODE)
POWERSHELL = shutil.which("powershell") if os.name == "nt" else shutil.which("pwsh")
BASH = shutil.which("bash")
if os.name == "nt":
    git = shutil.which("git")
    git_bash = Path(git).parent.parent / "bin" / "bash.exe" if git else None
    BASH = str(git_bash) if git_bash and git_bash.is_file() else None


class PythonExecutionModeTests(unittest.TestCase):
    def test_standard_user_is_default_and_environment_is_not_persisted(self):
        for value in ("", "0", "1"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"DEVSETUP_ADMIN_MODE": value}
            ), patch.object(VSCODE, "is_elevated", return_value=False), patch.object(
                VSCODE, "status"
            ) as status:
                VSCODE.enforce_execution_mode(False)
                self.assertEqual(os.environ["DEVSETUP_ADMIN_MODE"], value)
                status.assert_not_called()

    def test_elevated_writes_require_exact_opt_in(self):
        for value in ("", "0"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"DEVSETUP_ADMIN_MODE": value}
            ), patch.object(VSCODE, "is_elevated", return_value=True):
                with self.assertRaisesRegex(SystemExit, "standard, non-admin shell"):
                    VSCODE.enforce_execution_mode(False)
        with patch.dict(os.environ, {"DEVSETUP_ADMIN_MODE": "1"}), patch.object(
            VSCODE, "is_elevated", return_value=True
        ), patch.object(VSCODE, "status") as status:
            VSCODE.enforce_execution_mode(False)
            self.assertIn("explicit admin mode enabled", status.call_args.args[2])

    def test_elevated_audits_are_allowed_without_admin_mode(self):
        with patch.dict(os.environ, {"DEVSETUP_ADMIN_MODE": "0"}), patch.object(
            VSCODE, "is_elevated", return_value=True
        ), patch.object(VSCODE, "status") as status:
            VSCODE.enforce_execution_mode(True)
            self.assertIn("read-only inspection", status.call_args.args[2])

    def test_invalid_opt_in_is_not_treated_as_truthy(self):
        for value in ("true", "false", "yes", "2", " 1"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"DEVSETUP_ADMIN_MODE": value}
            ):
                with self.assertRaisesRegex(SystemExit, "must be 0"):
                    VSCODE.enforce_execution_mode(True)

    def test_main_rejects_elevated_process_before_reading_or_writing_profiles(self):
        for options in ([], ["--copilot-chat-migration"],
                        ["--agent-customization-migration", "stable"]):
            with self.subTest(options=options), patch.dict(
                os.environ, {"DEVSETUP_ADMIN_MODE": "0"}
            ), patch.object(VSCODE, "is_elevated", return_value=True), patch.object(
                sys, "argv", ["configure-vscode.py", *options]
            ), patch.object(VSCODE, "load_json") as load, patch.object(
                VSCODE, "run_cli"
            ) as cli:
                with self.assertRaisesRegex(SystemExit, "standard, non-admin shell"):
                    VSCODE.main()
                load.assert_not_called()
                cli.assert_not_called()


class ExecutionModeCoverageTests(unittest.TestCase):
    def test_every_shell_entrypoint_checks_execution_mode(self):
        for extension, guard, roots in (
            ("ps1", "Assert-DevSetupExecutionMode",
             ("setup.ps1", "manage-gpg-key.ps1", "setup-wsl.ps1")),
            ("sh", "devsetup_assert_execution_mode",
             ("setup.sh", "manage-gpg-key.sh")),
        ):
            scripts = [*ROOT.joinpath("src", "scripts").glob(f"*.{extension}")]
            scripts.extend(ROOT / name for name in roots)
            for script in scripts:
                with self.subTest(script=script.name):
                    self.assertIn(guard, script.read_text())


def child_environment(root):
    env = {
        key: value for key, value in os.environ.items()
        if key.lower() not in ("psmodulepath", "devsetup_status_log", "devsetup_admin_mode")
    }
    env.update(FIXTURE=str(root), DEVSETUP_ADMIN_MODE="0", NO_COLOR="1")
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


@unittest.skipUnless(POWERSHELL, "PowerShell is required")
class PowerShellExecutionModeTests(unittest.TestCase):
    def run_harness(self, root, content):
        harness = root / "test.ps1"
        module = str(ROOT / "src" / "config.ps1").replace("'", "''")
        harness.write_text(content.replace("REAL_MODULE", module))
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-OutputFormat", "Text",
             "-File", str(harness)],
            env=child_environment(root), capture_output=True, text=True,
            timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_standard_elevated_audit_admin_and_invalid_mode_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self.run_harness(Path(temporary), r"""
$ErrorActionPreference = 'Stop'
. 'REAL_MODULE'
$global:elevated = $false
function Test-DevSetupElevated { return $global:elevated }
foreach ($mode in @('', '0', '1')) {
    $env:DEVSETUP_ADMIN_MODE = $mode
    Assert-DevSetupExecutionMode
}
$global:elevated = $true
$env:DEVSETUP_ADMIN_MODE = '0'
try {
    Assert-DevSetupExecutionMode
    throw 'Unexpected elevated write permission'
} catch {
    if ($_.Exception.Message -notlike '*standard, non-admin shell*') { throw }
}
Assert-DevSetupExecutionMode -ReadOnly
$env:DEVSETUP_ADMIN_MODE = '1'
Assert-DevSetupExecutionMode
foreach ($mode in @('true', 'false', 'yes', '2', ' 1')) {
    $env:DEVSETUP_ADMIN_MODE = $mode
    try {
        Assert-DevSetupExecutionMode -ReadOnly
        throw 'Unexpected invalid opt-in permission'
    } catch {
        if ($_.Exception.Message -notlike '*must be 0*') { throw }
    }
}
Write-Host 'PASS: execution-mode matrix'
""")
            self.assertIn("PASS: execution-mode matrix", output)
            self.assertIn("explicit admin mode enabled", output)
            self.assertIn("read-only inspection", output)

    def test_all_windows_applications_reject_inherited_elevation_before_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "src" / "scripts"
            scripts.mkdir(parents=True)
            for source in (ROOT / "src" / "scripts").glob("*.ps1"):
                shutil.copyfile(source, scripts / source.name)
            for name in ("setup.ps1", "manage-gpg-key.ps1", "setup-wsl.ps1"):
                shutil.copyfile(ROOT / name, root / name)
            module = str(ROOT / "src" / "config.ps1").replace("'", "''")
            (root / "src" / "config.ps1").write_text(
                f". '{module}'\n"
                "function Test-DevSetupElevated { return $true }\n"
                "function Get-DevSetupConfig { throw 'Configuration reached before guard' }\n"
            )
            output = self.run_harness(root, r"""
$ErrorActionPreference = 'Stop'
$scripts = @(Get-ChildItem (Join-Path $PSScriptRoot 'src\scripts') -Filter '*.ps1')
$scripts += Get-Item (Join-Path $PSScriptRoot 'setup.ps1')
$scripts += Get-Item (Join-Path $PSScriptRoot 'manage-gpg-key.ps1')
$scripts += Get-Item (Join-Path $PSScriptRoot 'setup-wsl.ps1')
foreach ($script in $scripts) {
    try {
        if ($script.Name -eq 'setup-wsl.ps1') { & $script.FullName -Configure -UserName developer }
        else { & $script.FullName }
        throw "Unexpected execution: $($script.Name)"
    } catch {
        if ($_.Exception.Message -notlike '*standard, non-admin shell*') { throw }
    }
}
try {
    & (Join-Path $PSScriptRoot 'setup.ps1') -Uninstall -CheckUpgradesOnly
    throw 'Uninstall was incorrectly treated as read-only'
} catch {
    if ($_.Exception.Message -notlike '*standard, non-admin shell*') { throw }
}
Write-Host "PASS: $($scripts.Count) entrypoints blocked inherited elevation"
""")
            self.assertIn("PASS: 17 entrypoints", output)

    def test_admin_opt_in_does_not_widen_winget_install_or_uninstall_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tool.ps1").write_text("'fixture 1.0.0'\n")
            output = self.run_harness(root, r"""
$ErrorActionPreference = 'Stop'
. 'REAL_MODULE'
function Test-DevSetupElevated { return $true }
$env:DEVSETUP_ADMIN_MODE = '1'
Assert-DevSetupExecutionMode
$global:installed = $false
$global:calls = @()
function winget.exe {
    $global:calls += ($args -join ' ')
    $global:installed = $true
    $global:LASTEXITCODE = 0
}
function Update-DevSetupSessionPath {}
$find = { if ($global:installed) { Join-Path $PSScriptRoot 'tool.ps1' } }
$null = Install-DevSetupWingetTool -Component fixture -PackageId fixture -Find $find -ManualInstallHint fixture
Uninstall-DevSetupWingetTool -Component fixture -PackageId fixture
if ($global:calls.Count -ne 2) { throw 'Expected one install and one uninstall' }
foreach ($call in $global:calls) {
    if ($call -notlike '*--scope user*' -or $call -notlike '*--disable-interactivity*' -or $call -like '*machine*') {
        throw "Unexpected scope: $call"
    }
}
Write-Host 'PASS: admin opt-in preserved user scope'
""")
            self.assertIn("PASS: admin opt-in preserved user scope", output)


@unittest.skipUnless(BASH, "Bash is required")
class BashExecutionModeTests(unittest.TestCase):
    def run_harness(self, root, content):
        (root / "bin").mkdir(exist_ok=True)
        (root / "bin" / "python3").write_text('#!/usr/bin/env bash\nexec python "$@"\n')
        env = child_environment(root)
        env["REAL_CONFIG"] = str(ROOT / "src" / "config.sh")
        setup = r"""
set -euo pipefail
if command -v cygpath >/dev/null 2>&1; then
    export HOME="$(cygpath -u "$FIXTURE")"
    export REAL_CONFIG="$(cygpath -u "$REAL_CONFIG")"
else export HOME="$FIXTURE"; fi
export PATH="$HOME/bin:$PATH"
chmod +x "$HOME/bin/python3"
uname() { echo Linux; }
export -f uname
"""
        result = subprocess.run(
            [BASH, "-c", setup + content], cwd=root, env=env,
            capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_standard_root_audit_admin_and_invalid_mode_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self.run_harness(Path(temporary), r"""
. "$REAL_CONFIG"
elevated=0
devsetup_is_elevated() { [[ "$elevated" -eq 1 ]]; }
for mode in '' 0 1; do
    export DEVSETUP_ADMIN_MODE="$mode"
    devsetup_assert_execution_mode 0
done
elevated=1
export DEVSETUP_ADMIN_MODE=0
if devsetup_assert_execution_mode 0; then exit 1; fi
devsetup_assert_execution_mode 1
export DEVSETUP_ADMIN_MODE=1
devsetup_assert_execution_mode 0
for mode in true false yes 2 ' 1'; do
    export DEVSETUP_ADMIN_MODE="$mode"
    if devsetup_assert_execution_mode 1; then exit 1; fi
done
echo 'PASS: execution-mode matrix'
""")
            self.assertIn("PASS: execution-mode matrix", output)

    def test_every_unix_application_rejects_root_before_tool_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "src" / "scripts"
            scripts.mkdir(parents=True)
            for source in (ROOT / "src" / "scripts").glob("*.sh"):
                shutil.copyfile(source, scripts / source.name)
            for name in ("setup.sh", "manage-gpg-key.sh"):
                shutil.copyfile(ROOT / name, root / name)
            (root / "src" / "config.sh").write_text(r"""
. "$REAL_CONFIG"
devsetup_is_elevated() { return 0; }
devsetup_config() { printf forbidden; touch "$HOME/unexpected"; }
""")
            output = self.run_harness(root, r"""
uname() { echo Linux; }
export -f uname
count=0
for script in src/scripts/*.sh setup.sh manage-gpg-key.sh; do
    if output="$(bash "$script" 2>&1)"; then
        printf 'Unexpected execution: %s\n%s\n' "$script" "$output" >&2
        exit 1
    fi
    [[ "$output" == *'standard, non-root shell'* ]] || { printf '%s\n' "$output" >&2; exit 1; }
    count=$((count + 1))
done
if output="$(bash setup.sh --uninstall --check-upgrades-only 2>&1)"; then exit 1; fi
[[ "$output" == *'standard, non-root shell'* ]]
[[ ! -f "$HOME/unexpected" ]]
printf 'PASS: %s entrypoints blocked root\n' "$count"
""")
            self.assertIn("PASS: 17 entrypoints", output)

    def test_homebrew_shared_prefix_requires_opt_in_but_root_is_never_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self.run_harness(Path(temporary), r"""
. "$REAL_CONFIG"
elevated=0
devsetup_is_elevated() { [[ "$elevated" -eq 1 ]]; }
fixture_prefix="$HOME/.linuxbrew"
mkdir -p "$fixture_prefix"
brew() { printf '%s\n' "$fixture_prefix"; }
devsetup_assert_homebrew_write
fixture_prefix="$(dirname "$HOME")"
if devsetup_assert_homebrew_write; then exit 1; fi
export DEVSETUP_ADMIN_MODE=1
devsetup_assert_homebrew_write
elevated=1
if devsetup_assert_homebrew_write; then exit 1; fi
if devsetup_ensure_homebrew; then exit 1; fi
echo 'PASS: shared prefix opt-in and root protection'
""")
            self.assertIn("PASS: shared prefix opt-in and root protection", output)

    def test_homebrew_audit_apply_second_run_and_formula_only_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = self.run_harness(root, r"""
. "$REAL_CONFIG"
devsetup_is_elevated() { return 1; }
devsetup_activate_homebrew() { return 0; }
mkdir -p "$HOME/.linuxbrew"
brew() {
    if [[ "$1" == --prefix ]]; then printf '%s/.linuxbrew\n' "$HOME"; return; fi
    [[ "$*" == 'install --formula fixture' && "$NONINTERACTIVE" == 1 ]]
    echo install >> "$HOME/calls"
    printf '#!/usr/bin/env bash\necho fixture-1.0\n' > "$HOME/bin/devsetup-fixture-tool"
    chmod +x "$HOME/bin/devsetup-fixture-tool"
}
devsetup_install_via_homebrew fixture fixture devsetup-fixture-tool fixture 1
[[ ! -f "$HOME/calls" ]]
first="$(devsetup_install_via_homebrew fixture fixture devsetup-fixture-tool fixture 0 1)"
second="$(devsetup_install_via_homebrew fixture fixture devsetup-fixture-tool fixture 0 1)"
[[ "$first" == "$HOME/bin/devsetup-fixture-tool" && "$second" == "$first" ]]
[[ "$(wc -l < "$HOME/calls")" -eq 1 ]]
echo 'PASS: formula-only audit, apply, second run'
""")
            self.assertIn("PASS: formula-only audit, apply, second run", output)
            self.assertEqual((root / "calls").read_text().splitlines(), ["install"])


if __name__ == "__main__":
    unittest.main()
