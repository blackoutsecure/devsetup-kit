import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import subprocess
import sqlite3
from pathlib import Path
from contextlib import closing, redirect_stdout
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "src" / "configure-vscode.py"
SPEC = importlib.util.spec_from_file_location("configure_vscode", SOURCE)
assert SPEC is not None and SPEC.loader is not None
configure_vscode = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = configure_vscode
SPEC.loader.exec_module(configure_vscode)


class RustSettingsTests(unittest.TestCase):
    def test_rust_defaults_and_additive_language_settings(self):
        config = configure_vscode.load_json(SOURCE.parents[1] / "config" / "dev-setup.config.json")
        settings = configure_vscode.build_settings(config, None, None, None, None)
        rust_settings = {
            "[rust]": settings["[rust]"],
            "rust-analyzer.check.command": settings["rust-analyzer.check.command"],
        }
        self.assertTrue(config["user"]["install"]["rust"])
        self.assertEqual(settings["chat.editing.autoAcceptDelay"], 1)
        self.assertIn("rust-lang.rust-analyzer", config["user"]["vscode"]["extensions"]["install"])
        self.assertEqual(rust_settings["rust-analyzer.check.command"], "clippy")
        self.assertEqual(rust_settings["[rust]"]["editor.defaultFormatter"], "rust-lang.rust-analyzer")
        self.assertTrue(rust_settings["[rust]"]["editor.formatOnSave"])
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            path = profile / "settings.json"
            original = {"[rust]": {"editor.tabSize": 4}, "[python]": {"editor.tabSize": 2}}
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()
            self.assertTrue(configure_vscode.apply(profile, rust_settings, None, True))
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(configure_vscode.apply(profile, rust_settings, None, False))
            actual = json.loads(path.read_text())
            self.assertEqual(actual["[rust]"]["editor.tabSize"], 4)
            self.assertEqual(actual["[python]"], original["[python]"])
            self.assertFalse(configure_vscode.apply(profile, rust_settings, None, False))
            with patch.object(configure_vscode, "profile_targets", return_value=[("test", profile)]):
                configure_vscode.validate_profiles({}, rust_settings, None)
                actual["[rust]"]["editor.formatOnSave"] = False
                path.write_text(json.dumps(actual), encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "settings validation failed"):
                    configure_vscode.validate_profiles({}, rust_settings, None)


class CopilotMcpConfigTests(unittest.TestCase):
    def test_uses_copilot_home_when_configured(self):
        with patch.dict(os.environ, {"COPILOT_HOME": "~/copilot-home"}):
            self.assertEqual(
                configure_vscode.copilot_mcp_config_path(),
                Path.home() / "copilot-home" / "mcp-config.json",
            )

    def test_converts_portable_server_and_defaults_tool_allowlist(self):
        server = {
            "type": "http",
            "url": "https://example.test/mcp",
        }

        self.assertEqual(
            configure_vscode.copilot_mcp_server(server),
            {
                "type": "http",
                "url": "https://example.test/mcp",
                "tools": ["*"],
            },
        )

    def test_skips_vscode_inputs_and_unsupported_metadata(self):
        self.assertIsNone(
            configure_vscode.copilot_mcp_server(
                {
                    "type": "http",
                    "url": "${input:server-url}",
                }
            )
        )
        self.assertIsNone(
            configure_vscode.copilot_mcp_server(
                {
                    "type": "stdio",
                    "command": "uvx",
                    "gallery": "https://registry.example.test",
                }
            )
        )
        self.assertIsNone(
            configure_vscode.copilot_mcp_server(
                {
                    "type": "sse",
                    "url": "https://example.test/sse",
                }
            )
        )

    def test_dry_run_is_read_only_and_apply_is_additive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "mcp-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing": {
                                "type": "http",
                                "url": "https://local.example.test/mcp",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "user": {
                    "mcp": {
                        "servers": {
                            "existing": {
                                "type": "http",
                                "url": "https://managed.example.test/mcp",
                            },
                            "new": {
                                "type": "stdio",
                                "command": "uvx",
                                "args": ["example-server"],
                            },
                            "interactive": {
                                "type": "http",
                                "url": "${input:server-url}",
                            },
                        }
                    }
                }
            }

            with patch(
                "configure_vscode.copilot_mcp_config_path",
                return_value=config_path,
            ):
                configure_vscode.manage_copilot_mcp(config, dry_run=True)
                self.assertNotIn(
                    "new",
                    json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"],
                )

                configure_vscode.manage_copilot_mcp(config, dry_run=False)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    saved["mcpServers"]["existing"]["url"],
                    "https://local.example.test/mcp",
                )
                self.assertEqual(
                    saved["mcpServers"]["new"]["tools"],
                    ["*"],
                )
                self.assertNotIn("interactive", saved["mcpServers"])

                configure_vscode.manage_copilot_mcp(config, dry_run=False)
                self.assertEqual(
                    json.loads(config_path.read_text(encoding="utf-8")),
                    saved,
                )

    def test_rejects_non_object_mcp_servers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp-config.json"
            path.write_text('{"mcpServers": []}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                configure_vscode.current_copilot_mcp_servers(
                    json.loads(path.read_text(encoding="utf-8")),
                    path,
                )


