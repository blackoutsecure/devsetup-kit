# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## What this is

`devsetup-kit` is a cross-platform developer machine setup kit for workstations **without local admin rights**. It installs a per-user toolchain — Homebrew (macOS/Linux), Git, Node.js, Python, PHP, PowerShell 7, ShellCheck, ripgrep, Packer, GPG — then writes VS Code user settings, a `devcontainer` snippet, extensions, and MCP server entries into each configured VS Code profile so they follow the developer through Settings Sync. Compatible MCP servers are also added to the Copilot user-level config for Copilot harness/CLI sessions; that separate file is not covered by Settings Sync. Every step detects what is already present and reports a decision instead of reinstalling. No `sudo`, root, WSL, or GUI installer is used.

Three platform paths. Windows runs `setup.cmd` -> `setup.ps1` under Windows PowerShell 5.1+ (`setup.cmd` invokes `powershell.exe -NoProfile -ExecutionPolicy Bypass`), using `winget` for Node.js, Python, PHP, PowerShell 7, ShellCheck, ripgrep and Packer, a downloaded PortableGit build for Git, and PortableGit's bundled `usr\bin\gpg.exe` for GPG. macOS and Linux run `setup.sh` under Bash using Homebrew throughout; on Linux Homebrew is bootstrapped under `$HOME` when missing. WSL is never installed or invoked by the main flow — `setup-wsl.ps1` is a separate opt-in helper that audits or fixes the default user of an _already installed_ distribution.

Bash scripts must run on macOS's stock **bash 3.2** (`src/config.sh` says so and avoids associative arrays for that reason) and all use `set -euo pipefail`. PowerShell targets 5.1+ with `$ErrorActionPreference = "Stop"`. `src/configure-vscode.py` is standard-library Python 3 with no third-party imports. External tools relied on: `git`, `gpg`, `curl`, `tar`, and either `python3`/`python` or `jq` — the config reader falls back across all three because the config must be readable _before_ Python is installed. There is no package manifest, lockfile, or build step.

## Commands

`--audit` / `-Audit` is this repository's dry-run mode: detect and report only, install nothing, write no file, leave git config and `PATH` untouched. `src/configure-vscode.py` exposes the same as `--dry-run`. Always audit first.

```bash
./setup.sh --audit                          # dry run, writes nothing
./setup.sh                                  # apply
./setup.sh --check-upgrades-only            # report newer versions only
./setup.sh --skip-upgrade-check
./setup.sh --uninstall --audit              # preview removals; Git is never removed
bash ./src/scripts/install-node.sh --audit  # any installer runs standalone
python3 ./src/configure-vscode.py --dry-run
python3 -m unittest discover -s tests -v

./manage-gpg-key.sh --audit
./manage-gpg-key.sh --generate
./manage-gpg-key.sh --export /path/to/gpg-backup --zip-password '<password>'
./manage-gpg-key.sh --import /path/to/gpg-backup.gpg --zip-password '<password>'

# Lint (not wired into any script or workflow; run directly)
bash -n setup.sh manage-gpg-key.sh src/config.sh src/scripts/*.sh
shellcheck setup.sh manage-gpg-key.sh src/config.sh src/scripts/*.sh
markdownlint-cli2 --config .markdownlint.json "**/*.md"
python3 -m py_compile src/configure-vscode.py tests/test_configure_vscode.py
```

```powershell
.\setup.cmd                                 # Windows bootloader -> setup.ps1
.\setup.ps1 -Audit
.\setup.ps1 -SkipVSCodeSettings -GitInstallDir <path> -PythonVersion <x.y>
.\setup.ps1 -CheckUpgradesOnly
.\setup.ps1 -Uninstall -Audit
pwsh .\src\scripts\install-node.ps1 -Audit

.\setup-wsl.ps1 -Audit
.\setup-wsl.ps1 -Configure -UserName <linux-user> [-Distribution <name>]

.\manage-gpg-key.ps1 -Audit
.\manage-gpg-key.ps1 -Generate
.\manage-gpg-key.ps1 -Export C:\path\to\gpg-backup -ZipPassword <SecureString>
.\manage-gpg-key.ps1 -Import C:\path\to\gpg-backup.gpg -ZipPassword <SecureString>

Invoke-ScriptAnalyzer -Path . -Recurse
```

