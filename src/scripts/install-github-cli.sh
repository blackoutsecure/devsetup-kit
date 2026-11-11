#!/usr/bin/env bash
# Ensures GitHub CLI is available for repository and PR automation.
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

formula="$(devsetup_config advanced.githubCli.homebrewFormula gh)"

if [[ $uninstall -eq 1 ]]; then
	devsetup_uninstall_via_homebrew "GitHub CLI" "$formula" "$audit" || true
	exit 0
fi

devsetup_install_via_homebrew "GitHub CLI" "$formula" gh \
	"Install GitHub CLI from https://cli.github.com/." "$audit" 0 "$check_upgrades"
