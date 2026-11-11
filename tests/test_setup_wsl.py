import base64
import shutil
import subprocess
import unittest
from pathlib import Path


PWSH = shutil.which("pwsh")
SCRIPT = Path(__file__).resolve().parents[1] / "setup-wsl.ps1"


@unittest.skipUnless(PWSH, "PowerShell is required for mocked WSL integration tests")
class WslSafetyTests(unittest.TestCase):
    def run_setup(self, options, current_user="root"):
        harness = r"""
$ErrorActionPreference = 'Stop'
$global:currentUser = 'CURRENT_USER'
function global:wsl.exe {
    $global:LASTEXITCODE = 0
    $a = @($args)
    Write-Host "CALL $($a -join ' ')"
    if ($a -contains '--list') { 'TestDistro'; return }
    if ($a -contains 'whoami') { $global:currentUser; return }
    if ($a -contains 'getent') {
        $name = $a[-1]
        "${name}:x:1000:1000::/home/${name}:/bin/bash"
        return
    }
    if ($a -contains 'id') {
        if ($global:currentUser -eq 'root') { '0' } else { '1000' }
        return
    }
    if ($a -contains '--terminate') { $global:currentUser = 'developer'; return }
    if ($a -contains '--shutdown') { throw 'Global shutdown is forbidden' }
    if ($a -contains 'bash') {
        $content = $input | Out-String
        Write-Host "SCRIPT $content"
        return
    }
    if ($a -contains 'sudo') { $global:LASTEXITCODE = 1; return }
}
& 'SCRIPT_PATH' OPTIONS
"""
        harness = (
            harness.replace("CURRENT_USER", current_user)
            .replace("SCRIPT_PATH", str(SCRIPT).replace("'", "''"))
            .replace("OPTIONS", options)
        )
        encoded = base64.b64encode(harness.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_configure_audit_is_read_only(self):
        result = self.run_setup("-Audit -Configure -UserName developer -Distribution TestDistro")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SCRIPT ", result.stdout)
        self.assertNotIn("CALL --terminate", result.stdout)
        self.assertIn("would configure", result.stdout)

    def test_configure_does_not_restart_or_grant_sudo_by_default(self):
        result = self.run_setup("-Configure -UserName developer -Distribution TestDistro")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SCRIPT ", result.stdout)
        self.assertIn("restart pending", result.stdout)
        self.assertNotIn("NOPASSWD", result.stdout)
        self.assertNotIn("--terminate", result.stdout)
        self.assertNotIn("--shutdown", result.stdout)

    def test_non_root_user_does_not_require_passwordless_sudo(self):
        result = self.run_setup("-Audit", current_user="developer")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("starts as developer", result.stdout)
        self.assertNotIn("sudo -n", result.stdout)

    def test_restart_override_targets_only_named_distribution(self):
        result = self.run_setup(
            "-Configure -UserName developer -Distribution TestDistro -RestartDistribution"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CALL --terminate TestDistro", result.stdout)
        self.assertIn("starts as developer", result.stdout)
        self.assertNotIn("--shutdown", result.stdout)

    def test_restart_override_requires_named_distribution_before_any_writes(self):
        result = self.run_setup("-Configure -UserName developer -RestartDistribution")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SCRIPT ", result.stdout)

    def test_sudo_is_separate_explicit_opt_in(self):
        result = self.run_setup(
            "-Configure -UserName developer -Distribution TestDistro -EnablePasswordlessSudo"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOPASSWD", result.stdout)
        self.assertIn("restart pending", result.stdout)

    def test_root_cannot_be_selected_as_default_user(self):
        result = self.run_setup("-Configure -UserName root -Distribution TestDistro")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SCRIPT ", result.stdout)


if __name__ == "__main__":
    unittest.main()
