#!/usr/bin/env bash
# Installs the Dioxus CLI (dx) through Cargo without changing project toolchains.
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

package="$(devsetup_config advanced.dioxus.cargoPackage dioxus-cli)"
if [[ ! "$package" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]]; then
	printf 'Invalid Dioxus Cargo package name: %s\n' "$package" >&2
	exit 1
fi
cargo_home="${CARGO_HOME:-$HOME/.cargo}"
cargo_bin="$cargo_home/bin"
if [[ $uninstall -eq 1 ]]; then
	devsetup_status skip "Dioxus CLI" "Cargo packages are preserved; remove manually with cargo uninstall $package --root \"$cargo_home\" if intended"
	exit 0
fi

check_dioxus_upgrade() {
	local api metadata latest
	api="$(devsetup_config advanced.dioxus.cratesApiBaseUrl https://crates.io/api/v1/crates)"
	metadata="$(curl --fail --silent --show-error --location --max-time 30 --user-agent devsetup-kit "$api/$package")"
	if [[ "$DEVSETUP_READER" == jq ]]; then
		latest="$(printf '%s' "$metadata" | jq -er '.crate.max_stable_version | select(type == "string")')"
	elif [[ -n "$DEVSETUP_READER" ]]; then
		latest="$(printf '%s' "$metadata" | "$DEVSETUP_READER" -c 'import json, sys; print(json.load(sys.stdin)["crate"]["max_stable_version"])')"
	else
		printf 'Dioxus upgrade checks require Python or jq to read registry metadata.\n' >&2
		return 1
	fi
	if [[ ! "$latest" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
		printf 'Invalid latest stable Dioxus version: %s\n' "$latest" >&2
		return 1
	fi
	if awk -v latest="$latest" -v installed="$installed" 'BEGIN {
		split(latest, a, "."); split(installed, b, ".");
		for (i = 1; i <= 3; i++) {
			if (a[i] + 0 > b[i] + 0) exit 0;
			if (a[i] + 0 < b[i] + 0) exit 1;
		}
		exit !index(installed, "-");
	}'; then
		devsetup_status update "Dioxus CLI" "installed $installed, latest stable $latest (run: cargo install $package --locked --root \"$cargo_home\")"
	else
		devsetup_status found "Dioxus CLI" "installed $installed; latest stable $latest (no automatic upgrade)"
	fi
}

cargo="$(devsetup_rust_tool_path cargo || true)"
dx="$(devsetup_rust_tool_path dx || true)"
if [[ -z "$dx" ]]; then
	if [[ $audit -eq 1 ]]; then
		if [[ -z "$cargo" ]] && devsetup_skip_if_homebrew_write_blocked "Dioxus CLI"; then
			devsetup_status skip "Dioxus PATH" "Cargo is unavailable because shared Homebrew writes are blocked"
			exit 0
		fi
		if [[ -n "$cargo" ]] || devsetup_enabled user.install.rust; then
			devsetup_status install "Dioxus CLI" "would install $package with cargo install --locked --bin dx --root \"$cargo_home\" after stable Rust/Cargo are available"
			devsetup_status install "Dioxus PATH" "would expose $cargo_bin in new terminals after installation"
		else
			devsetup_status warn "Dioxus CLI" "missing and Cargo is unavailable; enable user.install.rust or install stable Rust/Cargo first"
		fi
		exit 0
	fi
	if [[ -z "$cargo" ]]; then
		if devsetup_skip_if_homebrew_write_blocked "Dioxus CLI"; then
			devsetup_status skip "Dioxus PATH" "Cargo is unavailable because shared Homebrew writes are blocked"
			exit 0
		fi
		printf 'Dioxus CLI requires stable Rust and Cargo. Run the Rust setup step first.\n' >&2
		exit 1
	fi
	devsetup_status install "Dioxus CLI" "installing $package through Cargo (user root: $cargo_home; source compilation may take several minutes)"
	PATH="$(dirname "$cargo"):$cargo_bin:$PATH" RUSTUP_TOOLCHAIN=stable RUSTUP_AUTO_INSTALL=0 \
		"$cargo" install --locked --bin dx --root "$cargo_home" "$package"
	dx="$cargo_bin/dx"
	if [[ ! -x "$dx" ]]; then
		printf 'Dioxus installation reported success but dx was not found at %s.\n' "$dx" >&2
		exit 1
	fi
fi

version="$("$dx" --version)"
if [[ "$version" =~ [0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)? ]]; then
	installed="${BASH_REMATCH[0]}"
else
	printf 'Could not determine Dioxus CLI version from: %s\n' "$version" >&2
	exit 1
fi
devsetup_status found "Dioxus CLI" "$version at $dx"
if [[ "$dx" == "$cargo_bin/dx" ]]; then
	tool_dir="$cargo_bin"
	if [[ -n "$cargo" ]]; then tool_dir="$(dirname "$cargo")"; fi
	devsetup_persist_rust_path "$tool_dir" "$audit"
fi
if [[ $check_upgrades -eq 1 ]]; then check_dioxus_upgrade; fi