`CONTRIBUTING.md` lists PSScriptAnalyzer, ShellCheck, and Ruff as optional local tooling; only ShellCheck is installed by the kit (`user.install.shellcheck`). No PowerShell or Python lint config exists here — `.markdownlint.json` (`MD013: false`) and `.editorconfig` are the only config files.

## Validating changes

**There is no CI in this repository.** `.github/` contains only `CODEOWNERS`, `dependabot.yml`, and `bos-universal-config.json`; there is no `.github/workflows/` directory, so nothing runs on push or pull request. The focused Python unit tests use the standard-library `unittest` runner under `tests/`.

These scripts mutate a real machine — user `PATH`, global git config, package manager state, VS Code profile files, the GPG keyring — so reasoning about correctness is not validation and neither is reading the diff. Work in this order:

1. `bash -n` then `shellcheck` on every shell script touched; `python3 -m py_compile` on the applier and `python3 -m unittest discover -s tests -v` for Python behavior changes.
2. Run the affected installer standalone with `--audit` / `-Audit` and read the reported plan.
3. Run the full entrypoint with `--audit` / `-Audit`; confirm the `Summary:` and `Recommendation:` lines describe exactly what you intend.
4. Run it for real on a **disposable target** — a VM snapshot you can roll back, a container, or a throwaway user account. Never your own configured machine. A Linux container is the cheapest path for `setup.sh`; a Windows VM is required for `setup.ps1`, `setup-wsl.ps1`, and PortableGit, which have no non-Windows equivalent.
5. Run it a second time on that target and confirm every line is `[found]` or `[skip]`. Idempotency is only proven by the second run.
6. Do this on both platforms if you touched both. If you touched only one, say so rather than implying parity was tested.

`manage-gpg-key.sh` / `.ps1` create real secret key material and rewrite global git signing config. Test them only against a throwaway `GNUPGHOME` or disposable machine, never a keyring you rely on.

## Architecture

```text
setup.cmd                        Windows bootloader; runs setup.ps1 via powershell.exe
setup.ps1                        Windows runner (PowerShell 5.1+)
setup.sh                         macOS / Linux runner (bash, 3.2-compatible)
setup-wsl.ps1                    Opt-in WSL default-user audit/fix; never installs WSL
manage-gpg-key.sh / .ps1         Opt-in GPG signing identity helpers
config/dev-setup.config.json     The single config file; `user` and `advanced` sections
src/config.sh                    Sourceable bash config reader, status/summary, Homebrew helpers
src/config.ps1                   Dot-sourced PowerShell equivalent, plus winget helpers
src/configure-vscode.py          Cross-platform VS Code settings/snippet/extension/MCP applier
src/scripts/install-*.sh         One per tool, Homebrew-based; each runs standalone
src/scripts/install-*.ps1        One per tool, winget-based; each runs standalone
.markdownlint.json               MD013 disabled; the only lint config in the repo
.editorconfig                    UTF-8, LF, 4 spaces; tabs in *.sh, CRLF in *.cmd
.gitattributes                   Line-ending normalization; *.cmd pinned to CRLF
.github/bos-universal-config.json  Repo-owned org automation config (sync services, gate modes)
.github/dependabot.yml           Weekly github-actions updates inside a managed marker block
.github/CODEOWNERS               Security review on every PR
```

### Entrypoints

