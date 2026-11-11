#!/usr/bin/env bash
#
# Ensures Python is available without admin rights or GUI installers.
# Version and uv download URL come from dev-setup.config.json.
#
#   --print-path  print only the interpreter path on stdout (progress to stderr)
#   --audit       report what would happen without changing anything
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
		--check-upgrades) check_upgrades=1 ;; # no-op here: uv pins exact versions, not a rolling latest
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

devsetup_assert_execution_mode "$audit"

python_version="$(devsetup_config user.python.version 3.14)"
uv_install_url="$(devsetup_config advanced.python.uvInstallUrl.unix https://astral.sh/uv/install.sh)"

if [[ $uninstall -eq 1 ]]; then
	# Only uninstall if uv actually reports this version installed - uv merely
	# being on PATH doesn't mean it's the one that put this version in place
	# (python3/python found on PATH already is left alone by the installer).
	uv_managed_path=""
	if command -v uv >/dev/null 2>&1; then
		uv_managed_path="$(uv python find "$python_version" 2>/dev/null || true)"
	fi
	# `uv python find` also resolves system interpreters it didn't install, so only
	# treat this as uv-managed when the resolved path is under uv's own data directory.
	case "$uv_managed_path" in
		*/uv/*) : ;;
		*) uv_managed_path="" ;;
	esac
	if [[ -n "$uv_managed_path" ]]; then
		if [[ $audit -eq 1 ]]; then
			devsetup_status remove Python "would uninstall CPython $python_version via uv"
		else
			uv python uninstall "$python_version"
			devsetup_status remove Python "uninstalled CPython $python_version via uv"
		fi
	else
		devsetup_status warn Python "no uv-managed CPython $python_version found to uninstall (a system Python, if any, is left alone)"
	fi
	exit 0
fi

python_command=""
for candidate in python3 python; do
	if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
		python_command="$(command -v "$candidate")"
		break
	fi
done

if [[ $audit -eq 1 ]]; then
	if [[ -n "$python_command" ]]; then
		devsetup_status found Python "$("$python_command" --version 2>&1) at $python_command"
	elif command -v uv >/dev/null 2>&1; then
		devsetup_status install Python "would install CPython $python_version via uv"
	else
		devsetup_status install Python "would bootstrap uv, then install CPython $python_version"
	fi
	exit 0
fi

if [[ -z "$python_command" ]]; then
	if ! command -v uv >/dev/null 2>&1; then
		devsetup_status install uv "installing to \$HOME/.local/bin (user-local, no admin, no GUI)" >&2
		uv_installer="$HOME/.uv-install.sh"
		curl -L --progress-bar -Sf "$uv_install_url" -o "$uv_installer"
		"${BASH:-bash}" "$uv_installer" >&2
		rm -f "$uv_installer"
		export PATH="$HOME/.local/bin:$PATH"
	fi
	if ! command -v uv >/dev/null 2>&1; then
		echo "Python is unavailable and uv could not be installed automatically. Install uv from https://docs.astral.sh/uv/. No GUI installer was launched." >&2
		exit 1
	fi
	devsetup_status install Python "installing CPython $python_version via uv" >&2
	uv python install "$python_version" >&2
	python_command="$(uv python find "$python_version")"
fi

if [[ $print_path -eq 1 ]]; then
	devsetup_status found Python "$("$python_command" --version 2>&1) at $python_command" >&2
	printf '%s\n' "$python_command"
else
	devsetup_status found Python "$("$python_command" --version 2>&1) at $python_command"
fi
