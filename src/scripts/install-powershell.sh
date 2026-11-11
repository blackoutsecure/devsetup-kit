#!/usr/bin/env bash
#
# Ensures PowerShell is available for VS Code's PowerShell extension.
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
upgrade=0
while [[ $# -gt 0 ]]; do
	case "$1" in
		--print-path) print_path=1 ;;
		--audit) audit=1 ;;
		--uninstall) uninstall=1 ;;
		--check-upgrades) check_upgrades=1 ;;
		--upgrade) upgrade=1 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

devsetup_assert_execution_mode "$audit"

formula="$(devsetup_config advanced.powershell.homebrewFormula powershell)"

if [[ $uninstall -eq 1 && $upgrade -eq 1 ]]; then
	printf '%s\n' '--uninstall and --upgrade cannot be combined.' >&2
	exit 2
fi

if [[ $uninstall -eq 1 ]]; then
	devsetup_uninstall_via_homebrew PowerShell "$formula" "$audit" || true
	exit 0
fi

powershell_version() {
	local output
	if ! output="$("$1" --version)"; then
		printf 'Cannot detect the PowerShell version at %s.\n' "$1" >&2
		return 1
	fi
	if [[ ! "$output" =~ ^PowerShell[[:space:]]([0-9]+\.[0-9]+\.[0-9]+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
		printf 'Cannot parse the PowerShell version at %s: %s\n' "$1" "$output" >&2
		return 1
	fi
	printf '%s\n' "${output#PowerShell }"
}

powershell_newer() {
	local installed="$1" latest="$2" index
	local installed_parts latest_parts
	IFS=. read -r -a installed_parts <<< "${installed%%[-+]*}"
	IFS=. read -r -a latest_parts <<< "$latest"
	for index in 0 1 2; do
		if (( 10#${latest_parts[$index]} > 10#${installed_parts[$index]} )); then return 0; fi
		if (( 10#${latest_parts[$index]} < 10#${installed_parts[$index]} )); then return 1; fi
	done
	[[ "${installed%%+*}" == *-* ]]
}

powershell_latest() {
	local api reader
	api="$(devsetup_config advanced.powershell.portableReleaseApiUrl https://api.github.com/repos/PowerShell/PowerShell/releases/latest)"
	reader="$(devsetup_config_reader)" || {
		printf 'A JSON reader is required to detect the latest PowerShell release.\n' >&2
		return 1
	}
	if [[ "$reader" == "jq" ]]; then
		curl -fsSL --connect-timeout 10 --max-time 30 "$api" |
			jq -er 'select(.draft != true and .prerelease != true) | .tag_name'
	else
		curl -fsSL --connect-timeout 10 --max-time 30 "$api" | "$reader" -c '
import json, sys
release = json.load(sys.stdin)
if release.get("draft") or release.get("prerelease"):
    raise SystemExit("The release endpoint did not return a stable PowerShell version.")
print(release["tag_name"])
'
	fi
}

command_path="$(command -v pwsh || true)"
installed=""
if [[ -n "$command_path" ]]; then
	installed="$(powershell_version "$command_path")"
	devsetup_status found PowerShell "installed $installed at $command_path" >&2
elif [[ $audit -eq 1 ]]; then
	devsetup_status install PowerShell "would install '$formula' via user-local Homebrew" >&2
else
	command_path="$(devsetup_install_via_homebrew PowerShell "$formula" pwsh \
		"Install it from https://learn.microsoft.com/powershell/." 0 1 0)"
	installed="$(powershell_version "$command_path")"
fi

latest=""
if [[ $check_upgrades -eq 1 || $upgrade -eq 1 ]]; then
	if tag="$(powershell_latest)" && [[ "${tag#v}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
		latest="${tag#v}"
	else
		devsetup_status warn PowerShell "latest stable version could not be detected" >&2
		if [[ $upgrade -eq 1 ]]; then exit 1; fi
	fi
fi

if [[ -n "$latest" ]]; then
	if [[ -z "$installed" ]]; then
		devsetup_status found "PowerShell release" "latest stable $latest; PowerShell 7 is not installed" >&2
	elif powershell_newer "$installed" "$latest"; then
		if [[ $upgrade -eq 0 || $audit -eq 1 ]]; then
			devsetup_status update PowerShell "installed $installed; latest stable $latest (run: ./setup.sh --upgrade-powershell)" >&2
		fi
		if [[ $upgrade -eq 1 ]]; then
			if ! devsetup_activate_homebrew; then
				devsetup_status warn PowerShell "upgrade requires an existing user-local Homebrew formula; existing installations are preserved" >&2
				exit 1
			fi
			devsetup_assert_homebrew_write
			if ! brew list --formula --versions "$formula" >/dev/null 2>&1; then
				devsetup_status warn PowerShell "'$formula' is not a Homebrew-managed formula; cask and unmanaged installations are preserved" >&2
				exit 1
			fi
			if [[ $audit -eq 1 ]]; then
				devsetup_status install PowerShell "would upgrade '$formula' to stable $latest via user-local Homebrew; existing sessions are preserved" >&2
			else
				devsetup_status install PowerShell "upgrading '$formula' to stable $latest via user-local Homebrew" >&2
				NONINTERACTIVE=1 brew upgrade --formula "$formula" < /dev/null >&2
				command_path="$(brew --prefix "$formula")/bin/pwsh"
				installed="$(powershell_version "$command_path")"
				if powershell_newer "$installed" "$latest"; then
					printf 'PowerShell upgrade verification failed: expected stable %s or newer, found %s.\n' "$latest" "$installed" >&2
					exit 1
				fi
				devsetup_status found PowerShell "upgraded to $installed at $command_path; existing sessions were preserved" >&2
			fi
		fi
	else
		devsetup_status found PowerShell "latest stable $latest; no upgrade needed (installed $installed); no downgrade performed" >&2
	fi
fi

if [[ $print_path -eq 1 && -n "$command_path" ]]; then
	printf '%s\n' "$command_path"
fi
