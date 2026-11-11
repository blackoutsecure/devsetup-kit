#!/usr/bin/env python3
"""Apply dev-setup's VS Code settings from config/dev-setup.config.json.

Cross-platform so Windows, macOS, and Linux share one implementation and one
settings payload. Writes to VS Code's syncable user profile, so with Settings
Sync enabled the result follows the signed-in GitHub account to other machines.

Dev containers stay opt-in: nothing here creates a .devcontainer folder or puts
a workspace into a container. The dev container keys are the defaults VS Code
applies *if* a container is built.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "dev-setup.config.json"

OS_KEYS = {"Windows": "windows", "Darwin": "macos"}
COPILOT_MCP_FIELDS = {"type", "command", "args", "env", "url", "headers", "tools"}
VSCODE_MCP_VARIABLE = re.compile(
    r"\$\{(?:input|config|command|env):"
    r"|\$\{(?:workspaceFolder|workspaceRoot|workspaceFolderBasename|"
    r"workspaceRootFolderName|cwd|pathSeparator)\}"
)


_SEV_COLOR = {
    "found": "\033[32m",    # green  - already satisfied
    "install": "\033[36m", # cyan   - change in progress
    "warn": "\033[33m",    # yellow - degraded but proceeded
    "skip": "\033[90m",    # grey   - disabled or n/a
}
_RESET = "\033[0m"


def _color_enabled() -> bool:
    """Match the NO_COLOR / GITHUB_ACTIONS / TTY rules used across the toolkit."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return True
    return sys.stdout.isatty()


def status(state: str, component: str, detail: str = "") -> None:
    """Match the audit line format used by config.ps1 and config.sh."""
    tag = f"{'[' + state + ']':<9}"
    color = _SEV_COLOR.get(state)
    if color and _color_enabled():
        tag = f"{color}{tag}{_RESET}"
    print(f"  {tag} {component:<8} {detail}")

    # DEVSETUP_STATUS_LOG lets the top-level runner (setup.ps1 / setup.sh) tally
    # every line, including these, even though this script runs in its own process.
    log_path = os.environ.get("DEVSETUP_STATUS_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{state}|{component}|{detail}\n")


def get(config: dict, key: str, default: Any = None) -> Any:
    """Look up a dotted path, falling back when absent, null, or blank."""
    node: Any = config
    for segment in key.split("."):
        if not isinstance(node, dict) or segment not in node:
            return default
        node = node[segment]
    if node is None or node == "":
        return default
    return node


def is_elevated() -> bool:
    if os.name == "nt":
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


def enforce_execution_mode(dry_run: bool) -> None:
    admin_mode = os.environ.get("DEVSETUP_ADMIN_MODE") or "0"
    if admin_mode not in ("0", "1"):
        raise SystemExit(
            "DEVSETUP_ADMIN_MODE must be 0 (standard user, the default) "
            "or 1 (explicit admin opt-in)."
        )
    if not is_elevated():
        return
    if dry_run:
        status("warn", "Execution mode", "elevated read-only inspection; no configuration changes")
    elif admin_mode == "1":
        status(
            "warn", "Execution mode",
            "explicit admin mode enabled; child processes inherit elevation; "
            "configuration scope remains per-user",
        )
    else:
        raise SystemExit(
            "Run this script from a standard, non-admin shell. To explicitly permit "
            "an already-elevated shell for this run, set DEVSETUP_ADMIN_MODE=1. "
            "No automatic elevation or de-elevation is performed."
        )


def strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments and trailing commas, ignoring string literals."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return {}
    try:
        return json.loads(strip_jsonc(raw))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON/JSONC: {exc}") from exc


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def profile_dirs(config: dict) -> list[Path]:
    """Resolve the configured VS Code profiles for this OS."""
    return [path for _, path in profile_targets(config)]


def profile_targets(config: dict) -> list[tuple[str, Path]]:
    """Resolve the configured VS Code profile names and directories for this OS."""
    os_key = OS_KEYS.get(platform.system(), "linux")
    configured = get(config, f"advanced.vscode.profileDirectories.{os_key}", {})
    wanted = get(config, "user.vscode.profiles", ["stable", "insiders"])
    return [
        (name, Path(os.path.expandvars(configured[name])))
        for name in wanted
        if name in configured
    ]


def build_settings(
    config: dict,
    git_path: str | None,
    python_path: str | None,
    php_path: str | None,
    powershell_path: str | None,
) -> dict:
    settings: dict[str, Any] = {}
    settings.update(get(config, "advanced.vscode.settings", {}))
    settings[
        get(
            config,
            "advanced.vscode.managedSettingKeys.pythonGlobalModuleInstallation",
            "python.globalModuleInstallation",
        )
    ] = bool(get(config, "user.python.allowGlobalPackageInstalls", False))

    if get(config, "user.install.devcontainerDefaults", True):
        features = dict(get(config, "user.devcontainers.features", {}))
        access = get(config, "user.devcontainers.dockerAccess", "outside-of-docker")
        docker = get(config, f"advanced.devcontainers.dockerAccessFeatures.{access}")
        if docker is None:
            raise SystemExit(
                f"user.devcontainers.dockerAccess '{access}' has no matching entry "
                "in advanced.devcontainers.dockerAccessFeatures."
            )
        features.update(docker)

        feature_key = get(
            config,
            "advanced.devcontainers.settingKeys.features",
            "dev.containers.defaultFeatures",
        )
        extension_key = get(
            config,
            "advanced.devcontainers.settingKeys.extensions",
            "dev.containers.defaultExtensions",
        )
        settings[feature_key] = features
        settings[extension_key] = get(config, "user.devcontainers.extensions", [])
        settings.update(get(config, "user.devcontainers.settings", {}))

    # Machine-local paths: never written unless the caller resolved them.
    if git_path:
        settings[get(config, "advanced.vscode.managedSettingKeys.gitPath", "git.path")] = git_path
    if python_path:
        settings[
            get(
                config,
                "advanced.vscode.managedSettingKeys.pythonInterpreter",
                "python.defaultInterpreterPath",
            )
        ] = python_path
    if php_path:
        settings[
            get(
                config,
                "advanced.vscode.managedSettingKeys.phpValidator",
                "php.validate.executablePath",
            )
        ] = php_path
    if powershell_path:
        settings[
            get(
                config,
                "advanced.vscode.managedSettingKeys.powerShellAdditionalExePaths",
                "powershell.powerShellAdditionalExePaths",
            )
        ] = [powershell_path]

    auto_accept_delay = get(config, "user.vscode.copilot.autoAcceptDelay", 1)
    if (
        isinstance(auto_accept_delay, bool)
        or not isinstance(auto_accept_delay, (int, float))
        or not 0 <= auto_accept_delay <= 100
    ):
        raise SystemExit(
            "user.vscode.copilot.autoAcceptDelay must be a number from 0 to 100 "
            "seconds; 0 disables automatic Keep."
        )
    settings["chat.editing.autoAcceptDelay"] = auto_accept_delay
    if get(config, "user.vscode.copilot.autopilot", False):
        settings["chat.permissions.default"] = "autopilot"
        settings["chat.defaultConfiguration"] = {
            "mode": "autopilot",
            "approvals": "allowAll",
        }
    if get(config, "user.vscode.copilot.fusion", False):
        settings["chat.copilot.ensemble.enabled"] = True
        settings["chat.copilot.hydraFusion.enabled"] = "v2"
    # User overrides win over everything above.
    settings.update(get(config, "user.vscode.settings", {}))
    return settings