- `setup.cmd` — Windows, 5 lines. Resolves its own directory and execs `powershell.exe -NoProfile -ExecutionPolicy Bypass -File setup.ps1 %*`. Add nothing else here.
- `setup.ps1` — Windows. Loads config, prints a header and resolved-configuration block, calls each `src/scripts/install-*.ps1` gated on `user.install.*`, captures the resolved Git/Python/PHP/PowerShell paths from each script's last pipeline value, and runs `src/configure-vscode.py` last. Modes: default, `-Audit`, `-CheckUpgradesOnly`, `-Uninstall`.
- `setup.sh` — macOS/Linux, same composition in bash. Refuses MinGW/MSYS/Cygwin and any `uname -s` other than `Darwin` or `Linux`. Installs Homebrew first as a dependency of every other step, and wraps `install-gpg.sh` so a GPG failure degrades to `[warn]` rather than aborting under `set -e`.
- `setup-wsl.ps1` — Windows, opt-in, never called by `setup.ps1`. Audits non-root identity, writable home, and executable login shell. `-Configure -UserName <name>` creates the user if absent and writes `[user] default=` without restarting. `-Audit` always prevents writes. Passwordless sudo requires the separate per-run `-EnablePasswordlessSudo` flag. Termination and verification require `-RestartDistribution -Distribution <name>` for that run; never shut down every distribution.
- `manage-gpg-key.sh` / `.ps1` — opt-in, never part of setup. See below.

### Shared modules

`src/config.sh` and `src/config.ps1` are sourced or dot-sourced by every entrypoint and installer, and both resolve the repository root from their own file location so any script works from any working directory. Each provides dotted-path config lookup where `null` and `""` fall back to a caller-supplied default (`devsetup_config` / `Get-DevSetupValue`), a status reporter emitting one `[found]`/`[install]`/`[skip]`/`[warn]`/`[update]`/`[remove]` line per component (`devsetup_status` / `Write-DevSetupStatus`), and a run-summary reader. Every status line is also appended to the file named by `DEVSETUP_STATUS_LOG`, a temp file the runner sets, which is how the final `Summary:` counts lines emitted by separate installer processes and by the Python applier.

`src/config.sh` also holds the shared Homebrew pattern (`devsetup_install_via_homebrew`, `devsetup_uninstall_via_homebrew`, `devsetup_check_homebrew_upgrade`, `devsetup_ensure_homebrew`), which is why `install-php.sh`, `install-powershell.sh`, `install-shellcheck.sh`, `install-ripgrep.sh`, and `install-gpg.sh` are each about 30 lines. `src/config.ps1` holds the winget equivalent (`Install-DevSetupWingetTool`, `Uninstall-DevSetupWingetTool`, `Test-DevSetupWingetUpgrade`, `Find-DevSetupWingetExecutable`) plus `Add-DevSetupUserPath`, which compares whole `PATH` entries rather than substrings.

`src/configure-vscode.py` is the only cross-platform implementation, so the settings payload has a single definition. It merges `settings.json`, writes `snippets/jsonc.json`, reconciles extensions via the VS Code CLI, merges MCP servers into each profile's `mcp.json` and compatible entries into `$COPILOT_HOME/mcp-config.json` (falling back to `~/.copilot/mcp-config.json`), revalidates by rereading, and only then may request Settings Sync. The merge is additive and idempotent — existing keys and existing MCP servers are preserved, never overwritten, and JSONC is tolerated on read. VS Code-only MCP variables/fields are skipped for the Copilot config and reported. Copilot's user config is not covered by VS Code Settings Sync. Files are rewritten as plain JSON, so comments in an existing `settings.json` are **not** preserved.

### Configuration

`config/dev-setup.config.json` is the single source of truth, read identically by all three shared modules so a value cannot drift between platforms. `user` holds routine knobs: `user.install.*` booleans gating each step, `user.checkUpgrades`, `user.git.*` (install dir, `forcePortable`, `userName`, `userEmail`), `user.python.*`, `user.vscode.*` (profiles, settings, extension install/block lists, Settings Sync policy), `user.mcp.*`, `user.devcontainers.*`. `advanced` holds shared or derived values correct by default: winget package IDs, Homebrew formulae, download URLs, per-OS VS Code profile directories, managed setting keys, `advanced.gpg.keyExpiry`.

