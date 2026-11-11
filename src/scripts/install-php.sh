#!/usr/bin/env bash
#
# Ensures PHP is available for VS Code's built-in PHP validator.
# --print-path prints only the executable path on stdout; --audit changes nothing.
#
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../config.sh
. "$script_dir/../config.sh"

print_path=0
audit=0
uninstall=0
check_upgrades=0
while [[ $# -gt 0 ]]; do
	case "$1" in
		--print-path) print_path=1 ;;
		--audit) audit=1 ;;
		--uninstall) uninstall=1 ;;
		--check-upgrades) check_upgrades=1 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

devsetup_assert_execution_mode "$audit"

formula="$(devsetup_config advanced.php.homebrewFormula php)"

if [[ $uninstall -eq 1 ]]; then
	devsetup_uninstall_via_homebrew PHP "$formula" "$audit" || true
	exit 0
fi

devsetup_install_via_homebrew PHP "$formula" php \
	"Install PHP from https://www.php.net/downloads.php." "$audit" "$print_path" "$check_upgrades"