def build_snippet(config: dict) -> tuple[str, str, dict] | None:
    if not get(config, "user.install.devcontainerDefaults", True):
        return None
    snippet_file = get(config, "advanced.devcontainers.snippet.file", "jsonc.json")
    name = get(config, "advanced.devcontainers.snippet.name", "Dev container")
    prefix = get(config, "advanced.devcontainers.snippet.prefix", "devcontainer")
    image = get(
        config,
        "user.devcontainers.baseImage",
        "mcr.microsoft.com/devcontainers/base:ubuntu-24.04",
    )
    remote_user = get(config, "user.devcontainers.remoteUser", "vscode")
    body = {
        "prefix": prefix,
        "description": (
            "Minimal dev container. Shared tooling comes from "
            "dev.containers.defaultFeatures / defaultExtensions in user settings."
        ),
        "body": [
            "{",
            '  "name": "${1:dev}",',
            f'  "image": "{image}",',
            '  "features": {',
            "    ${2}",
            "  },",
            f'  "remoteUser": "{remote_user}",',
            '  "postCreateCommand": "${3:echo ready}"',
            "}",
        ],
    }
    return snippet_file, name, body


def apply(user_dir: Path, settings: dict, snippet, dry_run: bool) -> bool:
    verb = "would set" if dry_run else "set"
    changes: list[str] = []

    settings_path = user_dir / "settings.json"
    current = load_json(settings_path)
    for key, value in settings.items():
        if key.startswith("[") and key.endswith("]") and isinstance(value, dict):
            existing = current.get(key, {})
            if isinstance(existing, dict):
                value = {**existing, **value}
        if current.get(key) != value:
            current[key] = value
            changes.append(key)

    snippets_path = None
    snippets: dict = {}
    if snippet:
        snippet_file, name, body = snippet
        snippets_path = user_dir / "snippets" / snippet_file
        snippets = load_json(snippets_path)
        if snippets.get(name) != body:
            snippets[name] = body
            changes.append(f"snippet {name!r}")

    if not changes:
        status("found", "vscode", f"already up to date ({user_dir})")
        return False

    status("install", "vscode", f"{verb} {len(changes)} setting(s) in {user_dir}")
    for name in changes:
        print(f"             - {name}")

    if not dry_run:
        write_json(settings_path, current)
        if snippets_path is not None:
            write_json(snippets_path, snippets)
    return True


def assert_no_overlap(wanted, blocked, kind: str, setting: str) -> None:
    """Listing something as both wanted and blocked is ambiguous, so fail loudly."""
    overlap = sorted(set(wanted) & set(blocked))
    if overlap:
        raise SystemExit(
            f"These {kind} are in both {setting} and .block: {', '.join(overlap)}"
        )


def run_cli(
    cli: str, *args: str, timeout: int = 120, capture_output: bool = True,
    redact_output: bool = False,
) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [cli, *args], capture_output=capture_output, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        if not redact_output:
            for output in (exc.stdout, exc.stderr):
                if output:
                    print(output.decode(errors="replace") if isinstance(output, bytes) else output)
        raise SystemExit(
            f"VS Code CLI exceeded {timeout}s: {cli} {' '.join(args)}. "
            "The CLI was stopped; VS Code was not closed. Check the terminal "
            "before retrying; a timeout does not prove Settings Sync completed."
        ) from exc
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def find_code_cli(config: dict, profile: str, command: str) -> str | None:
    """Fall back to well-known install locations when the CLI shim isn't on PATH."""
    cli = shutil.which(command)
    if cli:
        return cli
    os_key = OS_KEYS.get(platform.system(), "linux")
    if os_key == "windows":
        return None
    candidates = get(config, f"advanced.vscode.extensionCliFallbackPaths.{profile}.{os_key}", [])
    for candidate in candidates:
        path = os.path.expanduser(os.path.expandvars(candidate))
        if os.access(path, os.X_OK):
            return path
    return None


def code_cli_targets(config: dict, component: str = "ext") -> list[tuple[str, str, str]]:
    clis = get(config, "advanced.vscode.extensionCli", {})
    targets = []
    for profile in get(config, "user.vscode.profiles", ["stable", "insiders"]):
        command = clis.get(profile)
        if not command:
            continue
        cli = find_code_cli(config, profile, command)
        if cli:
            targets.append((profile, command, cli))
        else:
            status("skip", component, f"'{command}' CLI not on PATH ({profile})")
    return targets


def extension_plan(config: dict, installed: set[str]) -> tuple[list[str], list[str]]:
    wanted = [e.lower() for e in get(config, "user.vscode.extensions.install", [])]
    blocked = [e.lower() for e in get(config, "user.vscode.extensions.block", [])]
    return (
        [e for e in wanted if e not in installed],
        [e for e in blocked if e in installed],
    )


def installed_extensions(command: str, cli: str) -> set[str]:
    code, output = run_cli(cli, "--list-extensions")
    if code != 0:
        raise RuntimeError(f"{command} --list-extensions failed")
    return {line.strip().lower() for line in output.splitlines() if line.strip()}