A user customizes the kit by editing that one file in a fork or personal copy; command-line parameters override it for one run. Values may contain `%VAR%` (Windows), `$HOME` (macOS/Linux), `{version}`, and `{wingetPackageId}` placeholders, expanded at read time. Every lookup carries a fallback, so deleting a key, blanking it, or deleting the whole file degrades to the documented default rather than failing. It is not secret storage: MCP secrets must use VS Code `${input:id}` placeholders with matching `user.mcp.inputs` entries.

### GPG key management

`manage-gpg-key.sh` and `manage-gpg-key.ps1` are separate from setup because they change real state: a new secret key in the keyring and the global git signing config. Subcommands are `--audit`/`-Audit`, `--generate`/`-Generate`, `--export <path>`/`-Export <path>`, `--import <path>`/`-Import <path>`; generate and export can be combined. Both accept `--key-name`/`--key-email` (`-KeyName`/`-KeyEmail`) falling back to `user.git.userName` / `user.git.userEmail`, plus `--key-passphrase`/`-KeyPassphrase` for the private key and `--zip-password`/`-ZipPassword` for the archive. The PowerShell script takes both as `SecureString`, materializing plaintext only transiently for `gpg.exe --passphrase`.

- `--audit` touches no key material. It reports the resolved `gpg` binary and the current `user.signingkey`, and states what generate/export/import _would_ do.
- `--generate` writes a temp batch file containing the passphrase in cleartext, runs `gpg --batch --pinentry-mode loopback --gen-key` (RSA 4096, expiry from `advanced.gpg.keyExpiry`), deletes the batch file, then sets `user.signingkey`, `commit.gpgsign`, `tag.gpgsign`, and `gpg.program` globally. A generated passphrase is printed once and cannot be recovered.
- `--export` runs `gpg --export-secret-keys --armor` — the one operation that extracts **private key material**. With the public key, a `README.txt`, and (when a passphrase is known) a `KEY-PASSPHRASE.txt`, it is archived and encrypted with GPG symmetric AES-256 to `<path>.gpg`. The plaintext archive lives briefly in a temp directory removed by a `trap` / `finally`.
- `--import` decrypts that archive, runs `gpg --import` on `secret.asc`, reads the key ID from the bundled `README.txt`, and reconfigures global git signing. A bundled `KEY-PASSPHRASE.txt` is printed to the terminal.

Treat every export path as a secret-bearing artifact: it holds a usable private key and, by default, its passphrase.

## Safety invariants

- Every operation must be idempotent and safe to re-run: compare current state before writing, emit `[found]` when nothing changed, and make a second run report no changes.
- Every install step must have an audit path that detects and reports without writing. A step that cannot be audited does not belong in the kit.
- Back up or prompt before overwriting existing user configuration. The VS Code applier is additive and preserves unrelated keys, but it rewrites `settings.json` as plain JSON and drops comments; any change that replaces rather than merges user content needs a backup or an explicit prompt first.
- Never export, print, or log private key material or passphrases outside the one path the user explicitly asked for. Generated secrets are shown once, deliberately, and never written to a log, a status line, or `DEVSETUP_STATUS_LOG`.
- Never delete user data. Git is excluded from `--uninstall` because removing it would also require unwinding the credential and identity config this kit wrote; Homebrew is excluded because other tools depend on it.
- Prefer additive changes: append to `PATH`, merge settings, add MCP servers — never reconcile destructively.
- Keep destructive operations behind explicit confirmation. `--uninstall`, `-Configure` on `setup-wsl.ps1`, and every `manage-gpg-key` write are opt-in flags a default run never reaches.
- Do not require or prompt for a password in a non-interactive path. Nothing calls `sudo`, needs admin rights, or opens a GUI installer; Homebrew and winget run with `NONINTERACTIVE=1` and `--silent --accept-package-agreements --accept-source-agreements` respectively.
- Never widen scope silently: a step gated on `user.install.<tool>` stays gated, and a platform that cannot support a step reports `[skip]` or `[warn]` rather than guessing.
- Never automatically close or reload VS Code or terminate the user's terminals. Print manual restart guidance. Broad Autopilot/Allow All permissions are not restart consent; any supported restart override must be explicitly supplied for that run, not persisted.
- Use foreground execution for finite work, with explicit deadlines. Servers, watchers, and debuggers need bounded readiness checks, not waits for exit. Clean up only owned temporary helpers. The VS Code applier bounds CLI calls and streams extension-change output.
- Run `python3 -m unittest discover -s tests -v` for defaults, CLI deadlines, instruction preservation, and mocked WSL consent paths. WSL tests require PowerShell and do not touch a real distribution.
- Windows Node.js and PowerShell can fall back from user-scoped WinGet to official SHA256-verified portable ZIPs. Keep their destination under the user profile, preserve existing directories, and test with disposable ZIP fixtures. Never retry a failed user install with machine scope. User-scoped uninstall leaves portable directories and system packages alone.
- Request Settings Sync only after all managed writes and validation. It defaults on but requires already-enabled sync, a supported matching provider, and a cached account reference; let VS Code validate current OAuth, never handle tokens. `-SkipSettingsSync` / `--skip-settings-sync` skips the final request for one run. Copilot session sync and its local index default on separately; do not confuse settings upload with session-history upload or override account/organization restrictions.

