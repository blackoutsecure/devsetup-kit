#!/usr/bin/env bash
# Ensures the Prettier CLI is available as a user-level npm global.
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

package_name="$(devsetup_config advanced.prettier.npmPackage prettier)"
package_spec="$(devsetup_config advanced.prettier.npmPackageSpec prettier@latest)"
global_prefix="$(devsetup_config advanced.prettier.unixGlobalPrefix "$HOME/.npm-global")"
global_prefix="${global_prefix/#\$HOME/$HOME}"
bin_dir="$global_prefix/bin"

persist_prettier_path() {
	local profile path_line
	profile="$HOME/.profile"
	if [[ "$(uname -s)" == Darwin ]]; then profile="$HOME/.zprofile"; fi
	printf -v path_line "export PATH=%q:\"\$PATH\"" "$bin_dir"
	if [[ -f "$profile" ]] && grep -Fqx "$path_line" "$profile"; then
		devsetup_status found "Prettier PATH" "already configured in $profile"
	elif [[ $audit -eq 1 ]]; then
		devsetup_status install "Prettier PATH" "would add $bin_dir to $profile (new login shells)"
	else
		if [[ -f "$profile" ]]; then cp "$profile" "$profile.devsetup-backup-$(date -u +%Y%m%d%H%M%S)"; fi
		printf '\n# Added by devsetup-kit for Prettier.\n%s\n' "$path_line" >> "$profile"
		devsetup_status install "Prettier PATH" "added $bin_dir to $profile (new login shells)"
	fi
}

prettier_command=""
if command -v prettier >/dev/null 2>&1 && prettier --version >/dev/null 2>&1; then
	prettier_command="$(command -v prettier)"
elif [[ -x "$bin_dir/prettier" ]]; then
	prettier_command="$bin_dir/prettier"
fi
node_available=0
if command -v node >/dev/null 2>&1 && node --version >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && npm --version >/dev/null 2>&1; then
	node_available=1
fi

check_prettier_upgrade() {
	local installed latest
	[[ -n "$prettier_command" ]] || return 0
	command -v npm >/dev/null 2>&1 || return 0
	installed="$($prettier_command --version 2>/dev/null | head -n 1 || true)"
	latest="$(npm view "$package_name" version 2>/dev/null | head -n 1 || true)"
	if [[ -n "$installed" && -n "$latest" && "$installed" != "$latest" ]]; then
		devsetup_status update Prettier "newer version available: installed $installed, latest $latest (run: npm update --global $package_name)"
	fi
}

if [[ $uninstall -eq 1 ]]; then
	if ! command -v npm >/dev/null 2>&1; then
		devsetup_status warn Prettier "npm is unavailable; cannot uninstall"
		exit 0
	fi
	if [[ $audit -eq 1 ]]; then
		devsetup_status remove Prettier "would uninstall $package_name via npm"
		exit 0
	fi
	mkdir -p "$global_prefix"
	npm uninstall --global --prefix "$global_prefix" "$package_name" >/dev/null
	devsetup_status remove Prettier "uninstalled $package_name via npm"
	exit 0
fi

if [[ $audit -eq 1 ]]; then
	if [[ -n "$prettier_command" ]]; then
		devsetup_status found Prettier "$($prettier_command --version) at $prettier_command"
		if [[ "$prettier_command" == "$bin_dir/prettier" ]]; then persist_prettier_path; fi
		[[ $check_upgrades -eq 1 ]] && check_prettier_upgrade
	elif [[ $node_available -eq 1 ]]; then
		devsetup_status install Prettier "would install $package_spec via npm using prefix $global_prefix"
		persist_prettier_path
	elif devsetup_enabled user.install.node; then
		devsetup_status install Prettier "would install $package_spec after Node.js/npm are available"
		persist_prettier_path
	else
		devsetup_status warn Prettier "missing and Node.js/npm are unavailable; enable user.install.node or install Node.js first"
	fi
	exit 0
fi

if [[ $node_available -ne 1 ]]; then
	printf 'Prettier requires Node.js and npm, but one or both were not found. Run the Node.js step first, then run setup again.\n' >&2
	exit 1
fi

mkdir -p "$global_prefix"

case ":$PATH:" in
	*":$bin_dir:"*) ;;
	*) export PATH="$bin_dir:$PATH" ;;
esac

if [[ -z "$prettier_command" ]]; then
	devsetup_status install Prettier "installing $package_spec via npm (user global)"
	npm install --global --prefix "$global_prefix" "$package_spec"
	prettier_command="$(command -v prettier || true)"
	if [[ -z "$prettier_command" && -x "$bin_dir/prettier" ]]; then
		prettier_command="$bin_dir/prettier"
	fi
fi

if [[ "$prettier_command" == "$bin_dir/prettier" ]]; then
	persist_prettier_path
	case ":$PATH:" in
		*":$bin_dir:"*) ;;
		*) export PATH="$bin_dir:$PATH" ;;
	esac
fi

if [[ -z "$prettier_command" ]] || ! "$prettier_command" --version >/dev/null 2>&1; then
	printf 'Prettier setup completed but prettier was not found. Open a new terminal and run setup again.\n' >&2
	exit 1
fi

devsetup_status found Prettier "$($prettier_command --version) at $prettier_command"

if [[ $check_upgrades -eq 1 ]]; then
	check_prettier_upgrade
fi