def manage_extensions(config: dict, dry_run: bool) -> None:
    """Install the recommended extensions and report or remove blocked ones."""
    if not get(config, "user.vscode.extensions.manage", True):
        status("skip", "ext", "user.vscode.extensions.manage is false")
        return

    wanted = [e.lower() for e in get(config, "user.vscode.extensions.install", [])]
    blocked = [e.lower() for e in get(config, "user.vscode.extensions.block", [])]
    uninstall_blocked = get(config, "user.vscode.extensions.uninstallBlocked", False)

    assert_no_overlap(wanted, blocked, "extensions", "user.vscode.extensions.install")
    if not wanted and not blocked:
        return

    for profile, command, cli in code_cli_targets(config):
        try:
            installed = installed_extensions(command, cli)
        except RuntimeError:
            status("warn", "ext", f"{command} --list-extensions failed ({profile})")
            continue
        missing, present_blocked = extension_plan(config, installed)

        if not missing:
            status("found", "ext", f"all {len(wanted)} recommended present ({profile})")
        for ext in missing:
            if dry_run:
                status("install", "ext", f"would install {ext} ({profile})")
                continue
            status("install", "ext", f"installing {ext} ({profile}); deadline 600s")
            code, output = run_cli(
                cli, "--install-extension", ext, "--force", timeout=600, capture_output=False
            )
            if code == 0:
                status("install", "ext", f"installed {ext} ({profile})")
            else:
                status("warn", "ext", f"failed to install {ext}: {output.strip()[:120]}")

        for ext in present_blocked:
            if not uninstall_blocked:
                status("warn", "ext", f"{ext} is blocked but installed ({profile})")
                continue
            if dry_run:
                status("install", "ext", f"would uninstall blocked {ext} ({profile})")
                continue
            code, output = run_cli(
                cli, "--uninstall-extension", ext, timeout=600, capture_output=False
            )
            if code == 0:
                status("install", "ext", f"uninstalled blocked {ext} ({profile})")
            else:
                status("warn", "ext", f"failed to uninstall {ext}: {output.strip()[:120]}")


def validate_extensions(config: dict) -> None:
    """Confirm recommended extensions are installed where the matching CLI exists."""
    if not get(config, "user.vscode.extensions.manage", True):
        status("skip", "validate", "extension management is disabled")
        return

    uninstall_blocked = get(config, "user.vscode.extensions.uninstallBlocked", False)

    for profile, command, cli in code_cli_targets(config, "validate"):
        try:
            installed = installed_extensions(command, cli)
        except RuntimeError:
            raise SystemExit(f"{command} --list-extensions failed during validation")
        missing, present_blocked = extension_plan(config, installed)
        if missing:
            raise SystemExit(
                f"Missing recommended extension(s) for {profile}: {', '.join(missing)}"
            )

        if uninstall_blocked and present_blocked:
            raise SystemExit(
                f"Blocked extension(s) still installed for {profile}: "
                f"{', '.join(present_blocked)}"
            )
        status("found", "validate", f"extensions ok ({profile})")


def validate_profiles(config: dict, settings: dict, snippet) -> None:
    """Reread managed VS Code profile files and fail before sync if they drifted."""
    targets = [target for target in profile_targets(config) if target[1].is_dir()]
    if not targets:
        status("skip", "validate", "no VS Code user profile found on this machine")
        return

    for profile, user_dir in targets:
        settings_path = user_dir / "settings.json"
        current = load_json(settings_path)
        mismatched = []
        for key, value in settings.items():
            actual = current.get(key)
            if key.startswith("[") and key.endswith("]") and isinstance(value, dict) and isinstance(actual, dict):
                if all(actual.get(name) == expected for name, expected in value.items()):
                    continue
            if actual != value:
                mismatched.append(key)
        if mismatched:
            raise SystemExit(
                f"VS Code settings validation failed for {profile}: "
                f"{', '.join(mismatched)}"
            )

        if snippet:
            snippet_file, name, body = snippet
            snippets_path = user_dir / "snippets" / snippet_file
            snippets = load_json(snippets_path)
            if snippets.get(name) != body:
                raise SystemExit(f"VS Code snippet validation failed for {profile}: {name}")

        status("found", "validate", f"settings ok ({profile})")


def validate_mcp(config: dict) -> None:
    """Confirm configured MCP servers and inputs are present after reconciliation."""
    if not get(config, "user.install.mcpServers", True) or not get(
        config, "user.mcp.manage", True
    ):
        status("skip", "validate", "MCP management is disabled")
        return

    servers = get(config, "user.mcp.servers", {})
    inputs = get(config, "user.mcp.inputs", [])
    filename = get(config, "advanced.vscode.mcpFileName", "mcp.json")
    validate_profile_filename(filename, "advanced.vscode.mcpFileName")
    targets = [target for target in profile_targets(config) if target[1].is_dir()]
    if not targets:
        return

    for profile, user_dir in targets:
        current = load_json(user_dir / filename)
        existing, current_inputs = current_mcp_state(current)
        missing = missing_mcp_servers(profile_mcp_servers(servers, user_dir), existing)
        if missing:
            raise SystemExit(
                f"MCP validation failed for {profile}; missing server(s): "
                f"{', '.join(missing)}"
            )

        missing_inputs = missing_mcp_inputs(inputs, current_inputs)
        if missing_inputs:
            raise SystemExit(
                f"MCP validation failed for {profile}; missing input(s): "
                f"{', '.join(missing_inputs)}"
            )

        status("found", "validate", f"MCP ok ({profile})")


def current_mcp_state(current: dict) -> tuple[dict, list]:
    return current.get("servers") or {}, current.get("inputs") or []


def missing_mcp_servers(servers: dict, existing: dict) -> list[str]:
    return [name for name in servers if name not in existing]


def missing_mcp_inputs(inputs: list, current_inputs: list) -> list[str]:
    known = {i.get("id") for i in current_inputs}
    return [i.get("id") for i in inputs if i.get("id") not in known]


