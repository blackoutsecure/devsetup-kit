#!/usr/bin/env bash
# Ensures the Microsoft Graph PowerShell authentication module is available per user.
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

module_name="$(devsetup_config advanced.microsoftGraphPowershell.moduleName Microsoft.Graph.Authentication)"
repository="$(devsetup_config advanced.microsoftGraphPowershell.repository PSGallery)"
minimum_version="$(devsetup_config advanced.microsoftGraphPowershell.minimumModuleVersion 2.0.0)"
marker_dir="${HOME}/.devsetup-kit"
marker="$marker_dir/microsoft-graph-powershell.marker"

pwsh_command="$(command -v pwsh || true)"
if [[ -z "$pwsh_command" ]]; then
	devsetup_status skip "Microsoft Graph PowerShell" "PowerShell 7 is unavailable"
	exit 0
fi

installed="$(
	# shellcheck disable=SC2016
	"$pwsh_command" -NoProfile -NoLogo -NonInteractive -Command \
		'$ErrorActionPreference = "Stop"; $module = Get-Module -ListAvailable -Name '"$module_name"' -ErrorAction SilentlyContinue | Sort-Object Version -Descending | Select-Object -First 1; if ($null -ne $module) { $module.Version.ToString() }' \
		2>/dev/null || true
)"

version_at_least() {
	local current="$1" minimum="$2"
	"$pwsh_command" -NoProfile -NoLogo -NonInteractive -Command \
		"exit (if ([version]'$current' -ge [version]'$minimum') { 0 } else { 1 })" >/dev/null 2>&1
}

if [[ $uninstall -eq 1 ]]; then
	if [[ $audit -eq 1 ]]; then
		if [[ -f "$marker" ]]; then
			devsetup_status remove "Microsoft Graph PowerShell" "would uninstall CurrentUser module '$module_name'"
		else
			devsetup_status skip "Microsoft Graph PowerShell" "module was not installed by devsetup-kit; existing module is preserved"
		fi
		exit 0
	fi
	if [[ -f "$marker" ]]; then
		# shellcheck disable=SC2016
		"$pwsh_command" -NoProfile -NoLogo -NonInteractive -Command \
			'$ErrorActionPreference = "Stop"; Uninstall-Module -Name '"$module_name"' -AllVersions -Scope CurrentUser -Force -ErrorAction Stop'
		rm -f "$marker"
		rmdir "$marker_dir" 2>/dev/null || true
		devsetup_status remove "Microsoft Graph PowerShell" "uninstalled module '$module_name' from the CurrentUser scope"
	else
		devsetup_status skip "Microsoft Graph PowerShell" "module was not installed by devsetup-kit; existing module is preserved"
	fi
	exit 0
fi

if [[ -n "$installed" ]] && version_at_least "$installed" "$minimum_version"; then
	devsetup_status found "Microsoft Graph PowerShell" "module $module_name $installed is available"
else
	if [[ $audit -eq 1 ]]; then
		devsetup_status install "Microsoft Graph PowerShell" "would install $module_name >= $minimum_version from $repository at CurrentUser scope"
	else
		devsetup_status install "Microsoft Graph PowerShell" "installing $module_name >= $minimum_version from $repository at CurrentUser scope"
		mkdir -p "$marker_dir"
		# shellcheck disable=SC2016
		"$pwsh_command" -NoProfile -NoLogo -NonInteractive -Command \
			'$ErrorActionPreference = "Stop"; Install-Module -Name '"$module_name"' -Repository '"$repository"' -MinimumVersion '"$minimum_version"' -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop'
		printf 'module=%s\nminimum=%s\n' "$module_name" "$minimum_version" > "$marker"
	fi
fi

if [[ $check_upgrades -eq 1 ]]; then
	latest="$(
		# shellcheck disable=SC2016
		"$pwsh_command" -NoProfile -NoLogo -NonInteractive -Command \
			'$ErrorActionPreference = "Stop"; (Find-Module -Name '"$module_name"' -Repository '"$repository"' -ErrorAction Stop).Version.ToString()' \
			2>/dev/null || true
	)"
	if [[ -n "$latest" && -n "$installed" ]] && version_at_least "$latest" "$installed"; then
		if [[ "$latest" != "$installed" ]] && version_at_least "$latest" "$minimum_version"; then
			devsetup_status update "Microsoft Graph PowerShell" "installed $installed; latest $latest (run: Update-Module $module_name -Scope CurrentUser)"
		fi
	fi
fi