## Conventions

Bash: `set -euo pipefail`, tab indentation (`.editorconfig` overrides `*.sh` to tabs), repo root resolved from `$0`/`${BASH_SOURCE[0]}`, a `# shellcheck source=` directive above every `.` include, and bash 3.2 compatibility — no associative arrays, no `${var,,}`. Flags are parsed by a `while`/`case` loop exiting `2` on an unknown option. Reporting goes through `devsetup_status`, never a bare `echo`; errors go to stderr.

```bash
formula="$(devsetup_config advanced.gpg.homebrewFormula gnupg)"
if [[ $uninstall -eq 1 ]]; then
	devsetup_uninstall_via_homebrew GPG "$formula" "$audit" || true
	exit 0
fi
devsetup_install_via_homebrew GPG "$formula" gpg \
	"Install GnuPG from https://gnupg.org/download/." "$audit" 0 "$check_upgrades"
```

PowerShell: a comment-based help block (`.SYNOPSIS` / `.DESCRIPTION`), a `param(...)` block of `[switch]`/`[string]` parameters, `$ErrorActionPreference = "Stop"`, dot-sourcing `config.ps1` relative to `$PSScriptRoot`, `throw` for hard errors, `Write-DevSetupStatus` for every reported line. Scripts resolving a path emit it as their final pipeline value, captured by the runner with `Select-Object -Last 1`.

```powershell
$config = Get-DevSetupConfig
$expiry = Get-DevSetupValue $config "advanced.gpg.keyExpiry" "2y"
if (-not $exe) {
    Write-DevSetupStatus warn "GPG" "missing and winget is unavailable"
    return
}
```

Platform detection is `uname -s` in bash (with a MinGW/MSYS/Cygwin guard redirecting the user to `setup.cmd`) and `platform.system()` mapped through `OS_KEYS` in Python; PowerShell scripts assume Windows because that is the only place they are invoked from.

Adding a setup step means doing all of it in one change: add the `user.install.<tool>` boolean and any `advanced.<tool>.*` values to the config; add `src/scripts/install-<tool>.sh` using `devsetup_install_via_homebrew` and `src/scripts/install-<tool>.ps1` using `Install-DevSetupWingetTool`, both supporting `--audit`, `--uninstall`, `--check-upgrades`, and `--print-path` where a path is needed; wire both into `setup.sh` and `setup.ps1` in every mode block (default, upgrade-check, uninstall) with a matching `[skip]` line when config disables it; and document the key and script in `README.md`. The two platform paths must stay behaviourally aligned — a change to one without the other is a bug, not a partial implementation.

## Blackout Secure conventions

These apply to every repository in the `blackoutsecure` organization.

### Branch model

- `main` is the default and only long-lived branch.
- Create short-lived feature branches from `main` and land changes through pull requests.
  Preserve required checks and reviews; a permanent `dev` branch is not needed.