def contains_vscode_mcp_variable(value: Any) -> bool:
    if isinstance(value, str):
        return bool(VSCODE_MCP_VARIABLE.search(value))
    if isinstance(value, dict):
        return any(contains_vscode_mcp_variable(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_vscode_mcp_variable(item) for item in value)
    return False


def copilot_mcp_server(server: Any) -> dict | None:
    """Return a portable Copilot server or None when VS Code-specific data is required."""
    if not isinstance(server, dict):
        return None
    if set(server) - COPILOT_MCP_FIELDS:
        return None
    if server.get("type") not in {"stdio", "http"}:
        return None
    if contains_vscode_mcp_variable(server):
        return None

    portable = dict(server)
    portable.setdefault("tools", ["*"])
    return portable


def copilot_mcp_config_path() -> Path:
    """Resolve the Copilot user config, honoring COPILOT_HOME when set."""
    copilot_home = os.environ.get("COPILOT_HOME")
    root = (
        Path(os.path.expandvars(copilot_home)).expanduser()
        if copilot_home
        else Path.home() / ".copilot"
    )
    return root / "mcp-config.json"


def customization_migration_record(user_dir: Path) -> dict:
    path = copilot_mcp_config_path().with_name("devsetup-agent-migrations.json")
    state = load_json(path)
    if not isinstance(state, dict) or not isinstance(state.get("profiles", {}), dict):
        raise SystemExit(f"{path} must contain a JSON object with a profiles object.")
    record = state.get("profiles", {}).get(str(user_dir.resolve()), {})
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("mcpServers", []), list)
        or any(not isinstance(name, str) for name in record.get("mcpServers", []))
        or not isinstance(record.get("terminalInstructions", False), bool)
    ):
        raise SystemExit(f"Invalid customization migration record for {user_dir}.")
    return record


def profile_mcp_servers(servers: dict, user_dir: Path) -> dict:
    migrated = set(customization_migration_record(user_dir).get("mcpServers", []))
    if migrated.intersection(servers):
        path = copilot_mcp_config_path()
        runtime = current_copilot_mcp_servers(load_json(path), path)
        missing = migrated.intersection(servers).difference(runtime)
        if missing:
            raise SystemExit(
                f"Migrated Copilot MCP server(s) missing from {path}: {', '.join(sorted(missing))}"
            )
    return {name: server for name, server in servers.items() if name not in migrated}


def migration_file_bytes(path: Path) -> bytes | None:
    if path.is_symlink():
        raise SystemExit(f"Refusing to migrate a symbolic-link file: {path}")
    return path.read_bytes() if path.exists() else None


def write_migration_bytes(path: Path, content: bytes, expected: bytes | None) -> None:
    if migration_file_bytes(path) != expected:
        raise SystemExit(f"Migration file changed; preserved current content: {path}")
    if content == expected:
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".devsetup-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        if migration_file_bytes(path) != expected:
            raise SystemExit(f"Migration file changed before writing: {path}")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def migrate_agent_customizations(config: dict, profile: str, dry_run: bool) -> int:
    """Move supported user customizations, retaining private recovery copies."""
    for key in (
        "user.install.vscodeSettings", "user.install.mcpServers", "user.mcp.manage",
        "user.mcp.copilotConfig.manage", "user.vscode.terminalInstructions.manage",
    ):
        if not get(config, key, True):
            status("skip", "migrations", f"Not Assessed: {key} is disabled")
            return 1
    targets = dict(profile_targets(config))
    user_dir = targets.get(profile)
    if user_dir is None or not user_dir.is_dir():
        status("skip", "migrations", f"Not Assessed: no existing configured profile {profile!r}")
        return 1

    filename = get(config, "advanced.vscode.mcpFileName", "mcp.json")
    validate_profile_filename(filename, "advanced.vscode.mcpFileName")
    source_mcp = user_dir / filename
    target_mcp = copilot_mcp_config_path()
    state_path = target_mcp.with_name("devsetup-agent-migrations.json")
    source_instruction = user_dir / "prompts" / "terminal-execution.instructions.md"
    target_instruction = target_mcp.parent / "instructions" / source_instruction.name
    if len({
        path.resolve()
        for path in (source_mcp, target_mcp, state_path, source_instruction, target_instruction)
    }) != 5:
        raise SystemExit("Migration source and destination paths must not overlap.")
    originals = {
        path: migration_file_bytes(path)
        for path in (source_mcp, target_mcp, state_path, source_instruction, target_instruction)
    }
    source = load_json(source_mcp)
    if not isinstance(source, dict) or not isinstance(source.get("servers", {}), dict):
        raise SystemExit(f"{source_mcp} must contain a servers object.")
    destination = load_json(target_mcp)
    runtime = current_copilot_mcp_servers(destination, target_mcp)
    record = dict(customization_migration_record(user_dir))
    migrated = set(record.get("mcpServers", []))
    compatible = copilot_mcp_servers(config)
    retire: list[str] = []
    for name in get(config, "user.mcp.servers", {}):
        if name not in source.get("servers", {}):
            if name in compatible and name in runtime:
                migrated.add(name)
            continue
        portable = copilot_mcp_server(source["servers"][name])
        if name not in compatible or portable is None:
            raise SystemExit(
                f"Use VS Code's native Migrate action for {name}; "
                "VS Code-only configuration cannot be safely copied."
            )
        if name in runtime and copilot_mcp_server(runtime[name]) != portable:
            raise SystemExit(f"MCP migration target conflict for {name}; nothing was overwritten.")
        runtime.setdefault(name, portable)
        migrated.add(name)
        retire.append(name)

    instruction = originals[source_instruction]
    if (
        instruction is not None and originals[target_instruction] is not None
        and instruction != originals[target_instruction]
    ):
        raise SystemExit("Instruction migration target conflict; nothing was overwritten.")
    has_instruction = instruction is not None or originals[target_instruction] is not None
    if record.get("terminalInstructions") and not has_instruction:
        raise SystemExit(f"Migrated terminal instructions missing: {target_instruction}")
    missing = migrated.difference(runtime)
    if missing:
        raise SystemExit(f"Migrated MCP server(s) missing: {', '.join(sorted(missing))}")
    if not migrated and not has_instruction:
        status("skip", "migrations", "Not Assessed: no supported configured customizations found")
        return 1
    for path, content in originals.items():
        if migration_file_bytes(path) != content:
            raise SystemExit(f"Migration source or target changed during audit: {path}")

    destination["mcpServers"] = runtime
    record.update(mcpServers=sorted(migrated), terminalInstructions=has_instruction)
    state = load_json(state_path)
    state.setdefault("profiles", {})[str(user_dir.resolve())] = record
    state_bytes = (json.dumps(state, indent=4) + "\n").encode("utf-8")
    target_bytes = (json.dumps(destination, indent=4) + "\n").encode("utf-8")
    existing_target = originals[target_mcp]
    if existing_target is not None and load_json(target_mcp) == destination:
        target_bytes = existing_target
    pending = len(retire) + int(instruction is not None)
    changed = (
        pending or state_bytes != originals[state_path]
        or (migrated and target_bytes != originals[target_mcp])
    )
    if dry_run:
        status("install" if changed else "found", "migrations",
               f"{'would migrate' if changed else 'already migrated'} {pending} source item(s) "
               f"from {profile}; private backups precede source retirement")
        status("skip", "MCP trust", "VS Code will request trust again; no trust is granted automatically")
        return 0
    if not changed:
        status("found", "migrations", f"customizations already migrated ({profile}); no files changed")
        return 0

    backup_root = target_mcp.parent / "migration-backups"
    target_mcp.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_root.mkdir(mode=0o700, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="agent-customizations-", dir=backup_root))
    for path, name in (
        (source_mcp, "source-mcp.json"),
        (source_instruction, "source-terminal-execution.instructions.md"),
        (target_mcp, "target-mcp-config.json"),
        (target_instruction, "target-terminal-execution.instructions.md"),
        (state_path, "migration-state.json"),
    ):
        original = originals[path]
        if original is not None:
            write_migration_bytes(backup / name, original, None)
    if migrated:
        write_migration_bytes(target_mcp, target_bytes, originals[target_mcp])
        if load_json(target_mcp) != destination:
            raise SystemExit("MCP migration target validation failed; sources were retained.")
    if instruction is not None:
        write_migration_bytes(target_instruction, instruction, originals[target_instruction])
        if target_instruction.read_bytes() != instruction:
            raise SystemExit("Instruction migration target validation failed; source was retained.")
    # Record runtime ownership before retiring sources, so setup cannot recreate them.
    write_migration_bytes(state_path, state_bytes, originals[state_path])
    if retire:
        for name in retire:
            del source["servers"][name]
        write_migration_bytes(
            source_mcp, (json.dumps(source, indent=4) + "\n").encode("utf-8"),
            originals[source_mcp],
        )
    if instruction is not None:
        if migration_file_bytes(source_instruction) != instruction:
            raise SystemExit("Instruction source changed; retained it and the verified target.")
        source_instruction.unlink()
    if source_instruction.exists() or any(
        name in load_json(source_mcp).get("servers", {}) for name in retire
    ):
        raise SystemExit("Source retirement validation failed; inspect migration backups.")
    status("found", "migrations", f"migrated {pending} source item(s) ({profile}); backups: {backup}")
    status("skip", "MCP trust", "VS Code must request trust again; approve it yourself in the UI")
    return 0


