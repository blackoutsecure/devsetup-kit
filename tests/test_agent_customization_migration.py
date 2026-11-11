from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "src" / "configure-vscode.py"
SPEC = importlib.util.spec_from_file_location("agent_customization_applier", SOURCE)
assert SPEC is not None and SPEC.loader is not None
applier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(applier)


class AgentCustomizationMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.copilot = self.root / "copilot"
        environment = patch.dict(os.environ, {"COPILOT_HOME": str(self.copilot)})
        environment.start()
        self.addCleanup(environment.stop)
        self.server = {
            "type": "http",
            "url": "https://example.test/mcp",
        }
        self.config = {
            "user": {
                "vscode": {"profiles": ["test"]},
                "mcp": {"servers": {"github": dict(self.server)}},
            },
            "advanced": {
                "vscode": {
                    "profileDirectories": {
                        platform: {"test": str(self.profile)}
                        for platform in ("windows", "macos", "linux")
                    }
                }
            },
        }
        self.mcp = self.profile / "mcp.json"
        self.mcp.write_text(json.dumps({
            "servers": {
                "github": self.server,
                "unmanaged": {"type": "http", "url": "https://other.test/mcp"},
            },
            "inputs": [{"id": "existing", "type": "promptString"}],
        }), encoding="utf-8")
        self.instructions = (
            self.profile / "prompts" / "terminal-execution.instructions.md"
        )
        self.instructions.parent.mkdir()
        self.instructions.write_bytes(
            b'---\r\napplyTo: "**"\r\n---\r\nPersonal instructions, preserved verbatim.\r\n'
        )
        report = patch.object(applier, "status")
        self.report = report.start()
        self.addCleanup(report.stop)

    def migrate(self, dry_run: bool = False) -> int:
        return applier.migrate_agent_customizations(self.config, "test", dry_run)

    def snapshot(self) -> dict[Path, tuple[bytes, int]]:
        return {
            path.relative_to(self.root): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()
        }

    def test_audit_does_not_create_destinations_or_backups(self) -> None:
        before = self.snapshot()
        self.assertEqual(self.migrate(True), 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.copilot.exists())

    def test_moves_both_candidates_preserving_original_bytes_and_unrelated_data(self) -> None:
        mcp_before = self.mcp.read_bytes()
        instructions_before = self.instructions.read_bytes()
        self.assertEqual(self.migrate(), 0)
        target = self.copilot / "mcp-config.json"
        migrated = json.loads(target.read_text())["mcpServers"]
        self.assertEqual(migrated["github"], {**self.server, "tools": ["*"]})
        self.assertEqual(
            (self.copilot / "instructions" / self.instructions.name).read_bytes(),
            instructions_before,
        )
        self.assertFalse(self.instructions.exists())
        original = json.loads(self.mcp.read_text())
        self.assertNotIn("github", original["servers"])
        self.assertIn("unmanaged", original["servers"])
        self.assertEqual(original["inputs"], [{"id": "existing", "type": "promptString"}])
        backups = list((self.copilot / "migration-backups").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "source-mcp.json").read_bytes(), mcp_before)
        self.assertEqual(
            (backups[0] / "source-terminal-execution.instructions.md").read_bytes(),
            instructions_before,
        )
        if os.name != "nt":
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o700)
        details = "\n".join(call.args[2] for call in self.report.call_args_list)
        self.assertIn("trust", details)

    def test_second_run_is_idempotent(self) -> None:
        self.assertEqual(self.migrate(), 0)
        before = self.snapshot()
        self.report.reset_mock()
        self.assertEqual(self.migrate(), 0)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(
            call.args[0] in {"found", "skip"} for call in self.report.call_args_list
        ))

    def test_normal_setup_does_not_recreate_migrated_candidates(self) -> None:
        self.assertEqual(self.migrate(), 0)
        applier.manage_terminal_instructions(self.config, False)
        applier.manage_mcp(self.config, False)
        applier.validate_mcp(self.config)
        self.assertFalse(self.instructions.exists())
        self.assertNotIn("github", json.loads(self.mcp.read_text())["servers"])
        self.assertEqual(
            self.config["user"]["mcp"]["servers"]["github"], self.server
        )

    def test_migration_record_does_not_change_another_profile(self) -> None:
        self.assertEqual(self.migrate(), 0)
        other = self.root / "other"
        other.mkdir()
        for platform in ("windows", "macos", "linux"):
            self.config["advanced"]["vscode"]["profileDirectories"][platform]["other"] = str(other)
        self.config["user"]["vscode"]["profiles"].append("other")
        applier.manage_terminal_instructions(self.config, False)
        applier.manage_mcp(self.config, False)
        self.assertTrue((other / "prompts" / self.instructions.name).is_file())
        self.assertIn("github", json.loads((other / "mcp.json").read_text())["servers"])

    def test_target_conflict_preserves_every_source_and_creates_no_backup(self) -> None:
        path = self.copilot / "instructions" / self.instructions.name
        path.parent.mkdir(parents=True)
        path.write_text("Different user instructions\n", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "conflict"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.copilot / "migration-backups").exists())

    def test_mcp_conflict_never_overwrites_existing_target(self) -> None:
        target = self.copilot / "mcp-config.json"
        applier.write_json(target, {
            "mcpServers": {"github": {**self.server, "url": "https://local.test/mcp"}},
        })
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "conflict"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_equivalent_existing_target_and_unrelated_servers_are_preserved(self) -> None:
        target = self.copilot / "mcp-config.json"
        original = {
            "mcpServers": {
                "github": dict(self.server),
                "existing": {"type": "http", "url": "https://existing.test/mcp"},
            },
        }
        applier.write_json(target, original)
        before = target.read_bytes(), target.stat().st_mtime_ns
        self.assertEqual(self.migrate(), 0)
        self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)

    def test_unsupported_mcp_fields_require_native_migration(self) -> None:
        content = json.loads(self.mcp.read_text())
        content["servers"]["github"]["gallery"] = "https://example.test/gallery"
        self.mcp.write_text(json.dumps(content), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "native"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_disabled_management_is_not_overridden(self) -> None:
        self.config["user"]["mcp"]["copilotConfig"] = {"manage": False}
        before = self.snapshot()
        self.assertEqual(self.migrate(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_missing_migrated_target_is_an_explicit_error(self) -> None:
        self.assertEqual(self.migrate(), 0)
        (self.copilot / "mcp-config.json").unlink()
        with self.assertRaisesRegex(SystemExit, "missing"):
            applier.manage_mcp(self.config, False)
        self.assertNotIn("github", json.loads(self.mcp.read_text())["servers"])

    def test_changed_files_are_not_overwritten(self) -> None:
        original = self.mcp.read_bytes()
        self.mcp.write_text('{"servers": {}}\n', encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "changed"):
            applier.write_migration_bytes(self.mcp, b"stale migration output", original)
        self.assertEqual(self.snapshot(), before)

    def test_symlinks_are_rejected_without_touching_their_targets(self) -> None:
        if os.name == "nt":
            self.skipTest("Creating symlinks requires Windows developer mode or elevation")
        link = self.root / "linked-config.json"
        link.symlink_to(self.mcp)
        before = self.snapshot()
        with self.assertRaisesRegex(SystemExit, "symbolic-link"):
            applier.write_migration_bytes(link, b"replacement", self.mcp.read_bytes())
        self.assertEqual(self.snapshot(), before)

    def test_missing_profile_is_not_assessed_and_creates_no_files(self) -> None:
        before = self.snapshot()
        self.assertEqual(
            applier.migrate_agent_customizations(self.config, "unknown", False), 1
        )
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Not Assessed", self.report.call_args.args[2])

    def test_native_migrations_can_be_adopted_without_recreating_sources(self) -> None:
        applier.write_json(self.copilot / "mcp-config.json", {
            "mcpServers": {"github": dict(self.server)},
        })
        target = self.copilot / "instructions" / self.instructions.name
        target.parent.mkdir()
        self.instructions.rename(target)
        source = json.loads(self.mcp.read_text())
        del source["servers"]["github"]
        self.mcp.write_text(json.dumps(source), encoding="utf-8")
        self.assertEqual(self.migrate(), 0)
        applier.manage_terminal_instructions(self.config, False)
        applier.manage_mcp(self.config, False)
        self.assertFalse(self.instructions.exists())
        self.assertNotIn("github", json.loads(self.mcp.read_text())["servers"])

    def test_cli_audit_apply_and_repeat_on_disposable_profile(self) -> None:
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config), encoding="utf-8")
        command = [
            sys.executable, str(SOURCE), "--config", str(config),
            "--agent-customization-migration", "test",
        ]
        env = os.environ.copy()
        env.pop("DEVSETUP_STATUS_LOG", None)
        env["NO_COLOR"] = "1"
        before = self.snapshot()
        for arguments in (["--dry-run"], [], []):
            result = subprocess.run(
                [*command, *arguments], env=env, capture_output=True, text=True,
                timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if arguments:
                self.assertEqual(self.snapshot(), before)
            else:
                self.assertFalse(self.instructions.exists())
                self.assertNotIn("github", json.loads(self.mcp.read_text())["servers"])


if __name__ == "__main__":
    unittest.main()
