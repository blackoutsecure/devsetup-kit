# Blackout Secure Dev Setup Kit

Source: [blackoutsecure/devsetup-kit](https://github.com/blackoutsecure/devsetup-kit).
The repository rename does not change installed paths, shell-profile markers,
tool configuration or the existing setup/audit commands.

[![Made by BlackoutSecure](https://img.shields.io/badge/made%20by-BlackoutSecure-1f1f1f)](https://github.com/blackoutsecure)

Cross-platform developer environment setup for machines **without local admin rights**.

Installs Git, GitHub CLI, Node.js, Prettier, Python, Rust/Cargo, Dioxus CLI (`dx`), PHP, PowerShell, ShellCheck, ripgrep, Packer, and GPG
per-user, plus BusyBox on Windows, then applies VS Code settings and portable Copilot MCP defaults.
VS Code profile settings can follow you through Settings Sync; Copilot's separate global MCP
config is not covered by Settings Sync. Every step auto-detects what is already present and skips
it, reporting each decision in the terminal. Nothing requires WSL, sudo, or a GUI installer.

- **Audit first.** `setup.ps1 -Audit` / `setup.sh --audit` reports what would change and writes nothing.
- **One config.** Every tunable lives in [`config/dev-setup.config.json`](config/dev-setup.config.json).
- **Copilot auto-keep.** Pending edits are automatically kept after one second, with a configurable delay or manual-review opt-out.
- **Idempotent.** Re-running is safe; values are compared before they are written.
- **Color-coded.** Each line is tagged `[found]` (green), `[install]` (cyan), `[warn]` (yellow), or
  `[skip]` (grey) — identically across PowerShell, bash, and the Python VS Code applier. Colors are
  suppressed for `NO_COLOR`, non-TTY output, and are always on under `GITHUB_ACTIONS`.

## Requirements

Platform requirements:

- **Windows:** PowerShell 5.1+. WinGet for PHP, ShellCheck, ripgrep, BusyBox, and Packer.
  Official portable ZIP fallbacks for GitHub CLI, Node.js, and PowerShell; `uv` fallback for Python.
  Rust uses user-scoped WinGet or the official verified rustup installer. Prettier uses npm.
- **macOS:** Xcode Command Line Tools for Git. Homebrew for GitHub CLI, Node.js, PHP, PowerShell,
  ShellCheck, ripgrep, Packer, and GPG. Prettier uses npm.
- **Ubuntu / Debian:** Homebrew is installed under `$HOME` automatically if missing;
  used for Git, GitHub CLI, Node.js, PHP, PowerShell, ShellCheck, ripgrep, Packer, and GPG.
  Prettier uses npm.

No administrator or root access is required by the primary setup flow. WSL is never installed or invoked by `setup.ps1`.
Dioxus CLI uses Cargo on all platforms and requires stable Rust and a working native linker.

### No-admin limitations

- Windows WinGet installs always request user scope. GitHub CLI, Node.js, and PowerShell 7 fall back to
  official portable ZIPs if WinGet is missing, fails, or does not produce an executable.
  ZIPs are SHA256-verified against official release metadata, staged, then installed under
  `%LOCALAPPDATA%\Programs`; existing destination content is never overwritten.
  Python can fall back to user-local `uv`; Rust can use its official SHA256-verified
  user-local installer. Other unsupported packages report failure rather
  than retrying with machine scope or requesting elevation. WinGet uninstall is user-scoped
  too; portable ZIP fallbacks are deliberately left in place, not recursively removed.
- macOS and Linux bootstrap Homebrew from its source archive into `$HOME/.linuxbrew`. Homebrew
  documents this as its unsupported "untar anywhere" mode, so bottles may be unavailable and a
  formula may need to build from source. Standard-user mode never writes into `/opt/homebrew`,
  `/home/linuxbrew`, or another shared prefix. Install commands use `--formula` so a missing
  formula cannot silently select a cask that requests an administrator password.
- A new macOS installation still needs Xcode Command Line Tools for Git and source builds. Apple
  provides no silent no-admin installation path, so run `xcode-select --install` yourself when the
  tools are absent.

## Quick start

Windows — `setup.cmd` is the bootloader; it runs `setup.ps1`:

```powershell
.\setup.cmd
```

macOS / Linux:

```bash
chmod +x setup.sh
./setup.sh
```

Run an audit first to see what would happen:

```powershell
.\setup.ps1 -Audit
```

```bash
./setup.sh --audit
```

Audit mode installs nothing, writes no files, and does not touch git config or `PATH`.
Run setup from a normal, non-elevated account with a writable home directory. All runners,
standalone installers, and the Python applier reject elevated write runs by default. Existing working
system-installed tools can be reused without elevation; they do not need to be reinstalled.
On Unix, audit reports a shared Homebrew prefix as blocked when standard-user
setup would refuse to modify it. Existing Git credential helpers are preserved.
When an installation would require writing to a shared Homebrew prefix, that component is
reported as `[skip]` with the policy reason and later independent setup steps continue. The
Cargo-dependent Dioxus setup is skipped too when Rust/Cargo is unavailable for that reason.
The tool remains unavailable until you use a user-local Homebrew installation or deliberately
opt in to shared-prefix writes with `DEVSETUP_ADMIN_MODE=1`.

Setup never closes or reloads VS Code, terminates existing terminal sessions, or restarts
WSL as part of its default flow. It prints manual restart guidance in the terminal after
applying changes. Save work and restart only when you choose. There is no persistent
"restart automatically" configuration; the optional WSL helper has a per-run override below.

### Standard-user execution and explicit admin mode

The default applies to every managed application, not just PowerShell: children inherit the
standard user's process token. No script requests UAC elevation, calls `sudo`, or silently
retries a user-scoped installation as a machine installation. An elevated parent cannot be
made non-admin by setting an environment variable; open a normal terminal instead.

| Applications | Standard-user behavior |
| --- | --- |
| Git and GPG | Reuse existing tools or user-local PortableGit; Git configuration and keyrings belong to the current user. |
| GitHub CLI, Node.js, PowerShell | User-scoped WinGet or verified user-local ZIPs on Windows; Homebrew formulas on Unix. |
| Python and uv | User-scoped WinGet or user-local uv/CPython; project virtual environments remain the default. |
| Rust, Cargo, rustup | Current-user toolchains, components, and `PATH`; no automatic system linker installation. |
| PHP, ShellCheck, ripgrep, BusyBox, Packer | User-scoped WinGet; supported Unix tools use Homebrew formulas. BusyBox is only detected on Unix. |
| Prettier and npm | User-owned npm global prefix rather than the system Node.js installation directory. |
| Homebrew | New installations stay under the home directory; shared-prefix writes require the explicit override below. Root execution remains unsupported. |
| VS Code, extensions, MCP servers | Current-user profiles and CLI processes; no administrator launch options are added. |
| Dev containers and WSL | The container user remains `vscode`; WSL user changes, sudo grants, and restarts remain separate explicit operations. |

Set **`DEVSETUP_ADMIN_MODE=1` for one run** only when you deliberately want to permit
an already-elevated process, or modify a permitted shared Homebrew prefix from a non-root
account. Unset, blank, and `0` mean standard-user mode. Other values are rejected.
This is not saved to the kit config, VS Code settings, or the persistent user environment.

For example, from the chosen PowerShell session, keep the override scoped to a child process:

```powershell
pwsh -NoProfile -Command '$env:DEVSETUP_ADMIN_MODE="1"; & .\setup.ps1'
```

On macOS/Linux:

```bash
DEVSETUP_ADMIN_MODE=1 ./setup.sh
```

If setup skips tools because the shared Homebrew prefix is protected, its final
summary prints this opt-in command. Use it only when you are authorized to modify that
prefix; run from a permitted non-root account.

The override **does not grant permissions**, start an elevated shell, widen WinGet scope,
enable casks, or make Homebrew support root. All existing per-user destinations and safety
checks remain in place. Running children as admin is reported explicitly when the parent
is elevated. `-Audit`, `--audit`, `--dry-run`, and check-only modes remain read-only even in
admin mode; combining uninstall and check-only does not make uninstall read-only.

These guarantees cover processes launched by the kit. Applications opened independently
inherit their own launcher or terminal's identity; existing OS compatibility flags and
administrator-only hardware, hypervisor, or container-daemon operations are not changed.
Setup never grants passwordless sudo or restarts applications as part of the override.

### Optional WSL user setup

`setup-wsl.ps1` is a separate, opt-in helper for an existing WSL distribution that incorrectly starts as `root`.
It never installs WSL or a distribution. Audit first:

```powershell
.\setup-wsl.ps1 -Audit
```

To create or configure a non-root default user without granting passwordless `sudo`, run:

```powershell
.\setup-wsl.ps1 -Configure -UserName <linux-user>
```

Pass `-Distribution <name>` to target a specific installed distribution. A non-root user with
a writable home and executable login shell is healthy; passwordless `sudo` is not required.
`-Audit` takes precedence over `-Configure` and never writes or restarts anything.

Configuration writes the default-user setting but leaves VS Code, terminals, and WSL running.
The terminal reports **restart pending**; it does not claim that the new default has been
verified. Save Linux work, manually terminate the selected distribution, then reopen it and
run the audit again. To explicitly authorize termination and verification for one run:

```powershell
.\setup-wsl.ps1 -Configure -UserName <linux-user> -Distribution <name> -RestartDistribution
```

This ends processes only in the named distribution, never all WSL distributions. Do not use
the override while it hosts VS Code, a remote workspace, or work you want to keep running.
Development tasks that genuinely require passwordless `sudo`, such as loop-device tests,
can separately opt in with `-EnablePasswordlessSudo -Configure`. Neither override is stored
as a default. The helper does not remove an existing sudo grant automatically.

The setup also installs the ShellCheck CLI by default, so the local Bash lint
checks used by the Blackout Secure repositories can run without a separate
tool installation. Set `user.install.shellcheck` to `false` to skip it.

ripgrep (`rg`) is installed by default for fast recursive repository searches.
Set `user.install.ripgrep` to `false` to skip it.

BusyBox is installed by default on Windows through WinGet (`frippery.busybox-w32`) to provide
its Unix utilities through one user-local executable. On macOS and Linux the setup detects an
existing `busybox` command but does not install or remove one because no supported user-local
package source is available. Set `user.install.busybox` to `false` to skip the check.

HashiCorp Packer is installed by default for building VM images such as the SkillForge lab
appliance OVA. Windows uses WinGet (`Hashicorp.Packer`); macOS and Linux use HashiCorp's own
Homebrew tap (`hashicorp/tap/packer`), because Packer is no longer in homebrew-core. The
`hashicorp.hcl` extension joins the synced VS Code baseline for `.pkr.hcl` syntax support.
Set `user.install.packer` to `false` to skip the CLI.

Prettier is installed by default as a user-level npm global so `prettier --check .`
works in any repository, including before a repository's own dependencies are installed.
The VS Code Prettier extension and default formatter setting are also part of the synced
baseline. Set `user.install.prettier` to `false` to skip the global CLI.
On macOS/Linux, the installer uses the configured prefix without changing npm's
global configuration and adds its bin directory to the login profile. Open a new
login shell to use it.

GPG is available by default too, so `git` commit/tag signing works without a separate
tool installation. Set `user.install.gpg` to `false` to skip its configuration. On Windows,
the setup uses the GPG executable bundled with user-local PortableGit, adds its directory to
the user `PATH`, and writes the resolved path to Git's global `gpg.program`; it does not install
the administrator-elevated Gpg4win package. macOS and Linux continue to install GPG through
the user-local Homebrew flow.

### Optional GPG signing identity

`manage-gpg-key.ps1` / `manage-gpg-key.sh` are separate, opt-in helpers that generate, export, or
import a GPG key for `git` commit/tag signing. They're separate from `setup.ps1`/`setup.sh` because
they change real state: a new secret key in your keyring, and your global git signing config
(`user.signingkey`, `commit.gpgsign`, `tag.gpgsign`, and `gpg.program`). Nothing here runs as part of the main setup.
Audit first:

```powershell
.\manage-gpg-key.ps1 -Audit
```

```bash
./manage-gpg-key.sh --audit
```

Generate a new key (using `user.git.userName` / `user.git.userEmail` from config) and configure git
to sign with it:

```powershell
.\manage-gpg-key.ps1 -Generate
```

```bash
./manage-gpg-key.sh --generate
```

Back up the configured signing key to a password-protected archive, and restore it on another
machine. The archive is a plain zip/tarball encrypted with GPG's own AES-256 symmetric cipher, so
"zipping it and putting it wherever" doesn't need a separate archiver:

```powershell
.\manage-gpg-key.ps1 -Export C:\path\to\gpg-backup   # -ZipPassword <SecureString>, or one is generated and shown once
.\manage-gpg-key.ps1 -Import C:\path\to\gpg-backup.gpg -ZipPassword <SecureString>
```

```bash
./manage-gpg-key.sh --export /path/to/gpg-backup --zip-password '<password>'   # omit to generate one, shown once
./manage-gpg-key.sh --import /path/to/gpg-backup.gpg --zip-password '<password>'
```

`-Generate`/`--generate` and `-Export`/`--export` can be combined in one run. If a passphrase or
archive password isn't supplied, one is generated and printed once - save it, since it can't be
recovered afterward. `-KeyPassphrase`/`--key-passphrase` protects the private key itself (used by
gpg-agent when signing); `-ZipPassword`/`--zip-password` protects only the backup archive.

### Repository checks

This kit installs machine and editor prerequisites; repositories keep their own pinned Node and
Python tooling. From a repository root, use its declared check command. The common patterns in
this organization are:

```bash
npm run check
```

```bash
python -m pytest -q
```

Use the repository's `package.json`, `pyproject.toml`, or contributor guide as the authority when
it differs. Do not install project linters or test runners globally. For Python repositories, create
or select the repository virtual environment first; this kit recommends `.venv` and configures VS
Code to discourage global package installs.

### Options

| Option                  | Applies to                            | Effect                                                                                                   |
| ----------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `-Audit` / `--audit`    | runners and every installer           | Detect and report only.                                                                                  |
| `-SkipVSCodeSettings`   | `setup.ps1`                           | Leave editor settings alone for one run.                                                                 |
| `-GitInstallDir <path>` | `setup.ps1`                           | Override `user.git.installDir` for one run.                                                              |
| `-PythonVersion <x.y>`  | `setup.ps1`                           | Override `user.python.version` for one run.                                                              |
| `-SkipUpgradeCheck`     | `setup.ps1` / `--skip-upgrade-check`  | Skip the upgrade check for one run (it runs by default).                                                 |
| `-CheckUpgradesOnly`    | `setup.ps1` / `--check-upgrades-only` | Only check for newer versions; installs and applies nothing.                                             |
| `-UpgradePowerShell`    | `setup.ps1` / `--upgrade-powershell`  | Explicitly upgrade PowerShell 7 to the latest stable release. Combine with audit to preview.             |
| `-UpgradeRust`          | `setup.ps1` / `--upgrade-rust`        | Update only the host's stable Rust toolchain and installed components/targets; audit previews it.        |
| `-Uninstall`            | `setup.ps1` / `--uninstall`           | Remove tools this kit manages (winget/Homebrew). Combine with `-Audit` to preview. Git is never removed. |

Upgrade checks run by default (`user.checkUpgrades`, default `true`) alongside every audit, install, or
run-through, reporting newer versions with a new `[update]` tag and, where the package manager exposes
it, the installed and latest versions. They never apply upgrades automatically;
PowerShell upgrades require `-UpgradePowerShell` / `--upgrade-powershell`, and stable Rust
updates require `-UpgradeRust` / `--upgrade-rust`.
`-CheckUpgradesOnly` runs just that check without installing or changing anything. `-Uninstall` removes
Node.js, Prettier, Python, PHP, PowerShell, ShellCheck, ripgrep, and Packer via the same package manager that installed them (winget or npm
on Windows, Homebrew or npm on macOS/Linux). BusyBox is removed only on Windows, where the kit
manages it through WinGet; Unix installations are left untouched. Git is intentionally excluded since removing it would also need to
unwind the credential/identity config this kit writes.

## Audit output

```text
Auditing (detect only - nothing will be installed or changed):
  [found]   Git      git version 2.51.0 at C:\Program Files\Git\cmd\git.exe
  [install] git cfg  would set credential.helper, credential.credentialStore, credential.guiPrompt
  [warn]    identity not set; fill user.git.userName / user.git.userEmail
  [found]   Node.js  v22.11.0 at C:\Program Files\nodejs\node.exe
  [install] Python   would install Python.Python.3.14 via winget
  [install] vscode   would set 5 setting(s) in <user-profile>\Code\User
             - python.globalModuleInstallation
             - dev.containers.defaultExtensions
             - git.path
             - python.defaultInterpreterPath
             - python.terminal.activateEnvironment
  [skip]    validate dry-run; files were not changed
  [found]   VS Code User Sync GitHub Settings Sync already enabled (stable)

Audit complete. Nothing was installed or changed. Re-run without -Audit to apply.

Summary: 3 found, 2 would install, 1 skipped, 1 warning

Recommendation: 2 change(s) would be made if you run the real setup:
  - git cfg: would set credential.helper, credential.credentialStore, credential.guiPrompt
  - Python: would install Python.Python.3.14 via winget
Run this to apply them: .\setup.ps1
1 item(s) need attention regardless (see [warn] lines above).
```

The same vocabulary is used during a real run:

| Status      | Meaning                                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------------------ |
| `[found]`   | Already present and correct. Nothing was done.                                                               |
| `[install]` | Something was changed or installed.                                                                          |
| `[skip]`    | Disabled, not applicable on this platform, or blocked by a safety policy such as a shared Homebrew prefix. |
| `[warn]`    | Continued, but the result is degraded or needs your attention.                                               |
| `[update]`  | A newer version is available. Reports installed/latest versions when known, but never applies automatically. |
| `[remove]`  | Uninstalled. Only ever appears with `-Uninstall` / `--uninstall`.                                            |

Every run ends with a one-line `Summary:` tally of these tags. `-Audit` runs add a
`Recommendation:` section: if anything is pending, it lists planned changes and the command to
apply them; earlier failures can prevent later steps. On Unix, the command preserves a
`DEVSETUP_CONFIG_FILE` override. Warnings are reported separately even when no changes are planned.

## Layout

```text
setup.cmd     Windows bootloader -> setup.ps1
setup.ps1     Windows runner
setup.sh      macOS / Linux runner
config/       the single config file you edit
src/          all implementation
src/scripts/  one installer per tool, each runnable on its own
.github/      repo-specific automation config, Dependabot, and CODEOWNERS
```

| Path                                | Contents                                                                                         |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| root                                | The entrypoints you actually type. Nothing else.                                                 |
| `config/dev-setup.config.json`      | Single source of truth for every setting. Kept at the top level because it is the file you edit. |
| `src/config.ps1`, `src/config.sh`   | Config loader, dotted-path lookup, status reporter, shared helpers.                              |
| `src/configure-vscode.py`           | Cross-platform VS Code settings, extensions, and MCP applier.                                    |
| `src/scripts/install-*.{ps1,sh}`    | Per-tool install steps invoked by the runners.                                                   |
| `.github/bos-universal-config.json` | Repo-specific Blackout Secure automation config.                                                 |
| `.github/dependabot.yml`            | Repo-specific dependency-update config.                                                          |
| `.github/CODEOWNERS`                | Repo-specific review ownership.                                                                  |

Every script resolves the repository root from its own location, so the runners and the individual
installers work from any working directory.

## Configuration reference

`config/dev-setup.config.json` has two top-level sections, read by `src/config.ps1` (PowerShell),
`src/config.sh` (bash), and `src/configure-vscode.py` (Python). A value is defined exactly once and
cannot drift between platforms.

Every lookup carries a built-in fallback. Deleting a key, leaving it `""`, or deleting the whole
config file degrades to the documented default rather than failing the run.

### User-editable recommendations

These are the supported knobs for routine use. They are safe to edit in a fork or personal copy.

| Setting                                     | Default                                                                                                                                                                              | Purpose                                                                                                                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `user.install.git`                          | `true`                                                                                                                                                                               | Run the Git installer step.                                                                                                                                                       |
| `user.install.node`                         | `true`                                                                                                                                                                               | Run the Node.js/npm step.                                                                                                                                                         |
| `user.install.prettier`                     | `true`                                                                                                                                                                               | Run the Prettier CLI step. Uses user-level npm globals after Node.js/npm are available.                                                                                           |
| `user.install.python`                       | `true`                                                                                                                                                                               | Run the Python step.                                                                                                                                                              |
| `user.install.rust`                         | `true` | Provision stable Rust and Cargo, plus selected components and targets. |
| `user.install.dioxus`                       | `true` | Install Dioxus CLI (`dx`) through Cargo after the Rust step. Existing installations are preserved. |
| `user.install.php`                          | `true`                                                                                                                                                                               | Run the PHP step. macOS/Linux use Homebrew; Windows uses WinGet.                                                                                                                  |
| `user.install.powershell`                   | `true`                                                                                                                                                                               | Run the PowerShell 7 step. macOS/Linux use Homebrew; Windows uses WinGet.                                                                                                         |
| `user.install.shellcheck`                   | `true`                                                                                                                                                                               | Run the ShellCheck CLI step. macOS/Linux use Homebrew; Windows uses WinGet.                                                                                                       |
| `user.install.ripgrep`                      | `true`                                                                                                                                                                               | Run the ripgrep (`rg`) CLI step. macOS/Linux use Homebrew; Windows uses WinGet.                                                                                                   |
| `user.install.busybox`                      | `true`                                                                                                                                                                               | Install BusyBox through WinGet on Windows; detect an existing command on macOS/Linux.                                                                                             |
| `user.install.packer`                       | `true`                                                                                                                                                                               | Run the HashiCorp Packer CLI step. macOS/Linux use the `hashicorp/tap` Homebrew tap; Windows uses WinGet.                                                                         |
| `user.install.gpg`                          | `true`                                                                                                                                                                               | Run the GPG step. macOS/Linux use Homebrew; Windows configures PortableGit's bundled GPG.                                                                                         |
| `user.install.vscodeSettings`               | `true`                                                                                                                                                                               | Apply any VS Code settings at all.                                                                                                                                                |
| `user.install.devcontainerDefaults`         | `true`                                                                                                                                                                               | Include the Dev Containers keys and snippet.                                                                                                                                      |
| `user.install.mcpServers`                   | `true`                                                                                                                                                                               | Reconcile MCP servers in `mcp.json`.                                                                                                                                              |
| `user.checkUpgrades`                        | `true`                                                                                                                                                                               | Report newer versions (`[update]`) during every audit/install run, with installed/latest versions when known. `-SkipUpgradeCheck` / `--skip-upgrade-check` overrides for one run. |
| `user.git.installDir`                       | `""`                                                                                                                                                                                 | Windows PortableGit location. Empty uses `advanced.git.defaultInstallDir`.                                                                                                        |
| `user.git.forcePortable`                    | `false`                                                                                                                                                                              | Install PortableGit even when a system Git is on `PATH`. Left `false`, an existing Git is detected and the download is skipped.                                                   |
| `user.git.userName`                         | `""`                                                                                                                                                                                 | Applied via `git config --global user.name` when non-empty.                                                                                                                       |
| `user.git.userEmail`                        | `""`                                                                                                                                                                                 | Applied via `git config --global user.email` when non-empty.                                                                                                                      |
| `user.python.version`                       | `"3.14"`                                                                                                                                                                             | Single source of truth for Windows winget and macOS/Linux `uv`.                                                                                                                   |
| `user.python.allowGlobalPackageInstalls`    | `false`                                                                                                                                                                              | Written to VS Code as `python.globalModuleInstallation`; keep `false` to preserve the Python extension's virtual-environment warning.                                             |
| `user.python.recommendedVirtualEnvironment` | `".venv"`                                                                                                                                                                            | Documented environment folder recommendation for project-level dependencies.                                                                                                      |
| `user.vscode.profiles`                      | `["stable","insiders"]`                                                                                                                                                              | Which VS Code profiles receive settings and extensions.                                                                                                                           |
| `user.vscode.settingsSync.syncAfterSetup`   | `true`                                                                                                                                                                               | Request VS Code Settings Sync after successful validation when GitHub sync is already enabled. This may open VS Code.                                                             |
| `user.vscode.settingsSync.requiredProvider` | `"github"`                                                                                                                                                                           | Only request sync when the signed-in Settings Sync account provider matches this value.                                                                                           |
| `user.vscode.copilot.autoAcceptDelay`       | `1`                                                                                                                                                                                  | Automatically Keep pending Copilot edits after this many seconds (`0` disables; supported range `0`-`100`). Does not grant tool approvals.                                        |
| `user.vscode.settings`                      | curated set, see below                                                                                                                                                               | Settings merged verbatim into `settings.json`. Wins over everything else.                                                                                                         |
| `user.vscode.extensions.manage`             | `true`                                                                                                                                                                               | Install/report extensions at all.                                                                                                                                                 |
| `user.vscode.extensions.install`            | 22 extensions                                                                                                                                                                        | Installed if missing, via the VS Code CLI.                                                                                                                                        |
| `user.vscode.extensions.block`              | 11 extensions                                                                                                                                                                        | Never installed. Reported as `[warn]` if already present.                                                                                                                         |
| `user.vscode.extensions.uninstallBlocked`   | `true`                                                                                                                                                                               | Remove blocked extensions that are installed instead of just reporting them.                                                                                                      |
| `user.mcp.manage`                           | `true`                                                                                                                                                                               | Reconcile MCP servers at all.                                                                                                                                                     |
| `user.mcp.servers`                          | 4 servers                                                                                                                                                                            | Added to `mcp.json` if absent. Existing entries are never overwritten.                                                                                                            |
| `user.mcp.inputs`                           | `[]`                                                                                                                                                                                 | `${input:id}` definitions. Required by any server that references one.                                                                                                            |
| `user.mcp.copilotConfig.manage`             | `true`                                                                                                                                                                               | Also add portable servers to `$COPILOT_HOME/mcp-config.json` (or `~/.copilot/mcp-config.json`).                                                                                   |
| `user.mcp.block`                            | `[]`                                                                                                                                                                                 | Server IDs that should not be configured. Reported as `[warn]` if present.                                                                                                        |
| `user.mcp.removeBlocked`                    | `false`                                                                                                                                                                              | When `true`, blocked servers are deleted from `mcp.json` instead of reported.                                                                                                     |
| `user.devcontainers.dockerAccess`           | `"outside-of-docker"`                                                                                                                                                                | `outside-of-docker`, `in-docker`, or `none`.                                                                                                                                      |
| `user.devcontainers.baseImage`              | `mcr.microsoft.com/devcontainers/base:ubuntu-24.04`                                                                                                                                  | Image used by the `devcontainer` snippet.                                                                                                                                         |
| `user.devcontainers.remoteUser`             | `"vscode"`                                                                                                                                                                           | `remoteUser` emitted by the snippet.                                                                                                                                              |
| `user.devcontainers.features`               | common-utils, git, github-cli                                                                                                                                                        | Features always installed. The Docker feature is added from `dockerAccess`.                                                                                                       |
| `user.devcontainers.extensions`             | Copilot, Copilot Chat, PR, Actions, GitLens, EditorConfig, ESLint, Prettier, Ruff, Python, Pylance, debugpy, Markdownlint, Code Spell Checker, Markdown All in One, YAML, ShellCheck | Extensions always installed in a container.                                                                                                                                       |
| `user.devcontainers.settings`               | `copyGitConfig`, `gitCredentialHelperConfigLocation`, `cacheVolume`, `logLevel`                                                                                                      | Remaining `dev.containers.*` keys.                                                                                                                                                |

### Shared defaults

Shared, derived, or non-auto-detectable values: package identifiers, download URLs, version-pinned
paths, state keys, and the setting keys the scripts own. These are public and secret-free, but they
are not meant for day-to-day editing.

| Setting                                                           | Default                                    | Purpose                                                                                                                     |
| ----------------------------------------------------------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `advanced.git.defaultInstallDir`                                  | `%USERPROFILE%\PortableGit`                | Fallback when `user.git.installDir` is empty.                                                                               |
| `advanced.git.portableReleaseApiUrl`                              | git-for-windows latest release API         | Where the PortableGit build is discovered.                                                                                  |
| `advanced.git.portableAssetPattern`                               | `PortableGit-*64-bit.7z.exe`               | Which release asset to download.                                                                                            |
| `advanced.git.homebrewFormula`                                    | `git`                                      | Formula used on macOS/Linux.                                                                                                |
| `advanced.git.homebrewInstallUrl`                                 | Homebrew source archive                    | Archive extracted into `$HOME/.linuxbrew` when Homebrew is missing on macOS/Linux.                                          |
| `advanced.git.linuxbrewShellenv`                                  | `$HOME/.linuxbrew/bin/brew`                | User-local Homebrew executable loaded after install and persisted in `.profile` or `.zprofile`.                             |
| `advanced.git.credential.windows.helper`                          | `manager`                                  | Git Credential Manager.                                                                                                     |
| `advanced.git.credential.windows.credentialStore`                 | `wincredman`                               | Windows Credential Manager backing store.                                                                                   |
| `advanced.git.credential.windows.guiPrompt`                       | `false`                                    | Keeps GCM from opening blocking dialogs.                                                                                    |
| `advanced.git.credential.macos.helper`                            | `osxkeychain`                              | Applied when the helper exists.                                                                                             |
| `advanced.git.credential.linux.helper`                            | `manager`                                  | Applied when the helper exists.                                                                                             |
| `advanced.gpg.portableGitRelativePath`                            | `usr\bin\gpg.exe`                          | GPG executable within the user-local PortableGit directory on Windows.                                                      |
| `advanced.python.wingetPackageId`                                 | `Python.Python.{version}`                  | `{version}` is replaced by `user.python.version`.                                                                           |
| `advanced.python.windowsInstallRoot`                              | `%LOCALAPPDATA%\Programs\Python`           | Where an existing interpreter is discovered.                                                                                |
| `advanced.python.uvInstallUrl.windows`                            | `https://astral.sh/uv/install.ps1`         | uv bootstrap, used only if winget is unavailable.                                                                           |
| `advanced.python.uvInstallUrl.unix`                               | `https://astral.sh/uv/install.sh`          | uv bootstrap on macOS/Linux.                                                                                                |
| `advanced.python.uvWindowsPath`                                   | `%USERPROFILE%\.local\bin\uv.exe`          | Where the Windows uv bootstrap lands.                                                                                       |
| `advanced.node.wingetPackageId`                                   | `OpenJS.NodeJS.LTS`                        | Also substituted into `windowsSearchPaths`.                                                                                 |
| `advanced.node.homebrewFormula`                                   | `node`                                     | Formula used on macOS/Linux.                                                                                                |
| `advanced.node.windowsSearchPaths`                                | 3 paths                                    | Where `node.exe` is located after a winget install. `{wingetPackageId}` is substituted.                                     |
| `advanced.prettier.npmPackage`                                    | `prettier`                                 | Package name used for npm uninstall and upgrade checks.                                                                     |
| `advanced.prettier.npmPackageSpec`                                | `prettier@latest`                          | Package spec installed by npm.                                                                                              |
| `advanced.prettier.windowsGlobalPrefix`                           | `%USERPROFILE%\.npm-global`                | User-owned npm global prefix on Windows.                                                                                    |
| `advanced.prettier.unixGlobalPrefix`                              | `$HOME/.npm-global`                        | User-owned npm global prefix on macOS/Linux.                                                                                |
| `advanced.dioxus.cargoPackage`                                    | `dioxus-cli` | Cargo package supplying `dx`. |
| `advanced.dioxus.cratesApiBaseUrl`                                | `https://crates.io/api/v1/crates` | Read-only stable-version lookup for Dioxus upgrade checks. |
| `advanced.php.homebrewFormula`                                    | `php`                                      | Formula used on macOS/Linux for PHP validation.                                                                             |
| `advanced.php.wingetPackageId`                                    | `PHP.PHP`                                  | Package used on Windows for PHP validation.                                                                                 |
| `advanced.powershell.homebrewFormula`                             | `powershell`                               | Formula used on macOS/Linux for the PowerShell extension.                                                                   |
| `advanced.powershell.wingetPackageId`                             | `Microsoft.PowerShell`                     | Package used on Windows for the PowerShell extension.                                                                       |
| `advanced.busybox.wingetPackageId`                                | `frippery.busybox-w32`                     | Package used on Windows.                                                                                                    |
| `advanced.busybox.windowsSearchPaths`                             | WinGet `Links` and package folders         | Where an existing `busybox.exe` is discovered.                                                                              |
| `advanced.packer.homebrewFormula`                                 | `hashicorp/tap/packer`                     | Tap-qualified formula used on macOS/Linux.                                                                                  |
| `advanced.packer.wingetPackageId`                                 | `Hashicorp.Packer`                         | Package used on Windows.                                                                                                    |
| `advanced.packer.windowsSearchPaths`                              | WinGet `Links` and package folders         | Where an existing `packer.exe` is discovered.                                                                               |
| `advanced.vscode.profileDirectories`                              | per-OS stable/insiders paths               | Uses `%VAR%` on Windows and `$HOME` elsewhere.                                                                              |
| `advanced.vscode.managedSettingKeys.gitPath`                      | `git.path`                                 | Setting written with the resolved Git path.                                                                                 |
| `advanced.vscode.managedSettingKeys.pythonInterpreter`            | `python.defaultInterpreterPath`            | Setting written with the resolved interpreter.                                                                              |
| `advanced.vscode.managedSettingKeys.phpValidator`                 | `php.validate.executablePath`              | Setting written with the resolved PHP executable.                                                                           |
| `advanced.vscode.managedSettingKeys.powerShellAdditionalExePaths` | `powershell.powerShellAdditionalExePaths`  | Setting written with the resolved PowerShell executable.                                                                    |
| `advanced.vscode.extensionCli`                                    | `stable: code`, `insiders: code-insiders`  | CLI used to install extensions per profile. A profile is skipped when its CLI is not on `PATH` or a known install location. |
| `advanced.vscode.extensionCliFallbackPaths`                       | per-OS stable/insiders paths               | Well-known install locations checked on macOS/Linux when the CLI isn't on `PATH`.                                           |
| `advanced.vscode.mcpFileName`                                     | `mcp.json`                                 | File written next to `settings.json` in each profile.                                                                       |
| `advanced.vscode.settings`                                        | `azureFunctions.showProjectWarning: false` | Non-devcontainer settings the setup owns.                                                                                   |
| `advanced.devcontainers.dockerAccessFeatures`                     | map of 3 modes                             | Feature refs selected by `user.devcontainers.dockerAccess`.                                                                 |
| `advanced.devcontainers.settingKeys.features`                     | `dev.containers.defaultFeatures`           | Key holding the feature map.                                                                                                |
| `advanced.devcontainers.settingKeys.extensions`                   | `dev.containers.defaultExtensions`         | Key holding the extension list.                                                                                             |
| `advanced.devcontainers.snippet.file`                             | `jsonc.json`                               | Snippet file written under `snippets/`.                                                                                     |
| `advanced.devcontainers.snippet.name`                             | `Dev container (Ubuntu base)`              | Snippet entry name.                                                                                                         |
| `advanced.devcontainers.snippet.prefix`                           | `devcontainer`                             | Text typed to expand the snippet.                                                                                           |

### Precedence

For VS Code settings, later wins:

1. `advanced.vscode.settings`
2. dev container keys, when `user.install.devcontainerDefaults` is `true`
3. managed Python global package install guidance
4. resolved `git.path` / `python.defaultInterpreterPath`
5. Copilot presets, including `user.vscode.copilot.autoAcceptDelay`
6. `user.vscode.settings`

Command-line parameters override the config for a single run.

The kit defaults Copilot edit auto-keep to one second. Set
`user.vscode.copilot.autoAcceptDelay` to `0` to require manual Keep, or override
`chat.editing.autoAcceptDelay` under `user.vscode.settings`. Applying the kit updates
an existing profile's delay to the configured value; unattended permissions remain opt-in.

### Rust, Cargo, and editor

`user.install.rust` (default `true`) enables `src/scripts/install-rust.ps1` or
`src/scripts/install-rust.sh` in setup, audit, and upgrade-check modes.
Windows installs rustup through user-scoped WinGet (`advanced.rust.wingetPackageId`),
falling back to the official SHA256-verified rustup installer when user-scoped WinGet
is unavailable (`advanced.rust.bootstrapBaseUrl`). The fallback runs noninteractively
without installing Visual Studio or changing the default host;
macOS/Linux use Homebrew (`advanced.rust.homebrewFormula`, including its keg-only path).
Existing rustup installations and `CARGO_HOME` are detected even when Cargo is not on PATH.
Setup resolves rustup's configured default host and provisions that host's **stable**,
with `rustfmt`, `clippy`, and `rust-src` by default, checks `rustc` and Cargo,
and preserves an existing default toolchain and repository toolchain pins.
Cargo and `rustc` are required components and are repaired when missing, even when
`user.rust.components` is empty. Cargo is bundled with Rust; it needs no separate
installer or `user.install.cargo` switch. `user.install.rust` controls both.
Other missing selected components are repaired; existing toolchains are not automatically upgraded.
`user.rust.components` is a deduplicated array of rustup component names; `user.rust.targets`
is an optional array of cross-compilation targets, empty by default. For example:

```json
{
    "rust": {
        "components": ["rustfmt", "clippy", "rust-src", "rust-docs", "llvm-tools"],
        "targets": ["wasm32-unknown-unknown"]
    }
}
```

Place these keys under `user` in the config. Missing/null entries use the defaults; an
empty array selects no extras. Use names from `rustup component list --toolchain stable`
and `rustup target list --toolchain stable`. The installer validates availability for the
host's stable release, detects exact names rather than prefixes, and verifies each addition.
Unavailable/nightly-only components fail explicitly; setup does not silently install nightly,
remove unselected components, or force an update past unavailable components. Cross-target
standard libraries are not a substitute for that target's linker, SDK, or framework.

Installed versions are reported for rustup, rustc, Cargo, rustfmt, Clippy, and the optional
rust-analyzer component when present. Upgrade-check mode reports installed/latest toolchain
versions from `rustup check`; components update with their toolchain. Explicit updates:

```powershell
.\setup.ps1 -UpgradeRust -Audit
.\setup.ps1 -UpgradeRust
.\src\scripts\install-rust.ps1 -Upgrade
```

```bash
./setup.sh --upgrade-rust --audit
./setup.sh --upgrade-rust
./src/scripts/install-rust.sh --upgrade
```

Only `stable-<configured-host>` is updated, with `--no-self-update`; rustup itself,
other channels, pinned toolchains, and existing defaults are preserved. The stable update
also updates its installed components and targets before reconciling configured additions.
Update success is verified with `rustup check`. A failed or still-outdated update is an
error, not success. Rustup-manager updates remain separate package-manager/self-update
operations. Audit and check-only modes never update, even with the upgrade flag; explicit
updates still check for a newer stable when routine checks are disabled.

`CARGO_HOME` and `RUSTUP_HOME` are respected and reported; their defaults remain `~/.cargo`
and `~/.rustup`. The same standard-user/admin-opt-in policy covers rustup, Cargo, compiler
probes, components, and targets. Setup never retries permission failures with elevation,
changes ownership, or updates a system-managed rustup binary. Automatic provisioning of
project-pinned toolchains is disabled during inspection. Framework crates such as Tokio,
Axum, Bevy, and Tauri remain project dependencies managed by the project's Cargo manifests,
not global rustup components or silently installed CLI tools.

A normal run builds a dependency-free temporary Cargo project with `cargo build --offline`,
then executes the native program and removes the entire temporary workspace.
The probe uses the configured host, a private target directory, and its own working directory;
it does not fetch crates or modify the current project's manifest, lockfile, or build outputs.
Audit never compiles or changes PATH; it reports planned PATH/profile changes and
explicitly reports build readiness as unverified.
A successful version check alone is not proof that Windows linking works.
Failed probes report `[warn]`: MSVC requires C++ Build Tools; GNU requires compatible
MinGW linker tools. Linux needs a C linker and development libraries; macOS needs Xcode
Command Line Tools. Setup never elevates, installs these system prerequisites, changes the
host target, or writes a global linker workaround. Shared Rust installations and Cargo
packages are intentionally preserved by uninstall on both platforms.
Open a new terminal/login shell manually to pick up PATH changes.
Cargo-installed commands use `CARGO_HOME/bin`; Homebrew's Rust proxy directory is also
included when needed so commands such as `cargo clippy` work before opening a new shell.
This discovery is scoped to Rust subprocesses during audit and does not change persistent PATH.

The editor baseline installs official `rust-lang.rust-analyzer`, uses Clippy for checks,
and scopes rust-analyzer formatting/format-on-save to `[rust]`. Existing additional
Rust language settings are preserved. No duplicate debugger, deprecated Rust extension,
or unverified Rust MCP server is added. TOML support is optional rather than another default.

These user settings and extensions follow the existing **GitHub Settings Sync** handoff:
in VS Code, turn on Settings Sync, sign in with GitHub, and include **Settings** and
**Extensions**. Confirm the Rust entries with **Settings Sync: Show Synced Data**.
Local configuration or an accepted `--sync on` request is not proof of completed cloud
upload. Toolchains, Cargo caches, native SDKs, and machine PATH do **not** sync.

### Dioxus CLI (`dx`)

`user.install.dioxus` (default `true`) runs `src/scripts/install-dioxus.sh` or
`src/scripts/install-dioxus.ps1` after the Rust step on macOS, Linux, and Windows.
It uses the [official Dioxus Cargo package](https://dioxuslabs.com/learn/0.7/getting_started/#install-the-dioxus-cli):
`cargo install --locked --bin dx --root <Cargo home> dioxus-cli`.
The explicit root respects `CARGO_HOME` (default `~/.cargo` or `%USERPROFILE%\.cargo`)
and prevents `CARGO_INSTALL_ROOT` from redirecting the installation elsewhere.
The stable toolchain is selected only for the install subprocess; existing defaults,
repository pins, and the caller's toolchain environment are preserved.

This source build can take several minutes and needs a working native compiler/linker
and platform dependencies such as OpenSSL where applicable. Unlike the prebuilt
installer recommended by Dioxus for speed, this uses the kit's existing Cargo support
without running a downloaded shell script or installing `cargo-binstall`.
The kit never installs system SDKs or elevates to satisfy these dependencies.
WebAssembly targets, WebView2, Linux WebKitGTK, and mobile SDKs remain project/platform
prerequisites; installing `dx` does not prove a particular app target can build.

Existing `dx` commands are version-checked and skipped, including those under a custom
Cargo home that is not yet on PATH. The Cargo bin directory is exposed for future
terminals using the same Rust PATH helpers. Open a new terminal manually when ready.
Set `user.install.dioxus` to `false` to disable this step. If Rust setup is disabled,
provide stable Rust/Cargo separately before installing a missing CLI.

```bash
bash ./src/scripts/install-dioxus.sh --audit
bash ./src/scripts/install-dioxus.sh
```

```powershell
.\src\scripts\install-dioxus.ps1 -Audit
.\src\scripts\install-dioxus.ps1
```

Audit and upgrade-check modes never install or compile. Installed/latest stable
versions are compared through the crates.io HTTP API, not a mutating Cargo registry
command; lookup failures are explicit errors. Updates are reported, never applied
automatically. Projects needing a particular CLI release can install it explicitly
with `cargo install dioxus-cli --locked --version <version>`; setup accepts an existing CLI.
Uninstall preserves Cargo packages and reports the manual `cargo uninstall` command,
without removing Rust toolchains, caches, or project dependencies.

### Extensions

`user.vscode.extensions.install` is a lean, broadly useful baseline rather than an exhaustive list:
formatting and linting (`editorconfig`, `prettier`, `eslint`, `ruff`, `markdownlint`, `shellcheck`),
Python (`python`, `pylance`, `debugpy`, `vscode-python-envs`), Rust (`rust-lang.rust-analyzer`),
GitHub (`vscode-github-actions`, `vscode-pull-request-github`),
containers and remote (`remote-containers`, `vscode-containers`), plus `powershell`, `yaml`,
`hcl`, `makefile-tools`, `code-spell-checker`, `markdown-all-in-one`, and the Playwright Test extension
(`ms-playwright.playwright`) for running and debugging browser tests from VS Code.

Python Environments is explicit even though the Python extension also includes it; this keeps
environment management in the kit's audited baseline. ShellCheck provides editor diagnostics
alongside the CLI installed by the kit. Prettier remains the general default. For Python and
PowerShell, select `charliermarsh.ruff` and `ms-vscode.powershell`, respectively, in workspace
language-specific formatter settings when needed; Prettier does not support those languages.
Managed language override blocks preserve unrelated existing per-language choices.

The workspace-facing baseline also appears in `user.devcontainers.extensions`, including HCL,
Makefile Tools, Playwright, PowerShell, Python Environments, and ShellCheck. Container Tools and
Dev Containers themselves stay on the host. Extensions do not provision a project's runtimes,
test dependencies, or browser binaries inside a container.

The extension is installed into each configured VS Code profile, but Playwright itself remains a
per-project dependency. Use the extension's **Test: Install Playwright** command or
`npm init playwright@latest` in a project to create its test setup and install the selected browsers;
the setup kit does not install browser binaries globally.

#### Stack-specific recommendations

Keep these opt-in rather than installing every language, cloud explorer, or extension pack on
every machine. Add the required IDs to `user.vscode.extensions.install` and, when needed in a
container, `user.devcontainers.extensions`.

| Workload | Recommended extension IDs | Guidance |
| -------- | ------------------------- | -------- |
| Rust | `rust-lang.rust-analyzer` | Use with a project-managed Rust toolchain. Prefer rustfmt through rust-analyzer over `jinxdash.prettier-rust`; set `editor.defaultFormatter` to `rust-lang.rust-analyzer` in a workspace `[rust]` override. |
| Swift | `swiftlang.swift-vscode` | Install only where a Swift SDK/toolchain is available; its LLDB DAP dependency supplies debugging support. |
| Go | `golang.go` | Useful for Go repositories, not required for the setup kit itself. |
| C/C++ and CMake | `ms-vscode.cpptools`, `ms-vscode.cmake-tools` | Prefer the needed tools over the full C++ pack and its themes. |
| Astro | `astro-build.astro-vscode` | Add for Astro projects; Prettier alone is not the language service. |
| Vitest | `vitest.explorer` | Add when the repository uses Vitest; it complements rather than replaces Playwright Test. |
| Azure | Service-specific `ms-azuretools.*` extensions | Install only the services used by the project, rather than the entire Azure Tools pack. |
| Databases | `ms-mssql.mssql` or `mtxr.sqltools` with the appropriate driver | Choose according to the database; two explorers are not a universal requirement. |
| Microsoft Learn authoring | `docsmsft.docs-authoring-pack` | Intended for Learn content; ordinary repository Markdown uses the baseline tools. |

GitLens and Git History are optional additions to VS Code's built-in Git history, not baseline
requirements. Keep `ms-python.mypy-type-checker` only when a project needs mypy: Ruff does linting,
while Pylance and mypy do type analysis. Preview tools such as `typescriptteam.native-preview`
belong in an experimental profile rather than the portable baseline. Optional does not mean
blocked; the kit preserves installed tools that are not on its explicit block list.

For Cargo manifests, rustup configuration, and Python project configuration, the optional
[`tamasfe.even-better-toml`](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml)
extension supplies TOML validation and formatting. Its publisher labels it preview, so it is
not silently added to every machine. Keep the existing Rust formatter override rather than
adding a second Rust formatter or debugger when the installed tools already cover those needs.

Publisher references: [Python Environments](https://marketplace.visualstudio.com/items?itemName=ms-python.vscode-python-envs),
[ShellCheck](https://marketplace.visualstudio.com/items?itemName=timonwong.shellcheck), and
[rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer).

#### Superseded-tool policy

`user.vscode.extensions.block` is the kit's opinionated policy for tools that are deprecated,
superseded, or overlap its chosen baseline. Not every blocked extension is unmaintained: a project
that requires Black or Pylint should customize this policy rather than treating Ruff as an exact
replacement for every rule.

| Blocked                                                              | Superseded by                                   |
| -------------------------------------------------------------------- | ----------------------------------------------- |
| `ms-python.autopep8`, `black-formatter`, `flake8`, `isort`, `pylint` | `charliermarsh.ruff`                            |
| `ms-azuretools.vscode-docker`                                        | `ms-azuretools.vscode-containers`               |
| `ms-vscode.vscode-typescript-tslint-plugin`                          | `dbaeumer.vscode-eslint` (TSLint is deprecated) |
| `hookyqr.beautify`                                                   | `esbenp.prettier-vscode` (unmaintained)         |
| `ms-vscode.powershell-preview`                                       | `ms-vscode.powershell`                          |
| `eg2.vscode-npm-script`, `ms-vscode.node-debug2`                     | Built into VS Code                              |

Blocked extensions are removed by default because `uninstallBlocked` is `true`; set it to `false`
to report them without removing them. An extension listed in both `install` and `block` is a
configuration error and fails the run.

The [Docker publisher's migration guidance](https://marketplace.visualstudio.com/items?itemName=ms-azuretools.vscode-docker)
confirms that the old Docker wrapper pack can be removed while keeping Container Tools.

Extension management needs the matching VS Code CLI (`code` or `code-insiders`). On macOS and
Linux the kit also checks `advanced.vscode.extensionCliFallbackPaths` when the CLI is not on
`PATH`. Profiles whose CLI is missing are reported as `[skip]` and everything else still runs.

#### Extension updates

The baseline explicitly enables `extensions.autoCheckUpdates` and `extensions.autoUpdate`.
Override either key under `user.vscode.settings` when a project needs a different policy.
The setup applier installs missing recommendations and validates their presence; it does
not force-reinstall every existing extension on every run.

To update extensions already installed in each local VS Code edition, use:

```powershell
code --update-extensions
code-insiders --update-extensions
```

Use the same commands from Bash on macOS/Linux. Each CLI selects updates compatible with
its VS Code version and existing release-channel policy; setup does not opt extensions
into prerelease channels. These commands preserve unrelated installed extensions and do
not restart VS Code. An updated extension may need a manual window reload before the
running extension host uses its new version. Check `--list-extensions --show-versions`
afterward rather than interpreting an unchanged version as a failed upgrade.

### MCP servers

`user.mcp.servers` is merged into each profile's `mcp.json` and into the Copilot user-level
`mcp-config.json`. The latter uses the directory in `COPILOT_HOME`, or `~/.copilot` when that
variable is unset. The four shipped defaults use remote HTTP services or local `npx`/`uvx`
runtimes. GitHub requires authentication; the other defaults do not:

| Server                               | Transport     | Why it is a default                                       |
| ------------------------------------ | ------------- | --------------------------------------------------------- |
| `io.github.github/github-mcp-server` | http          | Repos, issues, PRs. Useful in any repository.             |
| `microsoftdocs/mcp`                  | http          | Microsoft/Azure documentation lookup. No auth.            |
| `microsoft/markitdown`               | stdio (`uvx`) | Converts PDFs/Office docs to Markdown. Language-agnostic. |
| `microsoft/playwright-mcp`           | stdio (`npx`) | Browser automation for front-end work.                    |

The local launchers are pinned to `markitdown-mcp@0.0.1a8` and
`@playwright/mcp@0.0.83`. MarkItDown remains on its existing alpha release channel.
`uvx` and `npx` resolve these versions in user-owned caches; Python/Node.js and the
launchers must be available. No server needs administrator rights merely to start.
The pinned npm launcher includes `--yes` so a first-time package download cannot wait
for an interactive npm prompt; this does not approve MCP trust or tool permissions.
The kit does not install Playwright browsers globally or grant a server additional trust.

Servers that are **not** shipped as defaults, and why:

| Not included                          | Reason                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Azure, Azure DevOps, NuGet, Terraform | Require a subscription, an organization name, a token, or a .NET/Terraform stack. Useful, but not universal. |
| Enterprise and Sentinel endpoints     | Tenant-entitled URLs. They fail for anyone without the entitlement.                                          |
| Next.js devtools, awesome-copilot     | Framework-specific, or require a local Docker daemon.                                                        |

Add any of these to `user.mcp.servers` yourself — the merge handles them the same way.

**Existing entries are never overwritten.** Only missing servers are added, so a locally pinned
version or an added `env` block survives a re-run. Remove a server from `mcp.json` and it comes back
on the next run; add it to `user.mcp.block` to stop that.

**Never hardcode secrets.** Use VS Code's `${input:id}` placeholders with matching entries in
`user.mcp.inputs` and mark secret prompts with `"password": true`. VS Code prompts for those values
locally instead of storing them in this repository.

A server that references an `${input:id}` with no matching definition fails the run, as does a
server listed in both `servers` and `block`.

The Copilot config uses the portable `mcpServers` format and adds `tools: ["*"]` when a server
does not define a tool list. Existing entries are never overwritten. Servers that use VS Code-only
fields or variables (including `${input:id}` secrets) are skipped for this destination and reported;
they remain available through the VS Code profile config. This is deliberate: the Copilot format
cannot prompt for VS Code input variables, and the kit will not copy resolved secrets into another
file.

VS Code Settings Sync does **not** sync `$COPILOT_HOME/mcp-config.json`. The setup writes the
portable config locally for the Copilot harness and Copilot CLI; it does not create a GitHub repo,
push user data, or store credentials. If you want this user-level config on other machines, use a
private repository or another secure sync method that you manage, and keep secret values in
environment variables rather than the tracked file.

#### MCP and agent plugin support review

Run the dedicated read-only inventory without applying unrelated setup settings:

```powershell
python .\src\configure-vscode.py --support-audit
```

Use `python3 src/configure-vscode.py --support-audit` on macOS/Linux. It reviews configured
MCP definitions in existing VS Code profiles and Copilot's separate user config, reports
missing launchers and differences from the kit baseline, and lists installed/enabled
plugins through `copilot plugin list --json` when that CLI is available. Configured is not
the same as running: the audit never starts an MCP server, sends a tool request, tests a
tenant login, updates packages/plugins, changes trust, or restarts an application.
URLs, headers, environment values, and plugin source details are not included in its output.
CLI failures and malformed inventories are reported explicitly; an absent CLI is skipped.
Installed plugins whose named marketplace is no longer registered are flagged as possible
update blockers without re-registering or trusting a source automatically.

Existing MCP definitions remain add-only. A new kit pin does not silently rewrite an existing
server's locally selected package or arguments. Review the reported difference, back up the
owning host's configuration, and change only the intended version argument. Preserve headers,
environment variables, tool restrictions, authentication, and unrelated servers.

VS Code's Agent Customizations editor and Copilot's `/plugin`/CLI management can have
separate plugin inventories. Use the manager that installed a plugin:

```powershell
copilot plugin list --json
copilot plugin marketplace list
copilot plugin update <plugin>@<marketplace>
```

Update named, already-reviewed plugins rather than enabling all marketplace entries.
If the original marketplace is no longer registered, restore its reviewed source before
updating; do not replace it with an unverified similarly named marketplace. A disabled
bundled plugin stays disabled. The `agentPlugins` directories contain generated/synced
snapshots, not a reliable count of installed plugins; never hand-edit or delete them to
force an update. The [official plugin management guide](https://code.visualstudio.com/docs/agent-customization/agent-plugins)
explains the separate inventories and supported update controls. The kit's extension
auto-update setting also lets VS Code check provider-managed Git-source plugins; npm/PyPI
plugin updates still require host confirmation.

Keep only one overlapping GitHub/Azure provider active per host where practical, but do not
delete a user configuration just because another host or extension supplies similar tools.
Docker-backed servers additionally require a working daemon; .NET MCP servers require their
configured `dnx` launcher/SDK. WorkIQ, Azure, Enterprise, Sentinel, and other account-specific
plugins/servers remain workload opt-ins, not new universal defaults. Authentication and tenant
entitlements must be verified in the owning client, not inferred from a successful file audit.

#### GitHub MCP and your GitHub-synced profile

The [official GitHub MCP server](https://github.com/github/github-mcp-server) is already included
in the shipped setup configuration. Its VS Code user-profile definition is:

```json
{
    "servers": {
        "io.github.github/github-mcp-server": {
            "type": "http",
            "url": "https://api.githubcopilot.com/mcp/"
        }
    }
}
```

This hosted server needs no Docker container or local GitHub MCP binary. Complete the host's
GitHub OAuth sign-in when prompted; no token belongs in the setup configuration. Authentication
and server trust are local to each host and might need approval again on another device.

To keep this setup in your GitHub-backed VS Code cloud profile:

1. Sign in to **Settings Sync** with GitHub. Run **Settings Sync: Configure** and select
   **MCP Servers**.
2. Run the kit's audit, then apply setup using the [quick start](#quick-start). It adds missing
   server definitions to the configured Stable and Insiders user profiles without replacing
   existing servers. It also maintains Copilot's separate local config.
3. Open **Settings Sync: Show Synced Data** and confirm the MCP data contains
   `io.github.github/github-mcp-server` with the endpoint above. An accepted `--sync on` request
   alone is not proof that the cloud upload finished.
4. On another device, let Settings Sync restore the user-profile configuration, complete any
   authentication or trust prompts, and request the GitHub MCP `get_me` tool to verify access.

Only the user-profile `mcp.json` participates in
[MCP Settings Sync](https://code.visualstudio.com/docs/agents/run/manage-mcp-servers#synchronize-mcp-configuration-across-devices).
Copilot's `mcp-config.json` remains local; run the kit on each machine that needs the Copilot
harness or CLI configuration. This does not change your public GitHub profile or publish
credentials.

### Settings deliberately excluded

`user.vscode.settings` holds portable editor, Git, terminal, and security preferences. Some
categories are **intentionally not** shipped here:

| Excluded                                                                                                              | Why                                                                                                                                                                           |
| --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git.path`, `python.defaultInterpreterPath`, `php.validate.executablePath`, `powershell.powerShellAdditionalExePaths` | Machine-local; resolved and written by the installers. The PHP and PowerShell path settings are ignored by Settings Sync.                                                     |
| `azureResourceGroups.selectedSubscriptions`, `@azure.argTenant`, `chat.mcp.serverSampling`                            | Contain tenant/subscription identifiers. Never commit these to a shared repo.                                                                                                 |
| `yaml.schemas`                                                                                                        | Absolute paths containing a username. Already in `settingsSync.ignoredSettings`.                                                                                              |
| `terminal.integrated.cwd`                                                                                             | A personal folder convention.                                                                                                                                                 |
| `chat.tools.global.autoApprove`, `chat.agent.sandbox.*`, `chat.agent.networkFilter`, `chat.tools.*.autoApprove`       | Agent security posture. Auto-approving tool calls and disabling the sandbox is a personal risk decision and must not be a shared default. Set them yourself if you want them. |
| Other `chat.*` / `github.copilot.*` tuning                                                                            | Fast-moving setting names and highly personal. Add to `user.vscode.settings` if you want them synced.                                                                         |

Anything in this list can still be added to `user.vscode.settings` on your own machine — the config
is yours to extend.

### Path placeholders

Config values may contain environment placeholders, expanded at read time:

| Form                | Platform      | Example                                      |
| ------------------- | ------------- | -------------------------------------------- |
| `%VAR%`             | Windows       | `%APPDATA%\Code\User`                        |
| `$HOME`             | macOS / Linux | `$HOME/.config/Code/User`                    |
| `{version}`         | any           | `Python.Python.{version}`                    |
| `{wingetPackageId}` | any           | `...\WinGet\Packages\{wingetPackageId}*\...` |

## Shared code reference

### `src/config.ps1` (dot-source it)

| Name                                                  | Kind     | Purpose                                                           |
| ----------------------------------------------------- | -------- | ----------------------------------------------------------------- |
| `$DevSetupRoot`                                       | variable | Repository root, resolved from the file's own location.           |
| `$DevSetupConfigPath`                                 | variable | Default config path under `config/`.                              |
| `Get-DevSetupConfig [-Path]`                          | function | Load and parse the config; warns and returns empty if absent.     |
| `Get-DevSetupValue $cfg <dotted.key> [$default]`      | function | Safe lookup. `null` and `""` fall back to `$default`.             |
| `Expand-DevSetupPath <value>`                         | function | Expand `%VAR%` placeholders.                                      |
| `ConvertTo-DevSetupHashtable <object>`                | function | `PSCustomObject` to hashtable for iteration.                      |
| `Write-DevSetupStatus <state> <component> [detail]`   | function | Emit one `[found]/[install]/[skip]/[warn]` line.                  |
| `Get-DevSetupVSCodeProfilePath $cfg [-Platform]`      | function | Existing `settings.json` paths for configured profiles.           |
| `Set-DevSetupVSCodeSetting $cfg <key> <value>`        | function | Write one setting to every profile, skipping no-ops.              |
| `Add-DevSetupUserPath <dir> [-Prepend]`               | function | Add a directory to the user `PATH` once, comparing whole entries. |
| `Get-DevSetupGitCredentialSetting $cfg`               | function | The git config keys/values this setup owns on Windows.            |
| `Write-DevSetupGitIdentityStatus $cfg <git> [-Audit]` | function | Identity reporting shared by audit and apply.                     |

```powershell
. (Join-Path $PSScriptRoot "..\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig
$version = Get-DevSetupValue $config "user.python.version" "3.14"
```

### `src/config.sh` (source it)

| Name                                           | Kind     | Purpose                                                                      |
| ---------------------------------------------- | -------- | ---------------------------------------------------------------------------- |
| `DEVSETUP_ROOT`                                | variable | Repository root, resolved from the file's own location.                      |
| `DEVSETUP_CONFIG_FILE`                         | variable | Config path. Override by exporting it before sourcing.                       |
| `DEVSETUP_READER`                              | variable | The JSON reader (`python3`, `python`, or `jq`) resolved once at source time. |
| `devsetup_config <dotted.key> [default]`       | function | Safe lookup. Arrays print newline-separated.                                 |
| `devsetup_enabled <dotted.key> [default]`      | function | True when the value is `true`.                                               |
| `devsetup_status <state> <component> [detail]` | function | Emit one status line.                                                        |
| `devsetup_git_identity_status [audit]`         | function | Identity reporting shared by audit and apply.                                |
| `devsetup_config_reader`                       | function | Prints `DEVSETUP_READER`; fails if none was found.                           |

```bash
. "$(dirname "$0")/../config.sh"
devsetup_assert_execution_mode "$audit"
version="$(devsetup_config user.python.version 3.14)"
```

The config must be readable _before_ Python is installed, so the reader is chosen from `python3`,
`python`, then `jq`, and every lookup falls back to the caller-supplied default if none exist.
Resolution happens at source time rather than per lookup: `devsetup_config` runs inside a `$( )`
subshell, so a value cached during a lookup would be discarded.

## Individual scripts

Each installer runs standalone and accepts `-Audit` / `--audit`.

### Git

```powershell
.\src\scripts\install-portable-git.ps1 [-ConfigureVSCode] [-ForcePortable] [-Audit]
```

```bash
./src/scripts/install-portable-git.sh [--audit]
```

- **Windows** downloads the latest [Git for Windows portable build](https://github.com/git-for-windows/git/releases)
  to the configured directory and adds it to the user `PATH`. An existing Git on `PATH` is detected
  and the download skipped unless `user.git.forcePortable` is `true`.
- **macOS** reports and exits if Git and Xcode Command Line Tools are both missing; Apple offers no
  silent install path, so run `xcode-select --install` once yourself.
- **Linux** uses an existing Git or Homebrew, otherwise installs
  [Homebrew for Linux](https://docs.brew.sh/Homebrew-on-Linux) under `$HOME` (no root) and installs
  Git through it.
- Configures the credential helper and applies `user.git.userName` / `user.git.userEmail` when set.
  Each value is compared first, so a second run reports `[found]`.
- `-ConfigureVSCode` points `git.path` at the resolved binary across every configured profile.

### GitHub CLI

`user.install.githubCli` (default `true`) enables GitHub CLI in setup, audit, upgrade-check,
and uninstall modes on both platform paths. macOS/Linux use the Homebrew formula from
`advanced.githubCli.homebrewFormula` (`gh`). Windows uses
`advanced.githubCli.wingetPackageId` (`GitHub.cli`) with user scope only.

If WinGet is unavailable, fails, or does not expose `gh.exe`, Windows installs an official
SHA256-verified ZIP under `advanced.githubCli.portableInstallDir`
(`%LOCALAPPDATA%\Programs\GitHub CLI`). Release metadata comes from
`advanced.githubCli.portableReleaseApiUrl`
(`https://api.github.com/repos/cli/cli/releases/latest`).
The shared portable installer stages and verifies the archive before moving it into an
unused user-local destination, preserves existing directories, and adds its `bin` to the
user PATH. `advanced.githubCli.windowsSearchPaths` controls additional executable lookup.

Audit never installs or changes PATH. User-scoped uninstall preserves portable ZIP
directories for deliberate manual removal. Setup never elevates, signs into GitHub, or
handles authentication tokens; use `gh auth login` yourself when needed.

### Python

```powershell
.\src\scripts\install-python.ps1 [-ConfigureVSCode] [-PythonVersion <x.y>] [-Audit]
```

```bash
./src/scripts/install-python.sh [--print-path] [--audit]
```

Checks for a working interpreter first. On Windows it installs per-user via `winget` when
available — winget packages go through a trusted pipeline and are not blocked by Defender
Application Control / Exploit Guard ASR policies common on managed corporate devices, whereas
executing a freshly downloaded `uv.exe` can be. If `winget` is unavailable, both platforms fall back
to `uv` in a user-local location.

The version comes from `user.python.version` on every platform. The PowerShell script emits the
resolved interpreter path as its final pipeline value; the shell script does the same under
`--print-path`, with progress on stderr.

### Node.js and npm

```powershell
.\src\scripts\install-node.ps1 [-Audit]
```

```bash
./src/scripts/install-node.sh [--audit]
```

Windows installs Node.js LTS per-user through `winget`; macOS/Linux use Homebrew. If PowerShell
execution policy blocks `npm.ps1`, use `npm.cmd install` / `npm.cmd test` — the same executable,
without changing machine security policy.

### PHP

```bash
./src/scripts/install-php.sh [--print-path] [--audit]
```

macOS/Linux use Homebrew and Windows uses WinGet to install PHP when it is missing. The resolved executable is written
to VS Code's `php.validate.executablePath`, which restores built-in PHP validation. That absolute
path is machine-local and explicitly excluded from Settings Sync.

### PowerShell

```powershell
.\src\scripts\install-powershell.ps1 [-Audit] [-CheckUpgrades] [-Upgrade]
```

```bash
./src/scripts/install-powershell.sh [--print-path] [--audit] [--check-upgrades] [--upgrade]
```

macOS/Linux use Homebrew and Windows uses WinGet to install PowerShell 7 when it is missing. The
resolved `pwsh` path is written to `powershell.powerShellAdditionalExePaths`, restoring discovery
for the VS Code PowerShell extension. The path is machine-local and excluded from Settings Sync.
Ordinary setup, audit, and explicit-upgrade runs support macOS's stock Bash 3.2;
installing a newer Bash is not required.

PowerShell detection reads the installed executable's version, not the version of the shell
running setup. Upgrade checks query the official latest stable release and compare numeric
versions, including multi-digit patch numbers. Stable releases replace same-version previews;
newer installations are never downgraded. Windows PowerShell 5.1 is left alone.

```powershell
.\setup.ps1 -UpgradePowerShell -Audit
.\setup.ps1 -UpgradePowerShell
```

```bash
./setup.sh --upgrade-powershell --audit
./setup.sh --upgrade-powershell
```

On Windows, explicit upgrades use the existing official SHA256-verified ZIP installer in
`advanced.powershell.portableInstallDir/<version>`. Existing system and portable installations
are preserved, including a currently running `pwsh`. Detection selects the newest executable
from `PATH` and these managed directories on subsequent runs. Setup configures VS Code with
that path. A system `pwsh` may still take precedence in a new terminal's `PATH`; use the returned
executable path when needed. No shell, terminal, or editor is restarted automatically.

On macOS/Linux, upgrades are limited to a formula managed by Homebrew under the user's home
directory. System-owned Homebrew prefixes, casks requiring installers, and unmanaged copies
are not modified. A failed upgrade or a package-manager version behind the stable release is
reported as an error, not success. `--print-path` continues to emit only the executable path
on stdout; diagnostics go to stderr.

Audits never install or upgrade, and `-CheckUpgradesOnly` / `--check-upgrades-only` remains
read-only even when combined with the upgrade option. Explicit upgrade requests check the
latest release even when routine upgrade checks are disabled. Release lookup failures produce
a warning for checks and fail explicit upgrade requests. Uninstall and upgrade cannot be
combined, and `user.install.powershell: false` still disables the entire step.

### VS Code settings

```powershell
python .\src\configure-vscode.py [--dry-run] [--config <path>] [--git-path <p>] [--python-path <p>] [--php-path <p>] [--powershell-path <p>]
```

```bash
python3 ./src/configure-vscode.py [--dry-run]
```

One cross-platform script, so the settings payload has a single definition. It writes these files
per configured profile, all covered by Settings Sync:

- `settings.json` — the merged settings described in [Precedence](#precedence).
- `snippets/jsonc.json` — a `devcontainer` snippet. Type `devcontainer` in a new
  `.devcontainer/devcontainer.json`.
- `mcp.json` — the configured MCP servers.
- `prompts/terminal-execution.instructions.md` — personal terminal and process guidance.
  Existing user-authored instructions are preserved and reported for manual comparison.
  Disable installation with `user.vscode.terminalInstructions.manage: false`.

#### Copilot edit auto-keep

The auto-keep capability maps `user.vscode.copilot.autoAcceptDelay` to VS Code's
`chat.editing.autoAcceptDelay` in every configured Stable/Insiders profile. Its default
is **1 second**, including when the config key is missing, `null`, or blank.
The delay must be a number from `0` to `100` seconds; invalid values fail before
profile writes. Set it to `0` to disable auto-keep, not to accept immediately.
Explicit `user.vscode.settings` overrides still win, including a delay of `0`.

For sessions with pending-edit review controls, VS Code automatically selects **Keep**
after the delay. Hovering over the review controls stops the countdown. Harnesses that
save edits directly without a pending-review state do not need this control.
Auto-keep does not approve commands/tools, enable Autopilot or Fusion, stage or commit
files, or change workspace trust.

This user setting is eligible for VS Code Settings Sync and is not excluded by the kit.
With GitHub-backed Settings Sync already enabled and **Settings** selected, the existing
post-validation sync handoff includes it. Confirm the value with
**Settings Sync: Show Synced Data**; a local write or accepted CLI request alone is not
proof of cloud upload. It is an editor preference, not a Copilot CLI or GitHub.com setting.
See [Review AI-generated edits](https://code.visualstudio.com/docs/agents/run/review-code-edits#_auto-accept-edits).

#### Copilot and terminal defaults

The baseline selects Agent, Copilot harness, Auto, the Standard (`balance`) tier, and queued
follow-up messages. Dictation and voice mode (including their buttons) are disabled.
Terminal output is shown in the Terminal panel where the harness supports it, shell integration
is enabled, and persistent process revival is disabled. Existing terminals are not closed.

These chat settings target recent VS Code/Copilot builds; preview features and model access
depend on the installed version, account, and organization policy. The Windows Copilot SDK
harness does **not** support the Agent Host integrated-terminal override in the currently
reviewed build. Terminal settings cannot force SDK shell output into the main panel there;
select the Local harness when integrated-terminal interaction is more important than the
Copilot harness. Instructions require the agent to disclose this limitation.

Autopilot/Allow All and Fusion are explicit opt-ins for a personal copy of the config:

```json
{
    "user": {
        "vscode": {
            "copilot": {
                "autopilot": true,
                "fusion": true
            }
        }
    }
}
```

Merge those keys into the existing config; do not replace the file with this fragment.
Both default to `false` so the kit does not grant unattended permissions or enable
experimental model routing for every user. Fusion presents Auto as Fusion; `balance` is
its Standard tier. Changing Fusion settings may restart the **Copilot runtime**, not the
VS Code application. Settings under `user.vscode.settings` still win over these presets.
Autopilot/Allow All grants broad tool access; it is not permission to restart the editor
or terminate a user's terminals. New-conversation defaults do not rewrite a running chat.

The instruction file sets finite-command budgets (normally 120 seconds, or 600 for builds),
foreground execution, bounded readiness checks for servers/watchers/debuggers, and cleanup
of owned temporary helpers. Instructions guide the agent; they are not a guaranteed process
watchdog. VS Code's 60-second silence threshold returns control without killing a process.
The applier separately enforces CLI deadlines: 120 seconds for queries/sync and 600 seconds
for extension changes, whose output remains visible. A CLI timeout is an error, not success.

It then reconciles extensions through the VS Code CLI: installs anything missing from
`user.vscode.extensions.install`, and reports (or removes) anything present from `.block`. See
[Extensions](#extensions).

Finally it merges `user.mcp.servers` into each profile's `mcp.json` and adds compatible entries
to the Copilot user-level MCP config. See [MCP servers](#mcp-servers).
After writes finish, it validates the managed settings, snippet, extension list, and MCP entries by
rereading the files and VS Code CLI output. If validation passes, `user.vscode.settingsSync` allows
one final guarded sync request: the script checks VS Code's global user-data state for
`sync.enable=true` and the configured account provider, then runs the configured VS Code CLI sync
arguments. It skips sync when Settings Sync is off, the provider is not GitHub, or the CLI is absent.
The final request is **enabled by default**, including when the config key is omitted.
It also requires a nonempty cached Settings Sync account reference and a supported provider
(`github` or `microsoft`); `requiredProvider` defaults to `github`. To use an existing
Microsoft Settings Sync account, explicitly set `requiredProvider` to `microsoft`.
Missing/unreadable state, no cached account, or a provider mismatch produces an explicit
skip (and an unreadable database produces a warning). The database is opened read-only and
closed promptly. A cached account is not proof of a current OAuth session: VS Code itself
validates authentication and may pause uploads until the user signs in again.

To opt out, set `user.vscode.settingsSync.syncAfterSetup` to `false`, or skip just one run:

```powershell
.\setup.ps1 -SkipSettingsSync
python .\src\configure-vscode.py --skip-settings-sync
```

```bash
./setup.sh --skip-settings-sync
```

These options skip only the kit's final request; they do not disable VS Code's ongoing
automatic sync or change Copilot session-sync preferences. Audit never makes a sync request.
All settings, snippets, instructions, extensions, and MCP changes and their validation finish
before the final request. Validation failure prevents that request. There is no blanket
guarantee that every local file is cloud-synced: VS Code resource exclusions and policies apply,
and the separate Copilot MCP file, tool installations, and credentials remain local.

An accepted `--sync on` request only confirms that sync was enabled, not that a cloud upload
finished. Check **Settings Sync: Show Synced Data** in VS Code for the remote settings and
instruction files. The script never edits the sync database, handles OAuth tokens, or
changes your public GitHub profile/bio.

#### Copilot session sync

Session history sync is separate from VS Code Settings Sync. The baseline enables
`chat.sessionSync.enabled` and its required dependency,
`github.copilot.chat.localIndex.enabled`. For supported Copilot harness sessions, this allows
session data to sync to the signed-in GitHub.com account for cross-device history. It requires a supported Copilot
sign-in and can be blocked by organization policy; setup does not sign in, override policy,
or claim that all existing session history has finished uploading.

To disable session-history uploads, set
`user.vscode.settings["chat.sessionSync.enabled"]` to `false`. Session sync may upload
conversation content; review this privacy choice before using the baseline in sensitive
workspaces. The preferences themselves can roam through VS Code Settings Sync, but session
data is uploaded independently by Copilot. A successful settings upload is not proof of a
completed session-history upload.

Use the [Copilot Chat migration process](#copilot-chat-migration-process) below for a
source-to-target move rather than treating enabled preferences as a completed migration.

The merge is additive and idempotent: existing settings and snippets are preserved, and JSONC
comments and trailing commas are tolerated on read. The file is rewritten as plain JSON, so comments
in `settings.json` are **not** preserved.

Settings Sync itself must still be enabled once from VS Code's Accounts menu — OAuth cannot be scripted.
Binaries, `PATH` entries, credentials, and git identity stay machine-local and are never uploaded.
`advanced.node.portableBaseUrl` / `portableInstallDir` and
`advanced.powershell.portableReleaseApiUrl` / `portableInstallDir` control the Windows ZIP
fallbacks. The PowerShell release endpoint also supplies stable-version checks on every platform.
Keep sources official and destinations under the user's profile. Node chooses
the current LTS, not an obsolete release to accommodate an unsupported architecture;
PowerShell requires the release asset's SHA256 digest. Downloads have finite timeouts and
checksum failures leave no installation behind. These fallbacks do not enable automatic
runtime upgrades or change the existing opt-in uninstall behavior.

#### Agent runtime customization migrations

**Agent Customizations > Migrations** is not session-history sync. It lists legacy
customizations that need new locations for the Copilot agent runtime. Enabling session
sync does not clear that dashboard.

Normal setup and its audit now include a read-only migration review. To refresh it
independently without installing tools or applying settings:

```powershell
python .\src\configure-vscode.py --review-migrations
```

```bash
python3 ./src/configure-vscode.py --review-migrations
```

The review discovers the current MCP definitions and instruction, prompt, agent,
chat-mode and skill files under each existing configured profile's `prompts` directory.
It lists kit-managed portable candidates separately from items requiring native review,
without printing server credentials or instruction contents. Counts are recomputed
on every run, including after native or kit migrations retire source items; nothing is
automatically moved. Management opt-outs remain in force. A kit candidate still needs
the migration audit below to validate target conflicts.

Reopen Copilot Chat's **Review Migrations** / **Agent Customizations > Migrations**
after changes: that runtime-specific view is authoritative. The source inventory does
not claim the dashboard is clear or that a migration completed. Workspace, extension,
hook and other customization sources remain native-only.

For the kit's terminal instructions and configured portable MCP servers, use this
separate opt-in process from the kit directory. Select one existing configured profile
(`insiders` below, or `stable`); do not run both blindly because their instruction
contents can differ.

1. **Audit** the actual customization move:

   ```powershell
   python .\src\configure-vscode.py --agent-customization-migration insiders --dry-run
   ```

   ```bash
   python3 ./src/configure-vscode.py --agent-customization-migration insiders --dry-run
   ```

2. **Apply** after reviewing the plan, using the same command without `--dry-run`.
   The process first checks every target for conflicts, then keeps private, exact-byte
   recovery copies under `$COPILOT_HOME/migration-backups/` (default
   `~/.copilot/migration-backups/`). Treat those copies as sensitive local data.
   No tools are installed, session databases read, or VS Code restarts performed.
3. **Verify** the runtime destinations:
   - Portable configured servers already installed in that profile move from its
     `mcp.json` `servers` object into `$COPILOT_HOME/mcp-config.json` `mcpServers`.
     Unmanaged servers, existing nonconflicting targets, and input definitions remain.
   - `prompts/terminal-execution.instructions.md` moves byte-for-byte into
     `$COPILOT_HOME/instructions/terminal-execution.instructions.md`.
   - Only after destination validation are the migrated source entries/files retired.
     The source MCP file is rewritten as plain JSON; its original JSONC bytes are
     preserved in the private recovery copy.
4. **Reopen the Migrations view** and verify that the moved items no longer appear.
   VS Code can request MCP trust again; approve that yourself after reviewing the server.
   This process never grants trust or transfers OAuth credentials.
5. **Rerun** the command to verify no changes. A local, per-profile
   `$COPILOT_HOME/devsetup-agent-migrations.json` ownership record prevents later normal
   setup runs from recreating these legacy candidates. Other profiles remain independent.
   If the native UI already migrated an item, this command can record that ownership too.

The runtime instructions and ownership record are machine-local; VS Code Settings Sync
does not synchronize these Copilot-directory paths.

The process honors the existing management opt-outs and `--config <path>`. Conflicting
targets, changed files, symbolic-link files, or VS Code-only MCP fields stop with an
explicit error; sources are retained. Use VS Code's native **Migrate...** action for
servers needing input-variable, gallery, or other VS Code-specific conversion. Prompts,
agents, hooks, and unrelated personal instructions are not silently migrated by this
kit-specific command.

For rollback, keep the private recovery directory: it contains the previous source,
destination, and ownership-record files that existed. Inspect those copies before any
manual restoration; do not blindly overwrite customizations subsequently edited.

#### Copilot Chat migration process

This section concerns **session history only**, not the
[Agent Customizations migration dashboard](#agent-runtime-customization-migrations).

The kit supports **preparing session sync**, not copying chat storage or automatically
declaring history migrated. This separate, opt-in mode uses the existing config and
cross-platform applier. It changes only the two session-sync preferences above in existing
configured VS Code profile directories; it does not install tools/extensions, change MCP
servers, request Settings Sync, read tokens, or restart VS Code. Normal setup is unchanged.

Follow these stages in order:

1. **Inventory and retain the source.** Identify the source machine, VS Code build/profile,
   Copilot account, repositories, and chats you need. Keep that machine and its local
   history intact. Session sync covers supported Copilot harness sessions; do not assume
   legacy VS Code Chat or another harness's local history will be converted or uploaded.
   Repository files, old absolute workspace paths, and machine-local checkpoints are not
   migrated by this process.
2. **Review privacy and policy.** History sync can upload conversation content to GitHub.
   Check repository exclusions and organization policy before applying. Both preferences
   must explicitly be `true` in `user.vscode.settings` (or inherited from
   `advanced.vscode.settings`), and `user.install.vscodeSettings` must allow management.
   An opt-out or missing dependency blocks preparation with `Not Assessed` and exit code 1;
   the command does not override it. A local setting cannot override enterprise policy.
3. **Audit the source**, from the kit directory:

   ```powershell
   python .\src\configure-vscode.py --copilot-chat-migration --dry-run
   ```

   ```bash
   python3 ./src/configure-vscode.py --copilot-chat-migration --dry-run
   ```

   Use `--config <path>` for a personal config. Only existing directories selected by
   `user.vscode.profiles` and `advanced.vscode.profileDirectories` are considered. If
   none exist, open the intended VS Code build/profile and audit again. Back up its
   `settings.json` before applying if you need its original comments: as with normal
   setup, the additive merge preserves unrelated values but rewrites JSONC as plain JSON.
4. **Prepare the source**, only after approving the audit and upload policy:

   ```powershell
   python .\src\configure-vscode.py --copilot-chat-migration
   ```

   ```bash
   python3 ./src/configure-vscode.py --copilot-chat-migration
   ```

   The command rereads and validates the written preferences. Exit code 0 means only
   that local preparation (or the dry-run plan) succeeded, not that history transferred.
5. **Verify the source upload in VS Code.** Sign in to Copilot with the intended supported
   GitHub.com account. In the Chat view's Copilot status bar, check session sync status.
   Wait for **N sessions synced**, inspect the linked sessions on GitHub.com, and confirm
   the required source sessions are present. **Syncing N sessions**, **Sync error**,
   **Not enabled**, or **Disabled by policy** is not completion. Do not bypass policy.
6. **Prepare and verify the target.** Repeat the audit and preparation commands on the
   destination, use the same Copilot account, and open the repository's actual checkout.
   Query history for known source sessions and inspect their conversation content.
   Check every required repository/session before considering the move complete. Cloud
   searchability is not proof that every legacy chat or local resume artifact was restored.
7. **Keep a rollback path.** Retain source history until target verification succeeds.
   If a required chat is missing or unsupported, leave migration **Not Assessed** and
   use the fallback below where available. To stop future uploads, set
   `chat.sessionSync.enabled` to `false` in the config and VS Code; this does not delete
   data already uploaded to GitHub.

**Local/legacy fallback:** on a build and session that offer the native commands, open
each required source chat and run **Chat: Export Chat...**, preserving its JSON export
privately outside the repository. Transfer that file securely, then run
**Chat: Import Chat...** on the target and inspect the imported conversation. Do not
convert Markdown transcripts, Copilot CLI event files, or SQLite data into guessed import
formats. If those commands are unavailable for the session, retain the source and stop;
the kit does not fabricate a successful import or copy `state.vscdb`, `workspaceStorage`,
or credential stores. Imports do not relocate referenced files or guarantee cross-harness
resumption. Follow organizational data-handling restrictions for offline exports too.

See the official [session history and sync-status guide](https://code.visualstudio.com/docs/agents/run/sessions/session-history),
[GitHub session-data documentation](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/session-data),
and [VS Code's native JSON export/import commands](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/contrib/chat/browser/actions/chatImportExport.ts).

## Repository hygiene

The repository is public and keeps only portable defaults in source control.

| Area                     | Current posture                                                                                 |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| Community defaults       | Funding, issue templates, and PR templates are inherited from the org-level `.github` repo.     |
| Org automation config    | `.github/bos-universal-config.json` opts into common sync/lint settings only.                   |
| CODEOWNERS               | `.github/CODEOWNERS` requests security review for every PR.                                     |
| Issues                   | Enabled for support and bug reports.                                                            |
| Projects and Discussions | Disabled; this kit is small enough to keep planning in issues and PRs.                          |
| Wiki                     | Disabled; public docs live in `README.md`, `SECURITY.md`, and `CONTRIBUTING.md`.                |
| Branch cleanup           | Delete branch on merge is enabled in GitHub repository settings.                                |
| Secrets                  | No credentials, tokens, tenant IDs, subscription IDs, or private endpoints belong in this repo. |
| Workflows                | No action/release workflow is copied because this repo has no `action.yml` or package manifest. |

## Dev container defaults

Dev containers stay **opt-in**. Nothing here creates a `.devcontainer` folder or puts a workspace
into a container; VS Code only containerizes a repo that already has a `.devcontainer/devcontainer.json`.
These are the defaults applied _if_ a container is built.

The default `user.devcontainers.dockerAccess` is `outside-of-docker`, which bind-mounts the host
Docker socket. The container shares the host image cache (no double-pull) and needs no `--privileged`
flag. Two consequences:

- Paths in nested `docker run -v` calls resolve against the **host** filesystem, not the container's.
  Use `${localWorkspaceFolder}` rather than `$(pwd)`. This is the usual cause of confusing failures
  with `act` and nested Compose.
- Socket access is root-equivalent on the host. Fine on a personal machine; not appropriate on
  shared or untrusted infrastructure.

Set `dockerAccess` to `in-docker` for true daemon isolation, accepting `--privileged` and a cold
image cache, or `none` to add no Docker feature at all.

## Troubleshooting

### Set your git identity

Fill `user.git.userName` and `user.git.userEmail` in the config and the setup applies them.
Use a GitHub noreply address if you do not want to expose a personal email address.

### `PATH` changes are not visible

The scripts update the **user-level** `PATH`, which existing shells do not inherit. Open a new
terminal, or reload VS Code.

### Docker Desktop re-prompts for file sharing on non-`C:` drives

If Docker Desktop shows a **Filesharing** dialog every time you run `docker compose`/`docker run`
for a project on a drive other than `C:`, this is Docker Desktop/Windows behavior, not something
VS Code or Settings Sync controls:

- With the **Hyper-V backend**, Settings → Resources → **File sharing** pre-authorizes a directory
  once.
- With the **WSL 2 backend** (the default), that persistent allow-list does not exist for drives WSL
  does not auto-mount, so Docker re-prompts per session by design. Updating Docker Desktop does not
  fix it.

Options: keep the project on `C:`, work inside the WSL distro's own filesystem and run Compose from
within WSL, switch to the Hyper-V backend, or click **Yes** each session.

### PowerShell blocks `npm.ps1`

Use `npm.cmd` instead of `npm`. Same executable, no security policy change.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