def current_copilot_mcp_servers(current: dict, path: Path) -> dict:
    if not isinstance(current, dict):
        raise SystemExit(f"{path} must contain a JSON object.")
    servers = current.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise SystemExit(f"{path} must contain an object named 'mcpServers'.")
    return servers


def copilot_mcp_servers(config: dict) -> dict[str, dict]:
    """Select servers that can be represented without VS Code-only values."""
    servers = get(config, "user.mcp.servers", {})
    blocked = get(config, "user.mcp.block", [])
    if not isinstance(servers, dict) or not isinstance(blocked, list):
        raise SystemExit("user.mcp.servers must be an object and user.mcp.block a list.")
    assert_no_overlap(servers, blocked, "MCP servers", "user.mcp.servers")

    compatible: dict[str, dict] = {}
    for name, server in servers.items():
        if name in blocked:
            continue
        portable = copilot_mcp_server(server)
        if portable is not None:
            compatible[name] = portable
    return compatible


def manage_copilot_mcp(config: dict, dry_run: bool) -> None:
    """Add portable configured MCP servers to the Copilot user config without overwrites."""
    if not get(config, "user.install.mcpServers", True) or not get(
        config, "user.mcp.manage", True
    ):
        status("skip", "Copilot MCP", "MCP management is disabled in config")
        return
    if not get(config, "user.mcp.copilotConfig.manage", True):
        status("skip", "Copilot MCP", "user.mcp.copilotConfig.manage is false")
        return

    compatible = copilot_mcp_servers(config)
    servers = get(config, "user.mcp.servers", {})
    blocked = get(config, "user.mcp.block", [])
    if not servers:
        return

    unsupported = [
        name for name in servers
        if name not in blocked and name not in compatible
    ]
    for name in unsupported:
        status(
            "warn",
            "Copilot MCP",
            f"skipped {name}; it needs VS Code-only fields or variables",
        )
    if not compatible:
        return

    path = copilot_mcp_config_path()
    current = load_json(path)
    existing = current_copilot_mcp_servers(current, path)
    added = missing_mcp_servers(compatible, existing)
    if not added:
        status(
            "found",
            "Copilot MCP",
            f"all {len(compatible)} compatible server(s) already configured",
        )
        return

    verb = "would add" if dry_run else "added"
    status("install", "Copilot MCP", f"{verb} {len(added)} server(s): {', '.join(added)}")
    if not dry_run:
        for name in added:
            existing[name] = compatible[name]
        current["mcpServers"] = existing
        write_json(path, current)


def validate_copilot_mcp(config: dict) -> None:
    if not get(config, "user.install.mcpServers", True) or not get(
        config, "user.mcp.manage", True
    ) or not get(
        config, "user.mcp.copilotConfig.manage", True
    ):
        status("skip", "validate", "Copilot MCP management is disabled")
        return

    compatible = copilot_mcp_servers(config)
    if not compatible:
        return

    path = copilot_mcp_config_path()
    current = load_json(path)
    existing = current_copilot_mcp_servers(current, path)
    missing = missing_mcp_servers(compatible, existing)
    if missing:
        raise SystemExit(
            f"Copilot MCP validation failed; missing server(s): {', '.join(missing)}"
        )
    status("found", "validate", f"Copilot MCP ok ({path})")


def validate_profile_filename(filename: str, setting: str) -> None:
    if (
        Path(filename).name != filename
        or any(separator in filename for separator in ("/", "\\"))
        or filename in {"", ".", ".."}
    ):
        raise SystemExit(f"{setting} must be a simple file name, got {filename!r}")


def validate_install(config: dict, settings: dict, snippet, dry_run: bool) -> bool:
    if dry_run:
        status("skip", "validate", "dry-run; files were not changed")
        return True

    validate_profiles(config, settings, snippet)
    validate_extensions(config)
    validate_mcp(config)
    validate_copilot_mcp(config)
    return True


