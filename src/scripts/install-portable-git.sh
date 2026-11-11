#!/usr/bin/env bash
#
# Ensures a usable Git is available without requiring sudo/admin rights, then
# applies the configured credential helper and (if set) the git identity.
#
# macOS: git ships with Xcode Command Line Tools; Apple requires its
#        installer UI if the tools are missing.
# Linux: prefers an existing git on PATH; falls back to installing
#        Homebrew for Linux (linuxbrew, installs entirely under $HOME,
#        no root required) and using it to install git.
#
# --audit reports what would happen without changing anything.
#
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../config.sh
. "$script_dir/../config.sh"

audit=0
print_path=0
uninstall=0
check_upgrades=0
while [[ $# -gt 0 ]]; do
	case "$1" in
		--audit) audit=1 ;;
		--print-path) print_path=1 ;;
		--uninstall) uninstall=1 ;;
		--check-upgrades) check_upgrades=1 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

devsetup_assert_execution_mode "$audit"

if [[ $uninstall -eq 1 ]]; then
	# Uninstall would also need to unwind global credential/identity config this
	# script wrote, which isn't safe to automate. Leave Git out of --uninstall.
	devsetup_status warn Git "uninstall is not supported; remove it via your OS package manager manually if needed"
	exit 0
fi

os="$(uname -s)"
formula="$(devsetup_config advanced.git.homebrewFormula git)"

if command -v git >/dev/null 2>&1; then
	devsetup_status found Git "$(git --version) at $(command -v git)"
	git_present=1
else
	git_present=0
fi

# Only the Linux/Homebrew-managed install is ours to report on; macOS's git comes
# from Xcode Command Line Tools and is left to Apple's own update mechanism.
if [[ $check_upgrades -eq 1 && $git_present -eq 1 && "$os" == "Linux" ]]; then
	devsetup_check_homebrew_upgrade Git "$formula"
fi

git_credential_helper_status() {
	local helper effective exec_path config_status
	case "$os" in
		Darwin) helper="$(devsetup_config advanced.git.credential.macos.helper osxkeychain)" ;;
		*)      helper="$(devsetup_config advanced.git.credential.linux.helper manager)" ;;
	esac
	if effective="$(git config --get credential.helper)"; then
		if [[ "$effective" == "$helper" ]]; then
			devsetup_status found "git cfg" "credential helper '$helper' already configured"
		else
			devsetup_status skip "git cfg" "existing credential helper preserved"
		fi
	else
		config_status=$?
		if [[ $config_status -ne 1 ]]; then return "$config_status"; fi
		exec_path="$(git --exec-path)"
		if command -v "git-credential-$helper" >/dev/null 2>&1 || [[ -x "$exec_path/git-credential-$helper" ]]; then
			if [[ $audit -eq 1 ]]; then
				devsetup_status install "git cfg" "would set credential helper to '$helper'"
			else
				git config --global credential.helper "$helper"
				devsetup_status install "git cfg" "credential helper set to '$helper'"
			fi
		else
			devsetup_status skip "git cfg" "credential helper '$helper' is not installed"
		fi
	fi
}

if [[ $audit -eq 1 ]]; then
	if [[ $git_present -eq 0 ]]; then
		case "$os" in
			Darwin) devsetup_status warn Git "missing; run xcode-select --install once" ;;
			Linux)  devsetup_audit_homebrew_install Git "$formula" || true ;;
		esac
	fi
	if [[ $git_present -eq 1 ]]; then git_credential_helper_status; fi
	devsetup_git_identity_status 1
	if [[ $print_path -eq 1 && $git_present -eq 1 ]]; then
		command -v git
	fi
	exit 0
fi

if [[ $git_present -eq 0 ]]; then
	case "$os" in
		Darwin)
			if ! xcode-select -p >/dev/null 2>&1; then
				devsetup_status warn Git "missing; macOS requires 'xcode-select --install' once"
				exit 1
			fi
			echo "Git was not found even though Xcode Command Line Tools are present." >&2
			exit 1
			;;
		Linux)
			devsetup_status install Git "installing '$formula' via Homebrew (live output below, may take a few minutes)"
			if ! devsetup_ensure_homebrew; then
				printf 'Git is unavailable and Homebrew could not be installed.\n' >&2
				exit 1
			fi
			NONINTERACTIVE=1 brew install --formula "$formula" < /dev/null
			devsetup_status found Git "$(git --version) at $(command -v git)"
			;;
		*)
			echo "Unsupported OS: $os" >&2
			exit 1
			;;
	esac
fi

git_credential_helper_status

user_name="$(devsetup_config user.git.userName "")"
user_email="$(devsetup_config user.git.userEmail "")"
# Plain ifs, not && chains: an empty value would trip set -e.
if [[ -n "$user_name" ]]; then
	git config --global user.name "$user_name"
fi
if [[ -n "$user_email" ]]; then
	git config --global user.email "$user_email"
fi
devsetup_git_identity_status

if [[ $print_path -eq 1 ]]; then
	command -v git
fi
