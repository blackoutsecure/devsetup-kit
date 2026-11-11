---
description: "Personal defaults for terminal commands, builds, tests, debugging, servers and watchers: visible foreground execution, bounded waits, and restart consent."
applyTo: "**"
---

# Visible, bounded terminal execution

- Prefer VS Code's integrated-terminal tool and reveal output in the main Terminal panel. Reuse an idle, dedicated agent terminal; never send commands into a terminal busy with the user's work. Keep non-sensitive stdout and stderr visible and do not clear output.
- Run finite commands synchronously in the foreground. Do not use background jobs, detached processes, hidden windows, or async mode for ordinary builds, tests, linting, or installs just to return sooner.
- Choose a wall-clock deadline before each command: normally 120 seconds for quick commands and 600 seconds for builds, tests, or installs. Explain a longer budget for a known slow operation. A tool wait timeout may only stop waiting, not stop the process.
- After 60 seconds without useful output, inspect for prompts, process activity, or broken shell integration when control is available. Silence alone does not prove a hang. Never reset the deadline by repeated polling.
- Prefer noninteractive options and disable pagers. Respect destructive-operation approvals. If completion detection breaks, use a fresh visible terminal instead of waiting indefinitely.
- On deadline expiry, interrupt only the command you started, allow a short bounded grace period, then terminate only its known PID or owned process tree if needed. Never kill by process name or close a user-owned terminal. Report timeout and partial results honestly; retry only after a concrete correction.
- Servers, watch mode, and debuggers are long-lived: do not wait for them to exit as a test of readiness. Use a separate visible terminal, verify readiness within a finite deadline (for example an HTTP health check), and continue validation. State how to stop them. Stop temporary helpers after validation; leave a service running only when requested.
- If the harness cannot expose commands in the integrated terminal, explain the limitation and use synchronous shell execution with output in chat instead. Never claim hidden output is visible in the Terminal panel.
- Never close, reload, or restart VS Code, terminate terminal sessions, or restart WSL automatically. Print the reason and manual restart instructions in the terminal, then let the user decide. Broad unattended permissions are not restart consent. An override must be explicitly supplied for that run, never saved as a default.
- Prefer non-admin/non-root execution, user-local installs, and project virtual environments. Never silently elevate, invoke sudo, or grant passwordless sudo.