def prepare_copilot_chat_migration(config: dict, dry_run: bool) -> int:
    """Prepare local sync preferences, leaving history verification to Copilot."""
    if not get(config, "user.install.vscodeSettings", True):
        status(
            "skip", "Copilot migration",
            "Not Assessed: VS Code settings management is disabled",
        )
        return 1

    configured = dict(get(config, "advanced.vscode.settings", {}))
    configured.update(get(config, "user.vscode.settings", {}))
    required = {
        key: configured.get(key)
        for key in (
            "chat.sessionSync.enabled",
            "github.copilot.chat.localIndex.enabled",
        )
    }
    disabled = [key for key, value in required.items() if value is not True]
    if disabled:
        status(
            "skip", "Copilot migration",
            "Not Assessed: explicitly enable these preferences in config after "
            f"reviewing upload privacy and organization policy: {', '.join(disabled)}",
        )
        return 1

    targets = [target for target in profile_targets(config) if target[1].is_dir()]
    if not targets:
        status(
            "skip", "Copilot migration",
            "Not Assessed: no configured VS Code user profile exists; "
            "open the intended VS Code build/profile first",
        )
        return 1

    # A malformed later profile must not leave earlier profiles partly prepared.
    for profile, user_dir in targets:
        path = user_dir / "settings.json"
        if not isinstance(load_json(path), dict):
            raise SystemExit(f"VS Code settings for {profile} must be a JSON object: {path}")

    for _, user_dir in targets:
        apply(user_dir, required, None, dry_run)
    if dry_run:
        status("skip", "validate", "dry-run; session-sync preferences were not changed")
    else:
        validate_profiles(config, required, None)

    status(
        "skip", "Copilot migration",
        "Not Assessed: history transfer requires the SOURCE/TARGET checks below. "
        "Local preference preparation is not migration completion.",
    )
    status(
        "skip", "migration source",
        "SOURCE: open Copilot with the intended GitHub.com account; check session "
        "sync status for N sessions synced, not Syncing, Sync error, or Disabled by policy.",
    )
    status(
        "skip", "migration target",
        "TARGET: repeat audit/preparation, sign in to the same Copilot account, "
        "open the repository checkout, and find and inspect a known SOURCE session. "
        "Keep the SOURCE until history is verified; Settings Sync is separate.",
    )
    status(
        "skip", "migration fallback",
        "For legacy/local-only chats, use native Chat: Export Chat... and "
        "Chat: Import Chat... JSON where supported, then verify the imported chat. "
        "No chat databases, credentials, workspace paths, or files are copied.",
    )
    return 0


def parse_state_bool(value: Any) -> bool:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def read_state_value(config: dict, user_dir: Path, key: str) -> Any:
    state_db = user_dir / get(
        config, "advanced.vscode.settingsSync.stateDbRelativePath", "globalStorage/state.vscdb"
    )
    if not state_db.is_file():
        return None
    try:
        with closing(sqlite3.connect(
            state_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
        )) as connection:
            row = connection.execute(
                "select value from ItemTable where key = ?", (key,)
            ).fetchone()
    except sqlite3.Error as exc:
        status(
            "warn", "VS Code User Sync",
            f"cannot read sync state from {state_db}: {exc}; sync will be skipped",
        )
        return None
    return None if row is None else row[0]


def sync_settings(config: dict, dry_run: bool) -> None:
    """Request sync last, only with enabled sync and a supported cached account."""
    sync_config = get(config, "user.vscode.settingsSync", {})
    if not get(sync_config, "syncAfterSetup", True):
        status("skip", "VS Code User Sync", "user.vscode.settingsSync.syncAfterSetup is false")
        return

    clis = get(config, "advanced.vscode.extensionCli", {})
    sync_keys = get(config, "advanced.vscode.settingsSync", {})
    enabled_key = get(sync_keys, "enabledKey", "sync.enable")
    provider_key = get(sync_keys, "accountProviderKey", "userDataSyncAccountProvider")
    account_key = get(sync_keys, "accountPreferenceKey", "userDataSyncAccountPreference")
    required_provider = get(sync_config, "requiredProvider", "github")
    cli_args = get(sync_keys, "syncCliArgs", ["--sync", "on"])

    for profile, user_dir in profile_targets(config):
        if not user_dir.is_dir():
            continue
        enabled = parse_state_bool(read_state_value(config, user_dir, enabled_key))
        provider = read_state_value(config, user_dir, provider_key)
        if isinstance(provider, bytes):
            provider = provider.decode("utf-8", errors="replace")
        provider = str(provider or "").strip().lower()

        if not enabled:
            status("skip", "VS Code User Sync", f"Settings Sync is not enabled ({profile})")
            continue
        if provider not in {"github", "microsoft"}:
            status("skip", "VS Code User Sync", f"unsupported or missing account provider ({profile})")
            continue
        if required_provider and provider != required_provider.lower():
            status("skip", "VS Code User Sync", f"provider is {provider or 'unknown'}, not {required_provider}")
            continue
        account = read_state_value(config, user_dir, account_key)
        if not account or (isinstance(account, (str, bytes)) and not account.strip()):
            status(
                "skip", "VS Code User Sync",
                f"no cached signed-in sync account ({profile}); sign in and enable Settings Sync in VS Code",
            )
            continue

        command = clis.get(profile)
        cli = find_code_cli(config, profile, command) if command else None
        if not cli:
            status("skip", "VS Code User Sync", f"'{command}' CLI not on PATH ({profile})")
            continue
        if dry_run:
            status(
                "found", "VS Code User Sync",
                f"{provider} Settings Sync enabled with a cached account ({profile}); "
                "dry-run; no sync request made",
            )
            continue

        code, output = run_cli(cli, *cli_args)
        if code == 0:
            status(
                "found", "VS Code User Sync",
                f"{provider} Settings Sync enabled; CLI enable request accepted ({profile}); "
                "VS Code must validate current authentication and complete cloud uploads; "
                "check Settings Sync: Show Synced Data. Copilot session uploads are separate.",
            )
        else:
            status("warn", "VS Code User Sync", f"sync request failed: {output.strip()[:120]}")