- Keep existing version tags and configured release automation. Do not push directly to
  `main` or move tags by hand.

### Centrally managed files - do not hand-edit here

`blackoutsecure/bos-automation-hub` distributes community health and lint configuration
files through `bos-managed-file-sync-action`. Where a file in this repository carries a
managed-file-sync delimiter block, change the source under the hub's `sync-files/`, never
the copy here.

Here the only such block is in `.github/dependabot.yml`, delimited `# >>> bos-automation-hub:dependabot_actions >>>` / `# <<< bos-automation-hub:dependabot_actions <<<`. `.github/bos-universal-config.json` is repo-owned and enables the `common`, `lf_line_endings`, `editorconfig`, `markdownlint`, `yamllint`, `shellcheck`, and `python_ecosystem` sync services, so more managed files may appear on a future sync run.

### CI gate

Where a repository is wired to it, pushes and pull requests run the hub's reusable
`bos-universal-security.yml`, reported as a single required check: markdownlint, yamllint,
shellcheck, actionlint, `bos-code-scanning-kit`, CodeQL, dependency review, and compliance
checks for the canonical README header and a conventional-commit PR title.

This repository is **not** wired to it. There is no `.github/workflows/` directory and no workflow of any kind, so no gate runs here today. If a workflow is added, every `uses:` reference must be a commit SHA with a trailing version comment, for example `actions/checkout@<sha> # v4.2.2`.

## Boundaries

### Always

- Run `bash -n` and `shellcheck` on every shell script you touch, and read the `--audit` output before running anything for real.
- Prove idempotency by running the changed path twice on a disposable target and confirming the second run reports only `[found]` and `[skip]`.
- Give every new install step an audit path, an `--uninstall` decision, and a `[skip]` line when its `user.install.*` gate is false.
- Read tunables through `devsetup_config` / `Get-DevSetupValue` / `get()` with a fallback rather than hardcoding a value or duplicating lookup logic.
- Keep the macOS/Linux and Windows paths behaviourally aligned, and update `README.md` when a config key, option, or script changes.
- Route every reported line through the shared status helper so the run summary stays accurate.

### Ask first

- Adding a new package or dependency the kit installs, on either platform. Each one runs on someone else's machine.
- Changing default configuration the kit writes: `user.vscode.settings`, the extension install or block lists, `user.mcp.servers`, the dev container defaults, or any `advanced.*` package ID, formula, or download URL.
- Any change that is not idempotent, or that cannot be fully audited by `--audit` / `-Audit`.
- Changing what `--uninstall` removes, particularly Git or Homebrew, both excluded on purpose.
- Changing GPG behaviour: key type or expiry, what the export archive contains, where a passphrase is written, or the global git signing keys the helpers set.
- Adding a `.github/workflows/` directory, a build step, a package manifest, or a runtime dependency to a repository that deliberately has none.
- Changing the config schema, the `user`/`advanced` split, or the placeholder expansion rules.

### Never

- Never commit private keys, passphrases, GPG export archives, tokens, or personal dotfiles containing credentials. `config/dev-setup.config.json` is not a secret store.
- Never commit a real `user.git.userName` / `user.git.userEmail`, tenant or subscription identifiers, or an absolute path containing a username.
- Never run a destructive setup step without confirmation: no removal, no overwrite of existing user configuration, and no WSL restart outside an explicit `-Configure`.
- Never let the Linux/macOS and Windows paths silently diverge in behaviour. If a platform genuinely cannot support a step, report `[skip]` or `[warn]` and say why.
- Never print, log, or write a private key, passphrase, or archive password to `DEVSETUP_STATUS_LOG`, a status line, or any file outside the encrypted export archive.
- Never call `sudo`, require admin rights, launch a GUI installer, or prompt for a password in a path a non-interactive run can reach.
- Never weaken a check to make something work: do not drop `set -euo pipefail`, add a blanket `shellcheck disable`, or swallow a non-zero exit to get a clean run.
- Never push directly to `main` or move a version tag by hand; use reviewed pull requests
  and configured release automation.
