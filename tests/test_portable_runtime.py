import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


PWSH = shutil.which("pwsh")
MODULE = Path(__file__).resolve().parents[1] / "src" / "config.ps1"


@unittest.skipUnless(PWSH and os.name == "nt", "Windows PowerShell runtime test")
class PortableRuntimeTests(unittest.TestCase):
    def run_install(self, tool, *, bad_hash=False, existing=False, outside_home=False, versioned=False):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "fixture.zip"
            exe_name = {
                "node": "node.exe", "powershell": "pwsh.exe", "githubCli": "bin/gh.exe",
            }[tool]
            architecture = (
                "arm64"
                if "ARM64" in (
                    os.environ.get("PROCESSOR_ARCHITECTURE", "")
                    + os.environ.get("PROCESSOR_ARCHITEW6432", "")
                )
                else "x64"
            )
            archive_root = f"node-v24.0.0-win-{architecture}/" if tool == "node" else ""
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(archive_root + exe_name, b"test runtime fixture")
            digest = "0" * 64 if bad_hash else hashlib.sha256(archive.read_bytes()).hexdigest()
            destination = root / "runtime"
            if existing or versioned:
                destination.mkdir()
                (destination / "keep.txt").write_text("preserve")
            install_dir = root.parent / "outside-devsetup-test" if outside_home else destination
            harness = r"""
$ErrorActionPreference = 'Stop'
. 'MODULE_PATH'
$env:USERPROFILE = 'USER_HOME'
$global:metadataCalls = 0
function Add-DevSetupUserPath { param($Directory, [switch]$Prepend); Write-Host "PATH $Directory" }
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    $global:metadataCalls++
    if ($Uri -like '*index.json') {
        return [pscustomobject]@{ version='v24.0.0'; lts='test'; files=@('win-ARCH-zip') }
    }
    if ($Uri -like '*repos/cli/cli/*') {
        return [pscustomobject]@{
            tag_name='v2.103.2'
            assets=@([pscustomobject]@{
                name='gh_2.103.2_windows_GHARCH.zip'
                digest='sha256:DIGEST'
                browser_download_url='https://example.test/runtime.zip'
            })
        }
    }
    return [pscustomobject]@{
        tag_name='v7.6.0'
        assets=@([pscustomobject]@{
            name='PowerShell-7.6.0-win-ARCH.zip'
            digest='sha256:DIGEST'
            browser_download_url='https://example.test/runtime.zip'
        })
    }
}
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri -like '*SHASUMS256.txt') {
        return [pscustomobject]@{Content='DIGEST  node-v24.0.0-win-ARCH.zip'}
    }
    Copy-Item 'ARCHIVE_PATH' $OutFile
}
$config = [pscustomobject]@{advanced=[pscustomobject]@{TOOL=[pscustomobject]@{portableInstallDir='INSTALL_DIR'}}}
$options = @{}
if (VERSIONED) {
    $options.InstallDirectory = Join-Path 'INSTALL_DIR' '7.6.0'
    $options.ReleaseMetadata = Invoke-RestMethod -Uri 'fixture' -TimeoutSec 30
}
$first = Install-DevSetupPortableRuntime -Config $config -Tool TOOL @options
$before = (Get-Item $first).LastWriteTimeUtc
$second = Install-DevSetupPortableRuntime -Config $config -Tool TOOL @options
if ($first -ne $second -or $before -ne (Get-Item $second).LastWriteTimeUtc -or $global:metadataCalls -ne 1) {
    throw 'Portable installation was not idempotent'
}
Write-Host 'PASS: installed twice with one metadata request'
"""
            for key, value in {
                "MODULE_PATH": str(MODULE),
                "USER_HOME": str(root),
                "ARCHIVE_PATH": str(archive),
                "INSTALL_DIR": str(install_dir),
                "TOOL": tool,
                "GHARCH": "amd64" if architecture == "x64" else architecture,
                "ARCH": architecture,
                "DIGEST": digest,
                "VERSIONED": "$true" if versioned else "$false",
            }.items():
                harness = harness.replace(key, value.replace("'", "''"))
            encoded = base64.b64encode(harness.encode("utf-16-le")).decode("ascii")
            result = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                env={
                    key: value for key, value in os.environ.items()
                    if key.lower() != "psmodulepath"
                },
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertFalse(list(root.glob(".devsetup-*")), "staging was not cleaned")
            if existing or versioned:
                self.assertEqual((destination / "keep.txt").read_text(), "preserve")
            if bad_hash:
                installed = destination / "7.6.0" if versioned else destination
                self.assertFalse(installed.exists(), "checksum failure installed a runtime")
            return result

    def test_node_archive_applies_and_is_idempotent(self):
        result = self.run_install("node")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: installed twice", result.stdout)

    def test_powershell_archive_applies_and_is_idempotent(self):
        result = self.run_install("powershell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: installed twice", result.stdout)

    def test_github_cli_archive_applies_and_is_idempotent(self):
        result = self.run_install("githubCli")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: installed twice", result.stdout)
        self.assertIn("PATH", result.stdout)

    def test_powershell_upgrade_preserves_existing_directory(self):
        result = self.run_install("powershell", versioned=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: installed twice", result.stdout)

    def test_powershell_upgrade_checksum_failure_preserves_old_directory(self):
        result = self.run_install("powershell", versioned=True, bad_hash=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA256 verification failed", result.stderr)

    def test_checksum_failure_never_installs(self):
        for tool in ("node", "powershell", "githubCli"):
            with self.subTest(tool=tool):
                result = self.run_install(tool, bad_hash=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SHA256 verification failed", result.stderr)

    def test_existing_directory_is_not_overwritten(self):
        result = self.run_install("node", existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Nothing was overwritten", result.stderr)

    def test_system_directory_is_rejected(self):
        result = self.run_install("node", outside_home=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed below the user profile", result.stderr)


if __name__ == "__main__":
    unittest.main()