def manage_terminal_instructions(config: dict, dry_run: bool) -> None:
    """Install syncable personal instructions without replacing user-authored content."""
    if not get(config, "user.vscode.terminalInstructions.manage", True):
        status("skip", "instructions", "terminal instruction management is disabled")
        return
    template = (REPO_ROOT / "src" / "terminal-execution.instructions.md").read_text(
        encoding="utf-8"
    )
    for profile, user_dir in profile_targets(config):
        if not user_dir.is_dir():
            continue
        migrated = customization_migration_record(user_dir).get("terminalInstructions", False)
        path = (
            copilot_mcp_config_path().parent / "instructions" / "terminal-execution.instructions.md"
            if migrated
            else user_dir / "prompts" / "terminal-execution.instructions.md"
        )
        if migrated and not path.is_file():
            raise SystemExit(f"Migrated terminal instructions missing: {path}")
        if path.exists():
            if path.read_text(encoding="utf-8-sig") == template:
                status("found", "instructions", f"terminal instructions ok ({profile})")
            else:
                status(
                    "warn", "instructions",
                    f"preserved existing {path}; compare with src/terminal-execution.instructions.md "
                    "for bounded waits and restart-consent guidance",
                )
            continue
        status(
            "install", "instructions",
            f"{'would add' if dry_run else 'adding'} terminal instructions ({profile})",
        )
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template, encoding="utf-8")


def manage_mcp(config: dict, dry_run: bool) -> None:
    """Merge the configured MCP servers into each profile's mcp.json.

    Servers already present are left alone rather than overwritten, so a locally
    pinned version or an added env block survives a re-run.
    """
    if not get(config, "user.install.mcpServers", True) or not get(
        config, "user.mcp.manage", True
    ):
        status("skip", "mcp", "MCP management is disabled in config")
        return

    servers = get(config, "user.mcp.servers", {})
    inputs = get(config, "user.mcp.inputs", [])
    blocked = get(config, "user.mcp.block", [])
    remove_blocked = get(config, "user.mcp.removeBlocked", False)

    assert_no_overlap(servers, blocked, "MCP servers", "user.mcp.servers")
    if not servers and not blocked:
        return

    # An ${input:id} with no matching entry leaves VS Code prompting for nothing.
    referenced = set(re.findall(r"\$\{input:([A-Za-z0-9_-]+)\}", json.dumps(servers)))
    defined = {i.get("id") for i in inputs}
    if referenced - defined:
        raise SystemExit(
            "user.mcp.servers reference inputs that are not defined in "
            f"user.mcp.inputs: {', '.join(sorted(referenced - defined))}"
        )

    filename = get(config, "advanced.vscode.mcpFileName", "mcp.json")
    validate_profile_filename(filename, "advanced.vscode.mcpFileName")
    verb = "would add" if dry_run else "added"

    for user_dir in profile_dirs(config):
        if not user_dir.is_dir():
            continue
        path = user_dir / filename
        current = load_json(path)
        existing, current_inputs = current_mcp_state(current)

        added = missing_mcp_servers(profile_mcp_servers(servers, user_dir), existing)
        present_blocked = [name for name in blocked if name in existing]

        changed = False
        for name in added:
            existing[name] = servers[name]
            changed = True
        for name in present_blocked:
            if remove_blocked:
                del existing[name]
                changed = True
            else:
                status("warn", "mcp", f"{name} is blocked but configured")

        missing_inputs = set(missing_mcp_inputs(inputs, current_inputs))
        new_inputs = [i for i in inputs if i.get("id") in missing_inputs]
        if new_inputs:
            current_inputs.extend(new_inputs)
            changed = True

        if not changed:
            status("found", "mcp", f"all {len(servers)} server(s) already configured")
            continue

        if added:
            status("install", "mcp", f"{verb} {len(added)} server(s): {', '.join(added)}")
        if remove_blocked and present_blocked:
            status("install", "mcp", f"removed blocked: {', '.join(present_blocked)}")
        if new_inputs:
            status("install", "mcp", f"{verb} {len(new_inputs)} input definition(s)")

        if not dry_run:
            current["servers"] = existing
            if current_inputs:
                current["inputs"] = current_inputs
            write_json(path, current)


def audit_mcp_support(servers: dict, expected: dict, label: str) -> None:
    if not isinstance(expected, dict) or not isinstance(servers, dict):
        raise SystemExit(f"MCP support audit requires a server object ({label}).")
    status("found", "support", f"{label}: {len(servers)} configured MCP definition(s)")
    for name, definition in servers.items():
        if not isinstance(definition, dict):
            raise SystemExit(f"Invalid MCP definition for {name} ({label}).")
        kind = definition.get("type", "stdio" if "command" in definition else "")
        if kind == "stdio":
            command = definition.get("command")
            arguments = definition.get("args", [])
            if not isinstance(command, str) or not command or not isinstance(arguments, list):
                raise SystemExit(f"Invalid stdio MCP definition for {name} ({label}).")
            if not all(isinstance(argument, str) for argument in arguments):
                raise SystemExit(f"MCP arguments must be strings for {name} ({label}).")
            if shutil.which(os.path.expandvars(command)):
                status("found", "support", f"{name} ({label}): launcher available; server not started")
            else:
                status("warn", "support", f"{name} ({label}): launcher unavailable; no automatic installation")
        elif kind in ("http", "sse"):
            if not isinstance(definition.get("url"), str) or not definition["url"]:
                raise SystemExit(f"Missing MCP URL for {name} ({label}).")
            status("found", "support", f"{name} ({label}): remote definition; authentication/connectivity not tested")
        else:
            status("warn", "support", f"{name} ({label}): unsupported transport; review in its owning host")
        baseline = expected.get(name)
        if isinstance(baseline, dict) and any(
            definition.get(field) != baseline.get(field)
            for field in ("type", "command", "args", "url")
            if field in baseline
        ):
            status(
                "warn", "support",
                f"{name} ({label}): differs from kit baseline; existing pin/customization preserved",
            )
    for name in missing_mcp_servers(expected, servers):
        status("warn", "support", f"{name} ({label}): kit baseline definition is absent")


