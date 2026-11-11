# Contributing to Blackout Secure Dev Setup Kit

Thank you for your interest in contributing.

## Getting started

1. Fork the repository.
2. Clone your fork:
   `git clone https://github.com/your-username/bos-devsetup-kit.git`
3. Create a feature branch: `git checkout -b feat/your-feature`.
4. Run the setup script to install the local toolchain. ShellCheck is included
   by default; optional additional lint tooling includes:
   - [PSScriptAnalyzer](https://github.com/PowerShell/PSScriptAnalyzer) for `*.ps1`
   - [`shellcheck`](https://www.shellcheck.net/) for `*.sh`
   - [`ruff`](https://github.com/astral-sh/ruff) for `src/configure-vscode.py`

## Development

Every tunable lives in [`config/dev-setup.config.json`](config/dev-setup.config.json).
Prefer adding or changing a config key over hardcoding a new value in a script.

Run an installer script on its own to iterate quickly, for example:

```powershell
pwsh ./src/scripts/install-node.ps1 -Audit
```

```bash
bash ./src/scripts/install-node.sh --audit
```

Run the full setup in audit mode before testing a real run:

```powershell
.\setup.ps1 -Audit
```

```bash
./setup.sh --audit
```

## Pull request process

1. Test both the audit and real-run paths for anything you touch.
2. Update `README.md` if you add or change a config key, option, or script.
3. Keep platform parity — a behavior change to the PowerShell path should have
   a matching bash change, and vice versa, unless the platforms genuinely diverge.
4. Open the PR with a clear description of the change and the motivation.

## Code style

- No admin/root access, no `sudo`, no WSL. Every step must work per-user.
- Every step must be idempotent and safe to re-run.
- Every install step needs an audit path that detects and reports without
  writing anything.
- Follow `.editorconfig` (4-space indent, LF line endings, tabs in `*.sh`).
- Read tunables through the shared config loader (`src/config.ps1`,
  `src/config.sh`) rather than duplicating lookup logic.

## Reporting issues

- Use [GitHub Issues](https://github.com/blackoutsecure/bos-devsetup-kit/issues)
  for bug reports.
- Include your OS/shell, the `-Audit`/`--audit` output, and the relevant
  section of your `config/dev-setup.config.json`.
- For security issues, follow the organization-wide
  [Security Policy](https://github.com/blackoutsecure/.github/blob/main/SECURITY.md)
  and report privately via
  [GitHub Security Advisories](https://github.com/blackoutsecure/bos-devsetup-kit/security/advisories/new).

## License

By contributing, you agree that your contributions will be licensed under
the Apache License, Version 2.0.