class GitHubMcpSetupTests(unittest.TestCase):
    def setUp(self):
        self.config = configure_vscode.load_json(configure_vscode.DEFAULT_CONFIG)
        self.server_name = "io.github.github/github-mcp-server"
        self.server = self.config["user"]["mcp"]["servers"][self.server_name]

    def test_official_remote_and_github_sync_are_shipped_defaults(self):
        self.assertEqual(
            self.server,
            {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
        )
        self.assertTrue(self.config["user"]["install"]["mcpServers"])
        self.assertTrue(self.config["user"]["mcp"]["manage"])
        self.assertTrue(self.config["user"]["mcp"]["copilotConfig"]["manage"])
        sync = self.config["user"]["vscode"]["settingsSync"]
        self.assertTrue(sync["syncAfterSetup"])
        self.assertEqual(sync["requiredProvider"], "github")
        self.assertEqual(
            configure_vscode.copilot_mcp_servers(self.config)[self.server_name],
            {**self.server, "tools": ["*"]},
        )

    def test_audit_apply_and_second_run_preserve_profile_and_copilot_config(self):
        self.config["user"]["mcp"]["servers"] = {self.server_name: self.server}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = [(name, root / name) for name in ("stable", "insiders")]
            existing_server = {"type": "http", "url": "https://example.test/mcp"}
            profile_original = {
                "servers": {"existing": existing_server},
                "inputs": [{"id": "existing", "type": "promptString"}],
            }
            for _, user_dir in profiles:
                configure_vscode.write_json(user_dir / "mcp.json", profile_original)
            copilot_path = root / "copilot" / "mcp-config.json"
            copilot_original = {"mcpServers": {"existing": existing_server}}
            configure_vscode.write_json(copilot_path, copilot_original)
            paths = [user_dir / "mcp.json" for _, user_dir in profiles] + [copilot_path]

            def snapshots():
                return {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in paths
                }

            with (
                patch("configure_vscode.profile_targets", return_value=profiles),
                patch("configure_vscode.copilot_mcp_config_path", return_value=copilot_path),
            ):
                before = snapshots()
                configure_vscode.manage_mcp(self.config, dry_run=True)
                configure_vscode.manage_copilot_mcp(self.config, dry_run=True)
                self.assertEqual(snapshots(), before)

                configure_vscode.manage_mcp(self.config, dry_run=False)
                configure_vscode.manage_copilot_mcp(self.config, dry_run=False)
                configure_vscode.validate_mcp(self.config)
                configure_vscode.validate_copilot_mcp(self.config)
                for _, user_dir in profiles:
                    self.assertEqual(
                        configure_vscode.load_json(user_dir / "mcp.json"),
                        {
                            **profile_original,
                            "servers": {
                                **profile_original["servers"],
                                self.server_name: self.server,
                            },
                        },
                    )
                self.assertEqual(
                    configure_vscode.load_json(copilot_path),
                    {
                        "mcpServers": {
                            **copilot_original["mcpServers"],
                            self.server_name: {**self.server, "tools": ["*"]},
                        }
                    },
                )

                after = snapshots()
                configure_vscode.manage_mcp(self.config, dry_run=False)
                configure_vscode.manage_copilot_mcp(self.config, dry_run=False)
                self.assertEqual(snapshots(), after)


class DefaultSettingsTests(unittest.TestCase):
    def setUp(self):
        self.config = configure_vscode.load_json(configure_vscode.DEFAULT_CONFIG)

    def settings(self):
        return configure_vscode.build_settings(self.config, None, None, None, None)

    def test_playwright_extension_is_in_the_managed_profile_baseline(self):
        extensions = self.config["user"]["vscode"]["extensions"]["install"]
        self.assertIn("ms-playwright.playwright", extensions)

    def test_python_environments_and_shellcheck_are_explicit_defaults(self):
        for key in ("vscode", "devcontainers"):
            with self.subTest(target=key):
                extensions = self.config["user"][key]["extensions"]
                if key == "vscode":
                    extensions = extensions["install"]
                self.assertIn("ms-python.vscode-python-envs", extensions)
                self.assertIn("timonwong.shellcheck", extensions)

    def test_workspace_extensions_follow_the_developer_into_containers(self):
        host = {
            extension.lower()
            for extension in self.config["user"]["vscode"]["extensions"]["install"]
        }
        container = {
            extension.lower()
            for extension in self.config["user"]["devcontainers"]["extensions"]
        }
        host_only = {
            "ms-azuretools.vscode-containers",
            "ms-vscode-remote.remote-containers",
        }
        self.assertEqual(host - host_only - container, set())

    def test_extension_defaults_are_unique_and_do_not_install_blocked_tools(self):
        policy = self.config["user"]["vscode"]["extensions"]
        blocked = {extension.lower() for extension in policy["block"]}
        for target, extensions in (
            ("host", policy["install"]),
            ("container", self.config["user"]["devcontainers"]["extensions"]),
        ):
            with self.subTest(target=target):
                normalized = {extension.lower() for extension in extensions}
                self.assertEqual(len(extensions), len(normalized))
                self.assertFalse(normalized & blocked)

    def test_extension_update_checks_are_enabled_and_can_be_overridden(self):
        for key in ("extensions.autoCheckUpdates", "extensions.autoUpdate"):
            with self.subTest(setting=key):
                self.assertTrue(self.settings()[key])
                self.config["user"]["vscode"]["settings"][key] = False
                self.assertFalse(self.settings()[key])

    def test_local_mcp_launchers_use_reviewed_pins_without_interactive_npm_prompts(self):
        servers = self.config["user"]["mcp"]["servers"]
        self.assertEqual(
            servers["microsoft/playwright-mcp"],
            {"type": "stdio", "command": "npx", "args": ["--yes", "@playwright/mcp@0.0.83"]},
        )
        self.assertEqual(
            servers["microsoft/markitdown"],
            {"type": "stdio", "command": "uvx", "args": ["markitdown-mcp@0.0.1a8"]},
        )

    def test_baseline_keeps_terminals_visible_and_voice_disabled(self):
        settings = self.settings()
        self.assertEqual(settings["chat.requestQueuing.defaultAction"], "queue")
        self.assertEqual(settings["chat.tools.terminal.outputLocation"], "terminal")
        self.assertTrue(settings["chat.tools.terminal.enforceTimeoutFromModel"])
        self.assertEqual(settings["chat.tools.terminal.idleSilenceTimeoutMs"], 60000)
        self.assertFalse(settings["terminal.integrated.enablePersistentSessions"])
        self.assertEqual(settings["terminal.integrated.persistentSessionReviveProcess"], "never")
        self.assertFalse(settings["dictation.enabled"])
        self.assertFalse(settings["agents.voice.enabled"])
        self.assertEqual(settings["window.confirmBeforeClose"], "always")

    def test_unattended_permissions_and_fusion_are_opt_in(self):
        self.assertNotIn("chat.defaultConfiguration", self.settings())
        self.assertNotIn("chat.copilot.ensemble.enabled", self.settings())
        self.config["user"]["vscode"]["copilot"] = {"autopilot": True, "fusion": True}
        settings = self.settings()
        self.assertEqual(
            settings["chat.defaultConfiguration"],
            {"mode": "autopilot", "approvals": "allowAll"},
        )
        self.assertEqual(settings["chat.permissions.default"], "autopilot")
        self.assertTrue(settings["chat.copilot.ensemble.enabled"])
        self.assertEqual(settings["chat.copilot.hydraFusion.enabled"], "v2")
        self.assertEqual(settings["github.copilot.chat.autoModeTierOverride"], "balance")
        self.assertEqual(settings["chat.defaultModel"], "auto")

    def test_user_settings_override_opt_in_presets(self):
        self.config["user"]["vscode"]["copilot"]["autopilot"] = True
        self.config["user"]["vscode"]["settings"]["chat.permissions.default"] = "default"
        self.assertEqual(self.settings()["chat.permissions.default"], "default")

    def test_non_root_devcontainer_and_no_global_python_installs(self):
        self.assertEqual(self.config["user"]["devcontainers"]["remoteUser"], "vscode")
        self.assertFalse(self.settings()["python.globalModuleInstallation"])

    def test_cloud_session_sync_and_its_index_dependency_are_enabled(self):
        settings = self.settings()
        self.assertTrue(settings["chat.sessionSync.enabled"])
        self.assertTrue(settings["github.copilot.chat.localIndex.enabled"])
        self.assertTrue(self.config["user"]["vscode"]["settingsSync"]["syncAfterSetup"])
        self.config["user"]["vscode"]["settings"]["chat.sessionSync.enabled"] = False
        self.assertFalse(self.settings()["chat.sessionSync.enabled"])


class CopilotAutoKeepTests(unittest.TestCase):
    def setUp(self):
        self.config = configure_vscode.load_json(configure_vscode.DEFAULT_CONFIG)

    def settings(self):
        return configure_vscode.build_settings(self.config, None, None, None, None)

    def test_shipped_default_is_one_second_and_syncable_without_tool_approvals(self):
        self.assertEqual(self.config["user"]["vscode"]["copilot"]["autoAcceptDelay"], 1)
        settings = self.settings()
        self.assertEqual(settings["chat.editing.autoAcceptDelay"], 1)
        self.assertNotIn(
            "chat.editing.autoAcceptDelay", settings["settingsSync.ignoredSettings"]
        )
        self.assertTrue(self.config["user"]["vscode"]["settingsSync"]["syncAfterSetup"])
        self.assertEqual(
            self.config["user"]["vscode"]["settingsSync"]["requiredProvider"], "github"
        )
        self.assertNotIn("chat.permissions.default", settings)
        self.assertNotIn("chat.defaultConfiguration", settings)
        self.assertNotIn("chat.copilot.ensemble.enabled", settings)

    def test_missing_null_or_blank_delay_defaults_to_one_second(self):
        for copilot in ({}, {"autoAcceptDelay": None}, {"autoAcceptDelay": ""}):
            with self.subTest(copilot=copilot):
                self.config["user"]["vscode"]["copilot"] = copilot
                self.assertEqual(self.settings()["chat.editing.autoAcceptDelay"], 1)
        settings = configure_vscode.build_settings(
            {"user": {"install": {"devcontainerDefaults": False}}},
            None, None, None, None,
        )
        self.assertEqual(settings["chat.editing.autoAcceptDelay"], 1)

    def test_configured_delay_includes_zero_for_manual_review(self):
        for delay in (0, 1, 2.5, 100):
            with self.subTest(delay=delay):
                self.config["user"]["vscode"]["copilot"]["autoAcceptDelay"] = delay
                self.assertEqual(self.settings()["chat.editing.autoAcceptDelay"], delay)

    def test_explicit_user_settings_override_the_preset(self):
        self.config["user"]["vscode"]["copilot"]["autoAcceptDelay"] = 5
        for delay in (0, 3):
            with self.subTest(delay=delay):
                self.config["user"]["vscode"]["settings"]["chat.editing.autoAcceptDelay"] = delay
                self.assertEqual(self.settings()["chat.editing.autoAcceptDelay"], delay)

    def test_invalid_delays_fail_before_writing_profiles(self):
        for delay in (-1, 101, True, False, "1", [], {}, float("inf"), float("nan")):
            with self.subTest(delay=delay):
                self.config["user"]["vscode"]["copilot"]["autoAcceptDelay"] = delay
                with self.assertRaisesRegex(SystemExit, "autoAcceptDelay.*0.*100"):
                    self.settings()

    def test_audit_apply_validation_and_second_run_preserve_each_profile(self):
        settings = {"chat.editing.autoAcceptDelay": self.settings()["chat.editing.autoAcceptDelay"]}
        original = {
            "editor.fontSize": 17,
            "chat.editing.autoAcceptDelay": 10,
            "chat.permissions.default": "default",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            targets = [
                (profile, Path(temp_dir) / profile)
                for profile in ("stable", "insiders")
            ]
            for _, user_dir in targets:
                configure_vscode.write_json(user_dir / "settings.json", original)

            def snapshot():
                return {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for _, user_dir in targets
                    for path in [user_dir / "settings.json"]
                }

            with (
                patch("configure_vscode.profile_targets", return_value=targets),
                patch("configure_vscode.status") as report,
            ):
                before = snapshot()
                for _, user_dir in targets:
                    self.assertTrue(configure_vscode.apply(user_dir, settings, None, True))
                self.assertEqual(snapshot(), before)

                for _, user_dir in targets:
                    self.assertTrue(configure_vscode.apply(user_dir, settings, None, False))
                    self.assertEqual(
                        configure_vscode.load_json(user_dir / "settings.json"),
                        {**original, "chat.editing.autoAcceptDelay": 1},
                    )
                configure_vscode.validate_profiles(self.config, settings, None)
                before = snapshot()
                report.reset_mock()
                for _, user_dir in targets:
                    self.assertFalse(configure_vscode.apply(user_dir, settings, None, False))
                self.assertEqual(snapshot(), before)
                self.assertEqual(
                    {call.args[0] for call in report.call_args_list}, {"found"}
                )

    def test_validation_rejects_a_profile_with_the_wrong_delay(self):
        settings = {"chat.editing.autoAcceptDelay": self.settings()["chat.editing.autoAcceptDelay"]}
        with tempfile.TemporaryDirectory() as temp_dir:
            user_dir = Path(temp_dir)
            configure_vscode.write_json(
                user_dir / "settings.json", {"chat.editing.autoAcceptDelay": 10}
            )
            with patch("configure_vscode.profile_targets", return_value=[("test", user_dir)]):
                with self.assertRaisesRegex(SystemExit, "validation failed.*autoAcceptDelay"):
                    configure_vscode.validate_profiles(self.config, settings, None)


class ExtensionManagementTests(unittest.TestCase):
    def setUp(self):
        self.config = configure_vscode.load_json(configure_vscode.DEFAULT_CONFIG)
        self.wanted = set(self.config["user"]["vscode"]["extensions"]["install"])
        self.additions = {"ms-python.vscode-python-envs", "timonwong.shellcheck"}
        self.optional = "example.optional-tool"
        self.blocked = "ms-azuretools.vscode-docker"
        self.installed = (self.wanted - self.additions) | {self.optional, self.blocked}

    def test_plan_adds_recommendations_and_only_removes_explicitly_blocked_tools(self):
        missing, blocked = configure_vscode.extension_plan(self.config, self.installed)
        self.assertCountEqual(missing, self.additions)
        self.assertEqual(blocked, [self.blocked])

    def test_extension_audit_never_changes_installed_extensions(self):
        before = set(self.installed)
        with (
            patch("configure_vscode.code_cli_targets", return_value=[("test", "code", "code")]),
            patch("configure_vscode.installed_extensions", return_value=self.installed),
            patch("configure_vscode.run_cli") as run,
            patch("configure_vscode.status") as report,
        ):
            configure_vscode.manage_extensions(self.config, dry_run=True)
            run.assert_not_called()
            details = [call.args[2] for call in report.call_args_list]
            for extension in self.additions:
                self.assertIn(f"would install {extension} (test)", details)
            self.assertIn(f"would uninstall blocked {self.blocked} (test)", details)
        self.assertEqual(self.installed, before)

    def test_apply_preserves_optional_tools_and_second_run_makes_no_changes(self):
        def run_cli(cli, operation, extension, *args, **kwargs):
            self.assertEqual(cli, "code")
            if operation == "--install-extension":
                self.installed.add(extension)
            elif operation == "--uninstall-extension":
                self.installed.remove(extension)
            else:
                self.fail(f"Unexpected extension operation: {operation}")
            return 0, ""

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(sys, "argv", [str(SOURCE), "--skip-settings-sync"]),
            patch(
                "configure_vscode.profile_targets",
                return_value=[("test", Path(temp_dir) / "User")],
            ),
            patch(
                "configure_vscode.copilot_mcp_config_path",
                return_value=Path(temp_dir) / "copilot-mcp.json",
            ),
            patch("configure_vscode.code_cli_targets", return_value=[("test", "code", "code")]),
            patch("configure_vscode.installed_extensions", side_effect=lambda *args: set(self.installed)),
            patch("configure_vscode.run_cli", side_effect=run_cli) as run,
            patch("configure_vscode.status") as report,
        ):
            user_dir = Path(temp_dir) / "User"
            user_dir.mkdir()
            settings_path = user_dir / "settings.json"
            custom_settings = {"editor.fontSize": 17, "[python]": {"editor.tabSize": 2}}
            settings_path.write_text(json.dumps(custom_settings), encoding="utf-8")

            def snapshot():
                return {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in Path(temp_dir).rglob("*")
                    if path.is_file()
                }

            before = snapshot()
            with patch.object(
                sys, "argv", [str(SOURCE), "--dry-run", "--skip-settings-sync"]
            ):
                self.assertEqual(configure_vscode.main(), 0)
            run.assert_not_called()
            self.assertEqual(snapshot(), before)

            self.assertEqual(configure_vscode.main(), 0)
            self.assertEqual(run.call_count, len(self.additions) + 1)
            self.assertEqual(self.installed, self.wanted | {self.optional})
            saved = configure_vscode.load_json(settings_path)
            self.assertEqual(saved["editor.fontSize"], custom_settings["editor.fontSize"])
            self.assertEqual(saved["[python]"], custom_settings["[python]"])
            self.assertTrue(self.additions <= set(saved["dev.containers.defaultExtensions"]))
            before = snapshot()
            run.reset_mock()
            report.reset_mock()
            self.assertEqual(configure_vscode.main(), 0)
            run.assert_not_called()
            self.assertEqual(snapshot(), before)
            self.assertEqual(
                {call.args[0] for call in report.call_args_list}, {"found", "skip"}
            )


class McpPluginSupportAuditTests(unittest.TestCase):
    def test_launcher_and_pin_review_does_not_expose_credentials_or_start_servers(self):
        secret = "support-audit-secret-value"
        expected = {
            "local": {"type": "stdio", "command": "npx", "args": ["example@2.0.0"]},
        }
        servers = {
            "local": {
                "type": "stdio", "command": "npx", "args": ["example@1.0.0"],
                "env": {"TOKEN": secret},
            },
            "remote": {
                "type": "http", "url": f"https://user:{secret}@example.test/private",
                "headers": {"Authorization": secret},
            },
        }
        before = json.dumps(servers)
        with (
            patch("configure_vscode.shutil.which", return_value=None),
            patch("configure_vscode.run_cli") as run,
            patch("configure_vscode.status") as report,
        ):
            configure_vscode.audit_mcp_support(servers, expected, "test")
            run.assert_not_called()
        details = "\n".join(call.args[2] for call in report.call_args_list)
        self.assertNotIn(secret, details)
        self.assertNotIn("example.test", details)
        self.assertIn("launcher unavailable", details)
        self.assertIn("existing pin/customization preserved", details)
        self.assertIn("authentication/connectivity not tested", details)
        self.assertEqual(json.dumps(servers), before)

    def test_invalid_server_shapes_fail_explicitly(self):
        invalid = (
            [],
            {"server": []},
            {"server": {"type": "stdio", "command": "", "args": []}},
            {"server": {"type": "stdio", "command": "npx", "args": "invalid"}},
            {"server": {"type": "stdio", "command": "npx", "args": [42]}},
            {"server": {"type": "http"}},
        )
        for servers in invalid:
            with self.subTest(servers=servers), patch("configure_vscode.status"):
                with self.assertRaises(SystemExit):
                    configure_vscode.audit_mcp_support(servers, {}, "test")

    def test_plugin_inventory_preserves_disabled_state_and_redacts_sources(self):
        plugins = [
            {"name": "workiq", "version": "2.0.2", "enabled": True,
             "marketplace": "copilot-plugins", "source": "private-source-secret"},
            {"name": "browser-use", "version": "0.0.4", "enabled": False},
            {"name": "winui", "version": "0.5.0", "enabled": True,
             "marketplace": "win-dev-skills"},
        ]
        with (
            patch("configure_vscode.shutil.which", return_value="copilot"),
            patch("configure_vscode.run_cli", side_effect=[
                (0, json.dumps(plugins)),
                (0, '[{"name":"copilot-plugins","source":"private-source-secret"}]'),
            ]) as run,
            patch("configure_vscode.status") as report,
        ):
            configure_vscode.audit_plugin_support()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                run.call_args_list[0].args,
                ("copilot", "plugin", "list", "--json"),
            )
            self.assertEqual(run.call_args_list[1].args,
                             ("copilot", "plugin", "marketplace", "list", "--json"))
            self.assertTrue(all(call.kwargs["redact_output"] for call in run.call_args_list))
        details = "\n".join(call.args[2] for call in report.call_args_list)
        self.assertIn("workiq@copilot-plugins 2.0.2: enabled", details)
        self.assertIn("disabled; left disabled", details)
        self.assertNotIn("private-source-secret", details)
        self.assertIn("caches are not modified", details)
        self.assertIn("win-dev-skills: installed plugin marketplace is not registered", details)

    def test_marketplace_inventory_errors_are_explicit_and_redacted(self):
        plugins = [{"name": "example", "version": "1.0.0", "enabled": True,
                    "marketplace": "example-marketplace"}]
        for result in ((1, "secret-output"), (0, "secret-output"), (0, "{}")):
            with self.subTest(result=result), patch(
                "configure_vscode.shutil.which", return_value="copilot"
            ), patch("configure_vscode.run_cli", side_effect=[(0, json.dumps(plugins)), result]), patch(
                "configure_vscode.status"
            ):
                with self.assertRaises(SystemExit) as error:
                    configure_vscode.audit_plugin_support()
                self.assertNotIn("secret-output", str(error.exception))

    def test_missing_plugin_cli_is_skipped_not_installed(self):
        with (
            patch("configure_vscode.shutil.which", return_value=None),
            patch("configure_vscode.run_cli") as run,
            patch("configure_vscode.status") as report,
        ):
            configure_vscode.audit_plugin_support()
            run.assert_not_called()
            self.assertEqual(report.call_args.args[0], "skip")

    def test_plugin_inventory_failures_do_not_print_command_output(self):
        cases = (
            (1, "private-output-secret"),
            (0, "private-output-secret"),
            (0, '{"unexpected": "private-output-secret"}'),
            (0, '[{"name":"private/output/secret","version":"1.0.0","enabled":true}]'),
            (0, '[{"name":"example","version":"private/output/secret","enabled":true}]'),
        )
        for result in cases:
            with self.subTest(result=result), patch(
                "configure_vscode.shutil.which", return_value="copilot"
            ), patch("configure_vscode.run_cli", return_value=result):
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(SystemExit) as error:
                    configure_vscode.audit_plugin_support()
                self.assertNotIn("private", output.getvalue())
                self.assertNotIn("private-output-secret", str(error.exception))

    def test_redacted_timeout_does_not_echo_partial_plugin_output(self):
        error = subprocess.TimeoutExpired(
            ["copilot", "plugin", "list", "--json"], 120,
            output="partial-secret-output", stderr="partial-secret-error",
        )
        output = io.StringIO()
        with patch("configure_vscode.subprocess.run", side_effect=error), redirect_stdout(output):
            with self.assertRaises(SystemExit):
                configure_vscode.run_cli(
                    "copilot", "plugin", "list", "--json", redact_output=True
                )
        self.assertEqual(output.getvalue(), "")

    def test_support_mode_is_read_only_and_never_calls_setup_managers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "profile"
            user.mkdir()
            server = {"local": {"type": "stdio", "command": "npx", "args": ["example@1.0.0"]}}
            (user / "mcp.json").write_text(json.dumps({"servers": server}))
            copilot = root / "copilot-mcp.json"
            copilot.write_text(json.dumps({"mcpServers": server}))
            config = root / "config.json"
            config.write_text(json.dumps({"user": {"mcp": {"servers": server}}}))
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in root.iterdir() if path.is_file()}
            before[user / "mcp.json"] = ((user / "mcp.json").read_bytes(),
                                         (user / "mcp.json").stat().st_mtime_ns)
            with (
                patch.object(sys, "argv", [str(SOURCE), "--config", str(config), "--support-audit"]),
                patch("configure_vscode.profile_targets", return_value=[("test", user)]),
                patch("configure_vscode.copilot_mcp_config_path", return_value=copilot),
                patch("configure_vscode.enforce_execution_mode") as enforce,
                patch("configure_vscode.shutil.which", return_value="available"),
                patch("configure_vscode.run_cli", return_value=(0, "[]")) as run,
                patch("configure_vscode.apply") as apply,
                patch("configure_vscode.manage_mcp") as manage,
                patch("configure_vscode.sync_settings") as sync,
                patch("configure_vscode.status"),
            ):
                self.assertEqual(configure_vscode.main(), 0)
                enforce.assert_called_once_with(True)
                run.assert_called_once_with(
                    "available", "plugin", "list", "--json", redact_output=True,
                )
                apply.assert_not_called()
                manage.assert_not_called()
                sync.assert_not_called()
            for path, snapshot in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshot)

    def test_support_audit_rejects_migration_modes(self):
        for option in (["--copilot-chat-migration"],
                       ["--agent-customization-migration", "stable"]):
            with self.subTest(option=option), patch.object(
                sys, "argv", [str(SOURCE), "--support-audit", *option]
            ), patch("configure_vscode.load_json") as load:
                with self.assertRaises(SystemExit) as error:
                    configure_vscode.main()
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()