def audit_plugin_support() -> None:
    cli = shutil.which("copilot")
    if not cli:
        status("skip", "plugins", "Copilot CLI unavailable; inspect Agent Plugins in VS Code")
        return
    code, output = run_cli(cli, "plugin", "list", "--json", redact_output=True)
    if code != 0:
        raise SystemExit(
            "Copilot plugin inventory failed; use the installed client's plugin manager. "
            "Command output withheld because it can contain local configuration."
        )
    try:
        plugins = json.loads(output)
    except json.JSONDecodeError:
        raise SystemExit("Copilot plugin inventory did not return valid JSON; output withheld.") from None
    if not isinstance(plugins, list):
        raise SystemExit("Copilot plugin inventory must return an array.")
    enabled_count = 0
    marketplaces = set()
    for plugin in plugins:
        if (
            not isinstance(plugin, dict)
            or not isinstance(plugin.get("name"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", plugin["name"])
            or not isinstance(plugin.get("enabled"), bool)
            or not isinstance(plugin.get("version"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.+-]+", plugin["version"])
            or (
                plugin.get("marketplace") is not None
                and (
                    not isinstance(plugin["marketplace"], str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]*", plugin["marketplace"])
                )
            )
        ):
            raise SystemExit("Copilot plugin inventory contains invalid identity/version metadata; details withheld.")
        enabled_count += plugin["enabled"]
        if plugin.get("marketplace"):
            marketplaces.add(plugin["marketplace"])
        identity = plugin["name"] + (f"@{plugin['marketplace']}" if plugin.get("marketplace") else "")
        status(
            "found", "plugins",
            f"{identity} {plugin['version']}: "
            f"{'enabled' if plugin['enabled'] else 'disabled; left disabled'}",
        )
    if marketplaces:
        code, output = run_cli(
            cli, "plugin", "marketplace", "list", "--json", redact_output=True
        )
        if code != 0:
            raise SystemExit("Copilot marketplace inventory failed; command output withheld.")
        try:
            catalogues = json.loads(output)
        except json.JSONDecodeError:
            raise SystemExit("Copilot marketplace inventory did not return valid JSON; output withheld.") from None
        if not isinstance(catalogues, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", item["name"])
            for item in catalogues
        ):
            raise SystemExit("Copilot marketplace inventory contains invalid metadata; details withheld.")
        registered = {item["name"] for item in catalogues}
        for marketplace in sorted(marketplaces - registered):
            status(
                "warn", "plugins",
                f"{marketplace}: installed plugin marketplace is not registered; "
                "updates may be blocked; restore its reviewed source in the owning host",
            )
    status("found", "plugins", f"{len(plugins)} CLI-listed plugin(s), {enabled_count} enabled; not a VS Code cache count")
    status(
        "skip", "plugins",
        "provider-owned/synced caches are not modified; check VS Code Agent Customizations "
        "separately; no plugin updates or trust changes performed",
    )


def audit_support(config: dict) -> int:
    for profile, directory in profile_targets(config):
        if not directory.is_dir():
            status("skip", "support", f"{profile}: VS Code profile unavailable")
            continue
        filename = get(config, "advanced.vscode.mcpFileName", "mcp.json")
        validate_profile_filename(filename, "advanced.vscode.mcpFileName")
        current = load_json(directory / filename)
        servers = current.get("servers", {})
        expected = profile_mcp_servers(get(config, "user.mcp.servers", {}), directory)
        audit_mcp_support(servers, expected, profile)
    path = copilot_mcp_config_path()
    audit_mcp_support(
        current_copilot_mcp_servers(load_json(path), path), copilot_mcp_servers(config), "Copilot"
    )
    audit_plugin_support()
    status(
        "skip", "support",
        "read-only inventory only: no server tools, network/auth probes, updates, "
        "trust grants, migrations or restarts",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--git-path", help="value for the managed git.path setting")
    parser.add_argument("--python-path", help="value for the managed interpreter setting")
    parser.add_argument("--php-path", help="value for the managed PHP validator setting")
    parser.add_argument(
        "--powershell-path",
        help="executable path for the managed PowerShell discovery setting",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report changes without writing files"
    )
    parser.add_argument(
        "--support-audit", action="store_true",
        help="read-only MCP definitions/launcher and Copilot plugin inventory; "
        "redacts server credentials and does not start servers or update plugins",
    )
    parser.add_argument(
        "--copilot-chat-migration", action="store_true",
        help="prepare only configured Copilot session-sync preferences and show "
        "manual migration verification steps; may enable history uploads; "
        "use --dry-run to audit first",
    )
    parser.add_argument(
        "--agent-customization-migration", metavar="PROFILE",
        help="migrate configured portable MCP servers and terminal instructions from "
        "one existing VS Code profile into the Copilot runtime; backs up sources "
        "before retiring them; use --dry-run first",
    )
    parser.add_argument(
        "--skip-settings-sync", action="store_true",
        help="skip the final Settings Sync request for this run without changing sync preferences",
    )
    args = parser.parse_args()
    if sum(bool(mode) for mode in (
        args.support_audit, args.copilot_chat_migration, args.agent_customization_migration
    )) > 1:
        parser.error("choose support audit, session-sync preparation or customization migration, not multiple modes")
    enforce_execution_mode(args.dry_run or args.support_audit)

    config = load_json(args.config)
    if not config:
        print(f"Config not found at {args.config}; using built-in defaults.")

    if args.support_audit:
        return audit_support(config)
    if args.agent_customization_migration:
        return migrate_agent_customizations(
            config, args.agent_customization_migration, args.dry_run
        )
    if args.copilot_chat_migration:
        return prepare_copilot_chat_migration(config, args.dry_run)

    if not get(config, "user.install.vscodeSettings", True):
        status("skip", "vscode", "user.install.vscodeSettings is false")
        return 0

    settings = build_settings(
        config, args.git_path, args.python_path, args.php_path, args.powershell_path
    )
    snippet = build_snippet(config)

    targets = [d for d in profile_dirs(config) if d.is_dir()]
    if not targets:
        status("skip", "vscode", "no VS Code user profile found on this machine")
    else:
        for user_dir in targets:
            apply(user_dir, settings, snippet, args.dry_run)

    manage_terminal_instructions(config, args.dry_run)
    manage_extensions(config, args.dry_run)
    manage_mcp(config, args.dry_run)
    manage_copilot_mcp(config, args.dry_run)
    if validate_install(config, settings, snippet, args.dry_run):
        if args.skip_settings_sync:
            status("skip", "VS Code User Sync", "--skip-settings-sync was passed")
        else:
            sync_settings(config, args.dry_run)
    if not args.dry_run:
        status(
            "skip", "restart",
            "VS Code and existing terminals were left open. If an extension or PATH change "
            "needs a restart, save your work and reopen VS Code or start a new terminal "
            "yourself when ready; no restart is performed automatically.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
