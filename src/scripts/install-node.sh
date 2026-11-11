#!/usr/bin/env bash
#
# Ensures Node.js and npm are available without admin rights or GUI installers.
# The Homebrew formula comes from dev-setup.config.json.
#
# --audit reports what would happen without changing anything.
#
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../config.sh
. "$script_dir/../config.sh"

audit=0
uninstall=0
check_upgrades=0
while [[ $# -gt 0 ]]; do
	case "$1" in
		--audit) audit=1 ;;
		--uninstall) uninstall=1 ;;
		--check-upgrades) check_upgrades=1 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

devsetup_assert_execution_mode "$audit"

formula="$(devsetup_config advanced.node.homebrewFormula node)"

if [[ $uninstall -eq 1 ]]; then
	devsetup_uninstall_via_homebrew Node.js "$formula" "$audit" || true
	exit 0
fi

if command -v node >/dev/null 2>&1 && node --version >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && npm --version >/dev/null 2>&1; then
	devsetup_status found Node.js "$(node --version) at $(command -v node)"
	devsetup_status found npm "$(npm --version) at $(command -v npm)"
	[[ $check_upgrades -eq 1 ]] && devsetup_check_homebrew_upgrade Node.js "$formula"
	exit 0
fi

os="$(uname -s 2>/dev/null || printf '%s' "${MSYSTEM:-Windows}")"

if [[ $audit -eq 1 ]]; then
	case "$os" in
		Darwin|Linux) devsetup_status install Node.js "would install '$formula' via user-local Homebrew" ;;
		*) devsetup_status warn Node.js "unsupported OS: $os" ;;
	esac
	exit 0
fi

case "$os" in
	Darwin|Linux)
		if ! devsetup_ensure_homebrew; then
			printf 'Node.js/npm unavailable and Homebrew could not be installed. Install Node.js LTS from https://nodejs.org/.\n' >&2
			exit 1
		fi
		devsetup_status install Node.js "installing '$formula' via Homebrew (live output below, may take a few minutes)"
		NONINTERACTIVE=1 brew install --formula "$formula" < /dev/null
		;;
	MINGW*|MSYS*|CYGWIN*)
		printf 'Node.js/npm unavailable in this shell. Run setup.cmd on Windows.\n' >&2
		exit 1
		;;
	*)
		printf 'Unsupported OS: %s\n' "$os" >&2
		exit 1
		;;
esac

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
	printf 'Node.js/npm setup failed. Open a new terminal and run setup again.\n' >&2
	exit 1
fi

devsetup_status found Node.js "$(node --version) at $(command -v node)"
devsetup_status found npm "$(npm --version) at $(command -v npm)"
[[ $check_upgrades -eq 1 ]] && devsetup_check_homebrew_upgrade Node.js "$formula"