class SettingsSyncTests(unittest.TestCase):
    def setUp(self):
        self.real_reader = configure_vscode.read_state_value
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.user_dir = Path(self.temp.name)
        self.config = {
            "advanced": {"vscode": {"extensionCli": {"test": "code"}}},
        }
        self.state = {
            "sync.enable": "true",
            "userDataSyncAccountProvider": "github",
            "userDataSyncAccountPreference": "opaque-account-reference",
        }
        for name, kwargs in (
            ("profile_targets", {"return_value": [("test", self.user_dir)]}),
            ("read_state_value", {"side_effect": lambda config, user, key: self.state.get(key)}),
            ("find_code_cli", {"return_value": "code"}),
            ("run_cli", {"return_value": (0, "")}),
            ("status", {}),
        ):
            mock = patch(f"configure_vscode.{name}", **kwargs)
            setattr(self, name, mock.start())
            self.addCleanup(mock.stop)

    def test_enabled_by_default_with_supported_cached_account(self):
        configure_vscode.sync_settings(self.config, False)
        self.run_cli.assert_called_once_with("code", "--sync", "on")
        self.assertIn("Copilot session uploads are separate", self.status.call_args.args[2])

    def test_config_opt_out_never_requests_sync(self):
        self.config["user"] = {"vscode": {"settingsSync": {"syncAfterSetup": False}}}
        configure_vscode.sync_settings(self.config, False)
        self.read_state_value.assert_not_called()
        self.run_cli.assert_not_called()

    def test_missing_disabled_or_signed_out_state_skips_sync(self):
        cases = (
            {"sync.enable": "false"},
            {"sync.enable": None},
            {"userDataSyncAccountProvider": None},
            {"userDataSyncAccountProvider": "github-enterprise"},
            {"userDataSyncAccountProvider": "microsoft"},
            {"userDataSyncAccountPreference": None},
            {"userDataSyncAccountPreference": " "},
        )
        for change in cases:
            with self.subTest(change=change):
                original = dict(self.state)
                self.state.update(change)
                configure_vscode.sync_settings(self.config, False)
                self.run_cli.assert_not_called()
                self.assertEqual(self.status.call_args.args[0], "skip")
                self.state = original

    def test_microsoft_account_can_be_explicitly_supported(self):
        self.state["userDataSyncAccountProvider"] = "microsoft"
        self.config["user"] = {"vscode": {"settingsSync": {"requiredProvider": "microsoft"}}}
        configure_vscode.sync_settings(self.config, False)
        self.run_cli.assert_called_once()

    def test_dry_run_is_read_only(self):
        configure_vscode.sync_settings(self.config, True)
        self.run_cli.assert_not_called()
        self.assertIn("dry-run", self.status.call_args.args[2])

    def test_missing_cli_skips_sync(self):
        self.find_code_cli.return_value = None
        configure_vscode.sync_settings(self.config, False)
        self.run_cli.assert_not_called()
        self.assertEqual(self.status.call_args.args[0], "skip")

    def test_request_failure_is_reported(self):
        self.run_cli.return_value = (1, "sign-in required")
        configure_vscode.sync_settings(self.config, False)
        self.assertEqual(self.status.call_args.args[0], "warn")
        self.assertIn("sign-in required", self.status.call_args.args[2])

    def test_state_reader_uses_read_only_database_and_warns_on_invalid_state(self):
        db = self.user_dir / "globalStorage" / "state.vscdb"
        self.assertIsNone(self.real_reader({}, self.user_dir, "sync.enable"))
        self.assertFalse(db.exists())
        db.parent.mkdir()
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
            connection.execute("INSERT INTO ItemTable VALUES ('sync.enable', 'true')")
            connection.commit()
        before = db.read_bytes()
        self.assertEqual(self.real_reader({}, self.user_dir, "sync.enable"), "true")
        self.assertEqual(db.read_bytes(), before)
        db.write_bytes(b"not a sqlite database")
        self.assertIsNone(self.real_reader({}, self.user_dir, "sync.enable"))
        self.assertEqual(self.status.call_args.args[0], "warn")


class CopilotChatMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user_dir = self.root / "profile"
        self.user_dir.mkdir()
        self.settings_path = self.user_dir / "settings.json"
        self.original = '{"editor.fontSize": 17, "chat.sessionSync.enabled": false}\n'
        self.settings_path.write_text(self.original, encoding="utf-8")
        self.sync_settings = {
            "chat.sessionSync.enabled": True,
            "github.copilot.chat.localIndex.enabled": True,
        }
        self.config = {"user": {"vscode": {"settings": dict(self.sync_settings)}}}
        targets = patch(
            "configure_vscode.profile_targets",
            return_value=[("test", self.user_dir)],
        )
        self.targets = targets.start()
        self.addCleanup(targets.stop)
        report = patch("configure_vscode.status")
        self.report = report.start()
        self.addCleanup(report.stop)

    def test_audit_is_read_only_and_does_not_claim_history_was_migrated(self):
        before = (self.settings_path.read_bytes(), self.settings_path.stat().st_mtime_ns)
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, True), 0
        )
        self.assertEqual(
            before,
            (self.settings_path.read_bytes(), self.settings_path.stat().st_mtime_ns),
        )
        details = "\n".join(call.args[2] for call in self.report.call_args_list)
        self.assertIn("Not Assessed", details)
        self.assertIn("SOURCE", details)
        self.assertIn("TARGET", details)

    def test_apply_changes_only_sync_preferences_and_second_run_is_idempotent(self):
        self.config["user"]["vscode"]["settings"]["editor.fontSize"] = 99
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, False), 0
        )
        self.assertEqual(
            json.loads(self.settings_path.read_text()),
            {"editor.fontSize": 17, **self.sync_settings},
        )
        before = (self.settings_path.read_bytes(), self.settings_path.stat().st_mtime_ns)
        self.report.reset_mock()
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, False), 0
        )
        self.assertEqual(
            before,
            (self.settings_path.read_bytes(), self.settings_path.stat().st_mtime_ns),
        )
        self.assertTrue(all(
            call.args[0] in {"found", "skip"} for call in self.report.call_args_list
        ))

    def test_explicitly_enabled_preferences_are_required_before_any_write(self):
        for key in self.sync_settings:
            for value in (False, None, "true", 1):
                with self.subTest(key=key, value=value):
                    self.config["user"]["vscode"]["settings"][key] = value
                    self.assertEqual(
                        configure_vscode.prepare_copilot_chat_migration(self.config, False),
                        1,
                    )
                    self.assertEqual(self.settings_path.read_text(), self.original)
                    self.assertIn("Not Assessed", self.report.call_args.args[2])
            self.config["user"]["vscode"]["settings"][key] = True

    def test_advanced_settings_are_inherited_and_user_opt_out_wins(self):
        self.config["advanced"] = {
            "vscode": {"settings": dict(self.sync_settings)}
        }
        self.config["user"]["vscode"]["settings"] = {}
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, True), 0
        )
        self.config["user"]["vscode"]["settings"]["chat.sessionSync.enabled"] = False
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, False), 1
        )
        self.assertEqual(self.settings_path.read_text(), self.original)

    def test_disabled_settings_management_and_missing_profiles_do_not_write(self):
        self.config["user"]["install"] = {"vscodeSettings": False}
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, False), 1
        )
        self.targets.assert_not_called()
        self.config["user"]["install"]["vscodeSettings"] = True
        missing = self.root / "missing"
        self.targets.return_value = [("missing", missing)]
        self.assertEqual(
            configure_vscode.prepare_copilot_chat_migration(self.config, False), 1
        )
        self.assertFalse(missing.exists())
        self.assertIn("Not Assessed", self.report.call_args.args[2])

    def test_all_profiles_are_preflighted_before_writing(self):
        other = self.root / "other"
        other.mkdir()
        self.targets.return_value.append(("other", other))
        for invalid in ("[]", '{"broken":'):
            with self.subTest(invalid=invalid):
                (other / "settings.json").write_text(invalid, encoding="utf-8")
                with self.assertRaises(SystemExit):
                    configure_vscode.prepare_copilot_chat_migration(self.config, False)
                self.assertEqual(self.settings_path.read_text(), self.original)

    def test_cli_mode_bypasses_normal_setup_and_settings_sync(self):
        with (
            patch.object(sys, "argv", [
                "configure-vscode.py", "--copilot-chat-migration", "--dry-run"
            ]),
            patch("configure_vscode.load_json", return_value=self.config),
            patch(
                "configure_vscode.prepare_copilot_chat_migration", return_value=1
            ) as prepare,
            patch("configure_vscode.build_settings") as build,
            patch("configure_vscode.sync_settings") as sync,
        ):
            self.assertEqual(configure_vscode.main(), 1)
        prepare.assert_called_once_with(self.config, True)
        build.assert_not_called()
        sync.assert_not_called()


