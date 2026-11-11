#!/usr/bin/env bash
#
# Sourceable config reader for dev-setup.
#
#   . "$(dirname "$0")/../config.sh"
#   version="$(devsetup_config user.python.version 3.14)"
#
# Reads the config with python3, python, or jq - whichever exists. The config is
# needed before Python is installed, so every lookup falls back to the
# caller-supplied default rather than failing.
#
# DEVSETUP_ROOT is the repository root, resolved from this file's location.

DEVSETUP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVSETUP_CONFIG_FILE="${DEVSETUP_CONFIG_FILE:-$DEVSETUP_ROOT/config/dev-setup.config.json}"

# The reader is resolved once, here at source time, which runs in the caller's
# shell. Every devsetup_config call happens inside a $( ) subshell, so a value
# cached during a lookup would be discarded; only a value set at source time is
# inherited. A plain variable rather than an associative array keeps this
# working on macOS's bash 3.2.
DEVSETUP_READER=""
for _devsetup_candidate in python3 python; do
	if command -v "$_devsetup_candidate" >/dev/null 2>&1 &&
		"$_devsetup_candidate" --version >/dev/null 2>&1; then
		DEVSETUP_READER="$_devsetup_candidate"
		break
	fi
done
if [[ -z "$DEVSETUP_READER" ]] && command -v jq >/dev/null 2>&1; then
	DEVSETUP_READER="jq"
fi
unset _devsetup_candidate

devsetup_is_elevated() {
	[[ "$EUID" -eq 0 ]]
}

devsetup_assert_execution_mode() {
	local read_only="${1:-0}" admin_mode="${DEVSETUP_ADMIN_MODE:-0}"
	case "$admin_mode" in
		0|1) ;;
		*)
			printf 'DEVSETUP_ADMIN_MODE must be 0 (standard user, the default) or 1 (explicit admin opt-in).\n' >&2
			return 2
			;;
	esac
	if ! devsetup_is_elevated; then return 0; fi
	if [[ "$read_only" -eq 1 ]]; then
		devsetup_status warn "Execution mode" "root read-only inspection; run write operations from a standard, non-root shell" >&2
	elif [[ "$admin_mode" == 1 ]]; then
		devsetup_status warn "Execution mode" "explicit admin mode enabled; child processes inherit root; installation scope remains per-user" >&2
	else
		printf 'Run this script from a standard, non-root shell. To explicitly permit an already-root shell for this run, set DEVSETUP_ADMIN_MODE=1. No automatic elevation or de-elevation is performed.\n' >&2
		return 1
	fi
}

