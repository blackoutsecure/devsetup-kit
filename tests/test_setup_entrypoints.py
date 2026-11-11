import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SetupEntrypointTests(unittest.TestCase):
    def test_github_cli_is_wired_in_all_modes_without_admin_controls(self):
        config = json.loads((ROOT / "config" / "dev-setup.config.json").read_text())
        self.assertTrue(config["user"]["install"]["githubCli"])
        self.assertEqual(config["advanced"]["githubCli"]["homebrewFormula"], "gh")
        self.assertEqual(config["advanced"]["githubCli"]["wingetPackageId"], "GitHub.cli")
        for name, installer in (
            ("setup.ps1", "install-github-cli.ps1"),
            ("setup.sh", "install-github-cli.sh"),
        ):
            text = (ROOT / name).read_text()
            self.assertEqual(text.count(installer), 3)
            self.assertIn("user.install.githubCli is false", text)
            self.assertNotIn("AllowAdminInstall", text)
        installer = (ROOT / "src" / "scripts" / "install-github-cli.ps1").read_text()
        self.assertIn("-FallbackInstall", installer)
        self.assertIn("-Tool githubCli", installer)

    def test_disposable_profile_audit_apply_and_second_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sandbox = Path(temp_dir)
            kit = sandbox / "kit"
            kit.mkdir()
            shutil.copytree(
                ROOT / "src", kit / "src",
                ignore=shutil.ignore_patterns("__pycache__", ".mypy_cache"),
            )
            for name in ("setup.ps1", "setup.sh"):
                shutil.copyfile(ROOT / name, kit / name)
            config = json.loads((ROOT / "config" / "dev-setup.config.json").read_text())
            config = copy.deepcopy(config)
            config["user"]["install"] = {name: False for name in config["user"]["install"]}
            config["user"]["install"].update(
                vscodeSettings=True, devcontainerDefaults=True, mcpServers=True
            )
            config["user"]["checkUpgrades"] = False
            config["user"]["vscode"]["profiles"] = ["test"]
            config["user"]["vscode"]["extensions"]["manage"] = False
            config["user"]["vscode"]["settingsSync"]["syncAfterSetup"] = False
            profile = sandbox / "profile"
            profile.mkdir()
            for platform in ("windows", "macos", "linux"):
                config["advanced"]["vscode"]["profileDirectories"][platform] = {
                    "test": str(profile)
                }
            config_dir = kit / "config"
            config_dir.mkdir()
            (config_dir / "dev-setup.config.json").write_text(json.dumps(config))
            env = os.environ.copy()
            env["COPILOT_HOME"] = str(sandbox / "copilot")
            env["NO_COLOR"] = "1"
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            if os.name == "nt":
                shell = shutil.which("powershell")
                if not shell:
                    self.skipTest("Windows PowerShell is unavailable")
                command = [shell, "-NoProfile", "-NonInteractive", "-File", str(kit / "setup.ps1")]
                audit_option = "-Audit"
                skip_sync_option = "-SkipSettingsSync"
            else:
                if os.geteuid() == 0:
                    self.skipTest("Run the disposable entrypoint test as a non-root user")
                shell = shutil.which("bash")
                if not shell:
                    self.skipTest("Bash is unavailable")
                command = [shell, str(kit / "setup.sh")]
                audit_option = "--audit"
                skip_sync_option = "--skip-settings-sync"

            def run(*options):
                result = subprocess.run(
                    [*command, *options], env=env, capture_output=True, text=True,
                    timeout=120, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Summary:", result.stdout)
                return result.stdout

            run(audit_option)
            self.assertFalse((profile / "settings.json").exists())
            self.assertFalse((sandbox / "copilot").exists())
            first = run()
            self.assertIn("Setup complete", first)
            settings = json.loads((profile / "settings.json").read_text())
            self.assertEqual(settings["chat.editing.autoAcceptDelay"], 1)
            self.assertEqual(settings["chat.requestQueuing.defaultAction"], "queue")
            self.assertFalse(settings["dictation.enabled"])
            self.assertEqual(settings["chat.tools.terminal.outputLocation"], "terminal")
            self.assertTrue(settings["chat.sessionSync.enabled"])
            self.assertTrue(settings["github.copilot.chat.localIndex.enabled"])
            self.assertTrue(
                (profile / "prompts" / "terminal-execution.instructions.md").is_file()
            )
            self.assertTrue((sandbox / "copilot" / "mcp-config.json").is_file())
            before = {
                path.relative_to(sandbox): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in profile.rglob("*") if path.is_file()
            }
            second = run(skip_sync_option)
            self.assertNotIn("[install]", second)
            self.assertNotIn("[warn]", second)
            after = {
                path.relative_to(sandbox): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in profile.rglob("*") if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertIn("terminal sessions remain open", second)
            self.assertIn("--skip-settings-sync was passed", second)


if __name__ == "__main__":
    unittest.main()