class CopilotChatMigrationCliTests(unittest.TestCase):
    def test_disposable_profile_audit_apply_and_second_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "profile"
            profile.mkdir()
            settings = profile / "settings.json"
            settings.write_text('{"editor.fontSize": 17}\n', encoding="utf-8")
            storage = profile / "globalStorage"
            storage.mkdir()
            state = storage / "state.vscdb"
            state.write_bytes(b"existing state must not be read or rewritten")
            config = json.loads(configure_vscode.DEFAULT_CONFIG.read_text())
            config["user"]["vscode"]["profiles"] = ["test"]
            for os_key in ("windows", "macos", "linux"):
                config["advanced"]["vscode"]["profileDirectories"][os_key] = {
                    "test": str(profile)
                }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            env = os.environ.copy()
            env.pop("DEVSETUP_STATUS_LOG", None)
            env.update(NO_COLOR="1", COPILOT_HOME=str(root / "copilot"))
            command = [
                sys.executable, str(SOURCE), "--config", str(config_path),
                "--copilot-chat-migration",
            ]

            def snapshot():
                return {
                    path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in root.rglob("*") if path.is_file()
                }

            def run(*options):
                result = subprocess.run(
                    [*command, *options], env=env, capture_output=True, text=True,
                    timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Not Assessed", result.stdout)
                return result.stdout

            before = snapshot()
            run("--dry-run")
            self.assertEqual(snapshot(), before)
            first = run()
            self.assertIn("[install]", first)
            self.assertEqual(json.loads(settings.read_text()), {
                "editor.fontSize": 17,
                "chat.sessionSync.enabled": True,
                "github.copilot.chat.localIndex.enabled": True,
            })
            self.assertEqual(state.read_bytes(), before[state.relative_to(root)][0])
            self.assertFalse((root / "copilot").exists())
            prepared = snapshot()
            second = run()
            self.assertEqual(snapshot(), prepared)
            self.assertNotIn("[install]", second)
            self.assertNotIn("[warn]", second)


class SyncOrderingTests(unittest.TestCase):
    def run_main(self, arguments=(), validation_error=False):
        events = []
        config = {"user": {"install": {"devcontainerDefaults": False}}}
        patches = [
            patch.object(sys, "argv", ["configure-vscode.py", *arguments]),
            patch("configure_vscode.load_json", return_value=config),
            patch("configure_vscode.profile_dirs", return_value=[]),
            patch("configure_vscode.status"),
        ]
        for name in ("manage_terminal_instructions", "manage_extensions", "manage_mcp",
                     "manage_copilot_mcp", "validate_install", "sync_settings"):
            def record(*args, name=name):
                events.append(name)
                if name == "validate_install" and validation_error:
                    raise SystemExit("validation failed")
                return True
            patches.append(patch(f"configure_vscode.{name}", side_effect=record))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        if validation_error:
            with self.assertRaisesRegex(SystemExit, "validation failed"):
                configure_vscode.main()
        else:
            self.assertEqual(configure_vscode.main(), 0)
        return events

    def test_sync_runs_after_all_managers_and_validation(self):
        self.assertEqual(self.run_main(), [
            "manage_terminal_instructions", "manage_extensions", "manage_mcp",
            "manage_copilot_mcp", "validate_install", "sync_settings",
        ])

    def test_cli_skip_flag_preserves_setup_but_never_requests_sync(self):
        events = self.run_main(["--skip-settings-sync"])
        self.assertIn("validate_install", events)
        self.assertNotIn("sync_settings", events)

    def test_validation_failure_prevents_sync(self):
        self.assertNotIn("sync_settings", self.run_main(validation_error=True))


class TerminalInstructionsTests(unittest.TestCase):
    def test_audit_apply_idempotency_and_preservation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            user_dir = Path(temp_dir)
            path = user_dir / "prompts" / "terminal-execution.instructions.md"
            with patch("configure_vscode.profile_targets", return_value=[("test", user_dir)]):
                configure_vscode.manage_terminal_instructions({}, dry_run=True)
                self.assertFalse(path.exists())
                configure_vscode.manage_terminal_instructions({}, dry_run=False)
                original = path.read_text(encoding="utf-8")
                self.assertIn('applyTo: "**"', original)
                self.assertIn("Never close, reload, or restart VS Code", original)
                self.assertIn("do not wait for them to exit", original)
                before = path.stat().st_mtime_ns
                configure_vscode.manage_terminal_instructions({}, dry_run=False)
                self.assertEqual(path.stat().st_mtime_ns, before)
                path.write_text("User-authored instructions\n", encoding="utf-8")
                configure_vscode.manage_terminal_instructions({}, dry_run=False)
                self.assertEqual(path.read_text(), "User-authored instructions\n")

    def test_disabled_instruction_management_writes_nothing(self):
        with patch("configure_vscode.profile_targets") as targets:
            configure_vscode.manage_terminal_instructions(
                {"user": {"vscode": {"terminalInstructions": {"manage": False}}}},
                dry_run=False,
            )
            targets.assert_not_called()


class CliDeadlineTests(unittest.TestCase):
    def test_default_deadline_is_finite_and_explicit(self):
        with patch("configure_vscode.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
            self.assertEqual(configure_vscode.run_cli("code", "--sync", "on"), (0, "ok"))
            self.assertEqual(run.call_args.kwargs["timeout"], 120)
            self.assertFalse(run.call_args.kwargs["check"])

    def test_actual_timeout_is_not_reported_as_success(self):
        with self.assertRaisesRegex(SystemExit, "exceeded 1s"):
            configure_vscode.run_cli(
                sys.executable, "-c", "import time; time.sleep(5)", timeout=1
            )

    def test_extension_install_has_longer_but_bounded_deadline(self):
        config = {"user": {"vscode": {"extensions": {"install": ["example.extension"]}}}}
        with (
            patch("configure_vscode.code_cli_targets", return_value=[("test", "code", "code")]),
            patch("configure_vscode.installed_extensions", return_value=set()),
            patch("configure_vscode.run_cli", return_value=(0, "")) as run,
        ):
            configure_vscode.manage_extensions(config, dry_run=False)
            self.assertEqual(run.call_args.kwargs["timeout"], 600)
            self.assertFalse(run.call_args.kwargs["capture_output"])


if __name__ == "__main__":
    unittest.main()