devsetup_homebrew_write_problem() {
	local prefix home_root
	if devsetup_is_elevated; then
		printf 'Homebrew does not support root execution, even with DEVSETUP_ADMIN_MODE=1. Use a standard user.\n' >&2
		return 1
	fi
	prefix="$(brew --prefix)" || { printf 'Cannot determine the Homebrew prefix.\n' >&2; return 1; }
	prefix="$(cd "$prefix" && pwd -P)" || { printf 'Cannot resolve the Homebrew prefix.\n' >&2; return 1; }
	home_root="$(cd "$HOME" && pwd -P)" || { printf 'Cannot resolve the user home directory.\n' >&2; return 1; }
	if [[ "${DEVSETUP_ADMIN_MODE:-0}" == 1 ]]; then return 0; fi
	case "$prefix" in
		"$home_root"/*) ;;
		*)
			printf 'refusing to modify shared prefix %s in standard-user mode; use user-local Homebrew or explicitly opt in with DEVSETUP_ADMIN_MODE=1 from a permitted non-root account\n' "$prefix" >&2
			return 1
			;;
	esac
}

devsetup_assert_homebrew_write() {
	local problem
	if problem="$(devsetup_homebrew_write_problem 2>&1)"; then return 0; fi
	devsetup_status warn Homebrew "$problem" >&2
	return 1
}

devsetup_config_reader() {
	[[ -n "$DEVSETUP_READER" ]] || return 1
	printf '%s' "$DEVSETUP_READER"
}

devsetup_config() {
	local key="$1"
	local default="${2-}"
	local value

	if [[ ! -f "$DEVSETUP_CONFIG_FILE" || -z "$DEVSETUP_READER" ]]; then
		printf '%s' "$default"
		return 0
	fi

	if [[ "$DEVSETUP_READER" == "jq" ]]; then
		value="$(jq -r --arg k "$key" '
			reduce ($k | split(".")[]) as $s (.; if type == "object" then .[$s] else null end)
			| if . == null then empty
			  elif type == "array" then .[] | tostring
			  else tostring end
		' "$DEVSETUP_CONFIG_FILE" 2>/dev/null)" || value=""
	else
		value="$("$DEVSETUP_READER" -c '
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    node = json.load(open(path, encoding="utf-8"))
except Exception:
    sys.exit(1)
for segment in key.split("."):
    if not isinstance(node, dict) or segment not in node:
        sys.exit(1)
    node = node[segment]
if node is None:
    sys.exit(1)
if isinstance(node, bool):
    value = "true" if node else "false"
elif isinstance(node, list):
    value = "\n".join(str(item) for item in node)
else:
    value = str(node)
sys.stdout.buffer.write((value + "\n").encode("utf-8"))
' "$DEVSETUP_CONFIG_FILE" "$key" 2>/dev/null)" || value=""
	fi

	# Empty means unset in the config; fall back like the PowerShell loader does.
	if [[ -z "$value" ]]; then
		printf '%s' "$default"
	else
		printf '%s' "$value"
	fi
}

devsetup_config_list() {
	local key="$1" default="${2-}"
	if [[ ! -f "$DEVSETUP_CONFIG_FILE" || -z "$DEVSETUP_READER" ]]; then
		[[ -z "$default" ]] || printf '%s\n' "$default"
		return 0
	fi
	if [[ "$DEVSETUP_READER" == jq ]]; then
		jq -r --arg key "$key" --arg fallback "$default" '
			reduce ($key | split(".")[]) as $part (.; if type == "object" then .[$part] else null end)
			| if . == null or . == "" then ($fallback | split("\n") | map(select(. != ""))) else . end
			| if type != "array" then error($key + " must be an array of non-empty strings")
			  elif any(.[]; if type == "string" then (test("^[[:space:]]*$") or test("[\r\n]")) else true end)
			  then error($key + " must contain non-empty, single-line strings")
			  else reduce .[] as $item ([]; if index($item) == null then . + [$item] else . end) | .[] end
		' "$DEVSETUP_CONFIG_FILE" | tr -d '\r'
	else
		"$DEVSETUP_READER" -c '
import json, sys
path, key, fallback = sys.argv[1:]
with open(path, encoding="utf-8-sig") as handle:
    node = json.load(handle)
for segment in key.split("."):
    node = node.get(segment) if isinstance(node, dict) else None
if node is None or node == "":
    node = fallback.splitlines()
if not isinstance(node, list) or any(
    not isinstance(item, str) or not item.strip() or "\n" in item or "\r" in item
    for item in node
):
    raise SystemExit(key + " must be an array of non-empty, single-line strings")
value = "\n".join(dict.fromkeys(node))
if value:
    sys.stdout.buffer.write((value + "\n").encode("utf-8"))
' "$DEVSETUP_CONFIG_FILE" "$key" "$default"
	fi
}

devsetup_enabled() {
	[[ "$(devsetup_config "$1" "${2:-true}")" == "true" ]]
}

devsetup_homebrew_path() {
	local configured_path
	if command -v brew >/dev/null 2>&1; then
		command -v brew
		return 0
	fi

	configured_path="$(devsetup_config advanced.git.linuxbrewShellenv "\$HOME/.linuxbrew/bin/brew")"
	configured_path="${configured_path/#\$HOME/$HOME}"
	if [[ -x "$configured_path" ]]; then
		printf '%s\n' "$configured_path"
		return 0
	fi
	return 1
}

devsetup_rust_tool_path() {
	local tool="$1" candidate cargo_bin brew_path formula brew_tool
	cargo_bin="${CARGO_HOME:-$HOME/.cargo}/bin"
	candidate="$(command -v "$tool" || true)"
	if [[ -z "$candidate" && -x "$cargo_bin/$tool" ]]; then candidate="$cargo_bin/$tool"; fi
	brew_path="$(devsetup_homebrew_path || true)"
	if [[ -n "$brew_path" ]]; then
		formula="$(devsetup_config advanced.rust.homebrewFormula rustup)"
		brew_tool="$("$brew_path" --prefix)/opt/$formula/bin/$tool"
		if [[ -x "$brew_tool" && ( -z "$candidate" || "$candidate" -ef "$brew_tool" ) ]]; then
			candidate="$brew_tool"
		fi
	fi
	[[ -n "$candidate" ]] || return 1
	printf '%s\n' "$candidate"
}

devsetup_persist_rust_path() {
	local tool_dir="$1" audit="${2:-0}" cargo_bin profile path_line
	cargo_bin="${CARGO_HOME:-$HOME/.cargo}/bin"
	profile="$HOME/.profile"
	if [[ "$(uname -s)" == Darwin ]]; then profile="$HOME/.zprofile"; fi
	printf -v path_line "export PATH=%q:%q:\"\$PATH\"" "$tool_dir" "$cargo_bin"
	if [[ -f "$profile" ]] && grep -Fqx "$path_line" "$profile"; then
		devsetup_status found "Rust PATH" "already configured in $profile"
	elif [[ "$audit" -eq 1 ]]; then
		devsetup_status install "Rust PATH" "would add Rust tools to $profile (new login shells)"
	else
		if [[ -f "$profile" ]]; then cp "$profile" "$profile.devsetup-backup-$(date -u +%Y%m%d%H%M%S)"; fi
		printf '\n# Added by bos-devsetup-kit for Rust.\n%s\n' "$path_line" >> "$profile"
		devsetup_status install "Rust PATH" "added Rust tools to $profile (new login shells)"
	fi
}

devsetup_activate_homebrew() {
	local brew_path
	brew_path="$(devsetup_homebrew_path 2>/dev/null || true)"
	[[ -n "$brew_path" ]] || return 1
	eval "$("$brew_path" shellenv)"
	command -v brew >/dev/null 2>&1
}

devsetup_audit_homebrew_install() {
	local component="$1" formula="$2" problem
	if devsetup_homebrew_path >/dev/null 2>&1; then
		if ! problem="$(devsetup_activate_homebrew && devsetup_homebrew_write_problem 2>&1)"; then
			devsetup_status warn "$component" "cannot install '$formula': ${problem:-Homebrew could not be activated}"
			return 1
		fi
	fi
	devsetup_status install "$component" "would install '$formula' via Homebrew"
}

devsetup_persist_homebrew_shellenv() {
	local brew_path="$1" profile shellenv_line backup
	if [[ "$(uname -s 2>/dev/null)" == "Darwin" ]]; then
		profile="$HOME/.zprofile"
	else
		profile="$HOME/.profile"
	fi
	printf -v shellenv_line "eval \"\$(\"%s\" shellenv)\"" "$brew_path"
	if [[ -f "$profile" ]] && grep -Fqx "$shellenv_line" "$profile"; then
		return 0
	fi
	if [[ -f "$profile" ]]; then
		backup="${profile}.devsetup-backup-$(date -u +%Y%m%d%H%M%S)"
		cp "$profile" "$backup"
		devsetup_status install Homebrew "backed up $profile to $backup" >&2
	fi
	printf '\n# Added by bos-devsetup-kit for user-local Homebrew.\n%s\n' "$shellenv_line" >> "$profile"
	devsetup_status install Homebrew "shell environment added to $profile" >&2
}

devsetup_ensure_homebrew() {
	local archive_url brew_path parent prefix stage
	if devsetup_is_elevated; then
		printf 'Homebrew does not support root execution, even with DEVSETUP_ADMIN_MODE=1. Use a standard user.\n' >&2
		return 1
	fi
	if devsetup_activate_homebrew; then
		devsetup_assert_homebrew_write
		return $?
	fi
	case "$(uname -s 2>/dev/null)" in
		Darwin|Linux) ;;
		*) return 1 ;;
	esac

	brew_path="$(devsetup_config advanced.git.linuxbrewShellenv "\$HOME/.linuxbrew/bin/brew")"
	brew_path="${brew_path/#\$HOME/$HOME}"
	prefix="$(dirname "$(dirname "$brew_path")")"
	case "$prefix" in
		"$HOME"/*) ;;
		*)
			printf 'Refusing to bootstrap Homebrew outside the user profile: %s\n' "$prefix" >&2
			return 1
			;;
	esac
	if [[ -e "$prefix" ]]; then
		printf 'Homebrew prefix exists but does not contain an executable brew: %s\n' "$prefix" >&2
		return 1
	fi

	archive_url="$(devsetup_config advanced.git.homebrewInstallUrl https://github.com/Homebrew/brew/archive/refs/heads/master.tar.gz)"
	parent="$(dirname "$prefix")"
	if ! mkdir -p "$parent"; then
		printf 'Unable to create the Homebrew parent directory: %s\n' "$parent" >&2
		return 1
	fi
	if ! stage="$(mktemp -d "$parent/.linuxbrew-install.XXXXXX")"; then
		printf 'Unable to create a temporary Homebrew staging directory under: %s\n' "$parent" >&2
		return 1
	fi
	devsetup_status install Homebrew "installing user-local Homebrew to $prefix" >&2
	if ! curl -fsSL "$archive_url" | tar -xzf - --strip-components=1 -C "$stage"; then
		rm -rf "$stage"
		return 1
	fi
	if ! mv "$stage" "$prefix"; then
		rm -rf "$stage"
		printf 'Unable to move the staged Homebrew installation to: %s\n' "$prefix" >&2
		return 1
	fi
	if ! devsetup_activate_homebrew; then
		rm -rf "$prefix"
		printf 'Homebrew could not run from the user-local prefix; removed incomplete install: %s\n' "$prefix" >&2
		return 1
	fi
	devsetup_persist_homebrew_shellenv "$brew_path"
}

# Shared single-command Homebrew install pattern for install-php.sh,
# install-powershell.sh, and install-shellcheck.sh, which differ only in
# component name, formula, and command to look for.
#   $1 component name   $2 formula        $3 command to look for on PATH
#   $4 manual-install hint (used on failure)
#   $5 audit (0/1)      $6 print-path (0/1, default 0)  $7 check-upgrades (0/1, default 0)
# Prints the resolved command path on stdout when print-path is requested.
devsetup_install_via_homebrew() {
	local component="$1" formula="$2" command_name="$3" manual_hint="$4" audit="$5" print_path="${6:-0}" check_upgrades="${7:-0}"
	local command_path=""
	if command -v "$command_name" >/dev/null 2>&1 && "$command_name" --version >/dev/null 2>&1; then
		command_path="$(command -v "$command_name")"
	fi

	if [[ "$audit" -eq 1 ]]; then
		if [[ -n "$command_path" ]]; then
			devsetup_status found "$component" "$("$command_path" --version 2>&1 | head -n 1) at $command_path"
			[[ "$check_upgrades" -eq 1 ]] && devsetup_check_homebrew_upgrade "$component" "$formula"
		else
			case "$(uname -s 2>/dev/null)" in
				Darwin|Linux) devsetup_audit_homebrew_install "$component" "$formula" || true ;;
				*) devsetup_status warn "$component" "missing and Homebrew is unavailable on this platform" ;;
			esac
		fi
		return 0
	fi

	if [[ -z "$command_path" ]]; then
		local os
		os="$(uname -s 2>/dev/null || printf '%s' "${MSYSTEM:-Windows}")"
		if [[ "$os" != "Darwin" && "$os" != "Linux" ]]; then
			printf '%s setup is unsupported on %s.\n' "$component" "$os" >&2
			return 1
		fi
		if ! devsetup_ensure_homebrew; then
			printf '%s is unavailable and Homebrew could not be installed. %s\n' "$component" "$manual_hint" >&2
			return 1
		fi
		devsetup_status install "$component" "installing '$formula' via Homebrew (live output below, may take a few minutes)" >&2
		NONINTERACTIVE=1 brew install --formula "$formula" < /dev/null >&2
		command_path="$(command -v "$command_name" || true)"
	fi

	if [[ -z "$command_path" ]] || ! "$command_path" --version >/dev/null 2>&1; then
		printf '%s setup failed. Open a new terminal and run setup again.\n' "$component" >&2
		return 1
	fi

	if [[ "$print_path" -eq 1 ]]; then
		devsetup_status found "$component" "$("$command_path" --version 2>&1 | head -n 1) at $command_path" >&2
		printf '%s\n' "$command_path"
	else
		devsetup_status found "$component" "$("$command_path" --version 2>&1 | head -n 1) at $command_path"
	fi
	if [[ "$check_upgrades" -eq 1 ]]; then
		if [[ "$print_path" -eq 1 ]]; then
			devsetup_check_homebrew_upgrade "$component" "$formula" >&2
		else
			devsetup_check_homebrew_upgrade "$component" "$formula"
		fi
	fi
	return 0
}

# Reports (never applies) whether Homebrew has a newer version of a formula.
# Silent when Homebrew is unavailable or the formula is already current.
devsetup_check_homebrew_upgrade() {
	local component="$1" formula="$2" outdated installed latest reader update_count
	devsetup_activate_homebrew || return 0
	outdated="$(brew outdated --formula --json=v2 "$formula" 2>/dev/null || true)"
	if [[ -n "$outdated" ]]; then
		update_count=0
		reader="$(devsetup_config_reader 2>/dev/null || true)"
		if [[ "$reader" == "jq" ]]; then
			update_count="$(printf '%s' "$outdated" | jq -r '(.formulae // []) | length' 2>/dev/null || printf '0')"
		elif [[ -n "$reader" ]]; then
			update_count="$(printf '%s' "$outdated" | "$reader" -c 'import json, sys; print(len(json.load(sys.stdin).get("formulae") or []))' 2>/dev/null || printf '0')"
		fi
		[[ "$update_count" -gt 0 ]] || return 0
		installed="unknown"
		latest="unknown"
		if [[ "$reader" == "jq" ]]; then
			installed="$(printf '%s' "$outdated" | jq -r '.formulae[0].installed_versions[0] // "unknown"' 2>/dev/null || printf 'unknown')"
			latest="$(printf '%s' "$outdated" | jq -r '.formulae[0].current_version // "unknown"' 2>/dev/null || printf 'unknown')"
		elif [[ -n "$reader" ]]; then
			installed="$(printf '%s' "$outdated" | "$reader" -c 'import json, sys; data=json.load(sys.stdin); item=(data.get("formulae") or [{}])[0]; print((item.get("installed_versions") or ["unknown"])[0])' 2>/dev/null || printf 'unknown')"
			latest="$(printf '%s' "$outdated" | "$reader" -c 'import json, sys; data=json.load(sys.stdin); item=(data.get("formulae") or [{}])[0]; print(item.get("current_version") or "unknown")' 2>/dev/null || printf 'unknown')"
		fi
		devsetup_status update "$component" "newer version available: installed $installed, latest $latest (run: brew upgrade $formula)"
	fi
}

# Removes a Homebrew-managed formula. Only ever called when --uninstall is passed explicitly.
devsetup_uninstall_via_homebrew() {
	local component="$1" formula="$2" audit="${3:-0}"
	if ! devsetup_activate_homebrew; then
		devsetup_status warn "$component" "Homebrew is unavailable; cannot uninstall"
		return 1
	fi
	if [[ "$audit" -eq 1 ]]; then
		devsetup_status remove "$component" "would uninstall '$formula' via Homebrew"
		return 0
	fi
	devsetup_assert_homebrew_write || return 1
	if brew uninstall --formula "$formula" >/dev/null 2>&1; then
		devsetup_status remove "$component" "uninstalled '$formula' via Homebrew"
	else
		devsetup_status warn "$component" "not installed via Homebrew, or uninstall failed"
	fi
}

# One audit line per component so a run reads as a report.
#   found   - already present, nothing to do
#   install - something is about to change
#   skip    - disabled in config, or not applicable on this platform
#   warn    - proceeded, but the result is degraded
#   update  - a newer version is available (reported only, never applied automatically)
#   remove  - uninstalled, only reachable via --uninstall
#
# Colors honour the de-facto NO_COLOR standard (https://no-color.org) and
# only render when the destination is a TTY or the GitHub Actions log
# surface, matching the palette bos-code-scanning-kit uses for severities.
_DEVSETUP_RESET=$'\033[0m'
devsetup__color_enabled() {
	[[ -n "${NO_COLOR:-}" ]] && return 1
	[[ "${GITHUB_ACTIONS:-}" == "true" ]] && return 0
	[[ -t 1 ]]
}

devsetup_status() {
	local state="$1" component="$2" detail="${3-}" color="" tag
	case "$state" in
		found) color=$'\033[32m' ;;   # green   - already satisfied
		install) color=$'\033[36m' ;; # cyan    - change in progress
		warn) color=$'\033[33m' ;;    # yellow  - degraded but proceeded
		skip) color=$'\033[90m' ;;    # grey    - disabled or n/a
		update) color=$'\033[35m' ;;  # magenta - newer version available
		remove) color=$'\033[31m' ;;  # red     - uninstalled via --uninstall
	esac
	tag="$(printf '%-9s' "[$state]")"
	if [[ -n "$color" ]] && devsetup__color_enabled; then
		tag="${color}${tag}${_DEVSETUP_RESET}"
	fi
	printf '  %s %-8s %s\n' "$tag" "$component" "$detail"

	# DEVSETUP_STATUS_LOG lets the top-level runner tally every line, including
	# ones from install-*.sh scripts that run as separate bash processes and
	# ones emitted by configure-vscode.py.
	if [[ -n "${DEVSETUP_STATUS_LOG:-}" ]]; then
		printf '%s|%s|%s\n' "$state" "$component" "$detail" >> "$DEVSETUP_STATUS_LOG"
	fi
}

# Prints one total per status tag for the whole run, reading whatever
# devsetup_status calls (from any process) logged to DEVSETUP_STATUS_LOG. In
# --audit runs, also recommends whether to run the real setup, lists what it
# would change, and gives the exact command.
devsetup_summary() {
	local log_path="${1:-}" audit="${2:-0}" found=0 install=0 skip=0 warn=0 update=0 remove=0
	local apply_command="${3:-./setup.sh}"
	local warn_label install_label summary_line update_label
	if [[ -n "$log_path" && -f "$log_path" ]]; then
		found="$(grep -c '^found|' "$log_path" || true)"
		install="$(grep -c '^install|' "$log_path" || true)"
		skip="$(grep -c '^skip|' "$log_path" || true)"
		warn="$(grep -c '^warn|' "$log_path" || true)"
		update="$(grep -c '^update|' "$log_path" || true)"
		remove="$(grep -c '^remove|' "$log_path" || true)"
	fi
	warn_label="warnings"
	[[ "$warn" -eq 1 ]] && warn_label="warning"
	install_label="installed"
	[[ "$audit" -eq 1 ]] && install_label="would install"
	echo
	summary_line="Summary: $found found, $install $install_label, $skip skipped, $warn $warn_label"
	if [[ "$update" -gt 0 ]]; then
		update_label="updates"
		[[ "$update" -eq 1 ]] && update_label="update"
		summary_line="$summary_line, $update $update_label available"
	fi
	if [[ "$remove" -gt 0 ]]; then
		summary_line="$summary_line, $remove removed"
	fi
	echo "$summary_line"

	if [[ "$audit" -eq 1 ]]; then
		echo
		if [[ "$install" -eq 0 ]]; then
			echo "Recommendation: no changes needed, environment already matches config/dev-setup.config.json. No need to run without --audit."
		else
			echo "Recommendation: $install change(s) would be made if you run the real setup:"
			grep '^install|' "$log_path" | while IFS='|' read -r _ component detail; do
				echo "  - ${component}: ${detail}"
			done
			echo "Run this to apply them: $apply_command"
		fi
		if [[ "$warn" -gt 0 ]]; then
			echo "$warn item(s) need attention regardless (see [warn] lines above)."
		fi
	fi
}

# Reports git identity state identically in audit and apply runs.
# Usage: devsetup_git_identity_status [audit]
devsetup_git_identity_status() {
	local audit="${1:-0}" configured current verb
	configured="$(devsetup_config user.git.userEmail "")"
	current="$(git config --global --get user.email 2>/dev/null || true)"

	if [[ -n "$configured" ]]; then
		if [[ "$audit" == "1" ]]; then verb="would apply"; else verb="applied"; fi
		devsetup_status install identity "$verb $configured from config"
	elif [[ -n "$current" ]]; then
		devsetup_status found identity "already set to $current"
	else
		devsetup_status warn identity "not set; fill user.git.userName / user.git.userEmail"
	fi
}
