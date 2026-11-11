#!/usr/bin/env bash
# Detects BusyBox on Unix; installation is supported on Windows only.
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

if busybox_path="$(command -v busybox 2>/dev/null)"; then
	if [[ $uninstall -eq 1 ]]; then
		devsetup_status skip BusyBox "existing executable is not managed by this kit: $busybox_path"
	elif [[ $check_upgrades -eq 1 ]]; then
		devsetup_status found BusyBox "available at $busybox_path; automatic upgrade checks are not supported on this platform"
	else
		devsetup_status found BusyBox "available at $busybox_path"
	fi
	exit 0
fi

if [[ $uninstall -eq 1 ]]; then
	devsetup_status skip BusyBox "not installed; this kit manages BusyBox on Windows only"
elif [[ $audit -eq 1 ]]; then
	devsetup_status skip BusyBox "not installed; automatic installation is supported on Windows only"
else
	devsetup_status skip BusyBox "automatic installation is supported on Windows only"
fi
