#!/usr/bin/env bash
# Provisions stable Rust without changing an existing default toolchain.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../config.sh
. "$script_dir/../config.sh"
audit=0
uninstall=0
check_upgrades=0
upgrade=0
while [[ $# -gt 0 ]]; do
	case "$1" in
		--audit) audit=1 ;;
		--uninstall) uninstall=1 ;;
		--check-upgrades) check_upgrades=1 ;;
		--upgrade) upgrade=1 ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done
devsetup_assert_execution_mode "$audit"

if [[ $uninstall -eq 1 && $upgrade -eq 1 ]]; then
	printf '%s\n' '--uninstall and --upgrade cannot be combined.' >&2
	exit 2
fi
case "$(uname -s)" in
	Darwin|Linux) ;;
	*) devsetup_status warn Rust "run setup.cmd on Windows"; exit 1 ;;
esac
if [[ $uninstall -eq 1 ]]; then
	devsetup_status skip Rust "shared rustup toolchains and Cargo packages are preserved; remove manually with rustup self uninstall if intended"
	exit 0
fi

component_list="$(devsetup_config_list user.rust.components $'rustfmt\nclippy\nrust-src')"
component_list="$(printf '%s\n' cargo rustc "$component_list" | awk 'NF && !seen[$0]++')"
target_list="$(devsetup_config_list user.rust.targets)"
while IFS= read -r name; do
	[[ -n "$name" ]] || continue
	if [[ ! "$name" =~ ^[a-z][a-z0-9_.-]*$ ]]; then
		printf 'Invalid Rust component name: %s\n' "$name" >&2
		exit 1
	fi
done <<< "$component_list"
while IFS= read -r name; do
	[[ -n "$name" ]] || continue
	if [[ ! "$name" =~ ^[a-z][a-z0-9_.-]*$ ]]; then
		printf 'Invalid Rust target name: %s\n' "$name" >&2
		exit 1
	fi
done <<< "$target_list"
selection="components [${component_list//$'\n'/, }], targets [${target_list//$'\n'/, }]"
formula="$(devsetup_config advanced.rust.homebrewFormula rustup)"
cargo_bin="${CARGO_HOME:-$HOME/.cargo}/bin"
devsetup_status found "Rust homes" "Cargo: ${CARGO_HOME:-$HOME/.cargo}; rustup: ${RUSTUP_HOME:-$HOME/.rustup} (current-user permissions; no elevation requested)"
rustup="$(devsetup_rust_tool_path rustup || true)"
if [[ -z "$rustup" ]]; then
	if [[ $audit -eq 1 ]]; then
		if devsetup_audit_homebrew_install Rust "$formula"; then
			devsetup_status install Rust "would install stable with $selection"
			devsetup_status install "Rust PATH" "would add Rust tools to the login shell profile after installation"
		fi
		devsetup_status skip "Rust build" "linker readiness is unverified; audit does not compile or run code"
		exit 0
	fi
	devsetup_ensure_homebrew
	rustup_bin="$(brew --prefix)/opt/$formula/bin"
	export PATH="$rustup_bin:$cargo_bin:$PATH"
	RUSTUP_AUTO_INSTALL=0 devsetup_install_via_homebrew rustup "$formula" rustup "Install rustup from https://rustup.rs/." 0
	rustup="$(command -v rustup)"
fi

rustup_dir="$(dirname "$rustup")"
invoke_rustup() {
	PATH="$rustup_dir:$cargo_bin:$PATH" RUSTUP_AUTO_INSTALL=0 "$rustup" "$@"
}

invoke_rustup_check() {
	local output exit_code
	if output="$(invoke_rustup check)"; then
		printf '%s\n' "$output"
		return 0
	else
		exit_code=$?
	fi
	if [[ $exit_code -eq 100 ]] && printf '%s\n' "$output" | grep -qi 'update available'; then
		printf '%s\n' "$output"
		return 0
	fi
	if [[ -n "$output" ]]; then printf '%s\n' "$output" >&2; fi
	return "$exit_code"
}

rust_has_entry() {
	local entries="$1" name="$2" component="${3:-0}"
	printf '%s\n' "$entries" | awk -v name="$name" -v host="$default_host" -v component="$component" '
		$1 == name || (component == 1 && $1 == name "-" host) { found = 1 }
		END { exit !found }
	'
}

version="$(invoke_rustup --version)"
devsetup_status found rustup "$version"
if [[ $audit -eq 1 ]]; then devsetup_persist_rust_path "$rustup_dir" 1; fi
host_info="$(invoke_rustup show)"
default_host="$(printf '%s\n' "$host_info" | sed -n 's/^Default host: //p')"
if [[ -z "$default_host" || "$default_host" == *[[:space:]]* ]]; then
	devsetup_status warn Rust "could not resolve rustup's default host"
	exit 1
fi
stable_toolchain="stable-$default_host"
toolchains="$(invoke_rustup toolchain list)"
if ! printf '%s\n' "$toolchains" | awk -v expected="$stable_toolchain" '$1 == expected { found = 1 } END { exit !found }'; then
	if [[ $audit -eq 1 ]]; then
		devsetup_status install "Rust stable" "would install stable with $selection; existing defaults remain unchanged"
		devsetup_status skip "Rust build" "linker readiness is unverified; audit does not compile or run code"
		exit 0
	fi
	devsetup_status install "Rust stable" "installing stable with minimal profile"
	invoke_rustup toolchain install "$stable_toolchain" --profile minimal --no-self-update
fi

upgrades=""
if [[ $check_upgrades -eq 1 || $upgrade -eq 1 ]]; then
	if ! upgrades="$(invoke_rustup_check)"; then
		devsetup_status warn Rust "rustup upgrade check failed"
		exit 1
	fi
	stable_status="$(printf '%s\n' "$upgrades" | awk -v toolchain="$stable_toolchain" '$1 == toolchain && $2 == "-"')"
	if [[ $upgrade -eq 1 ]]; then
		if [[ -z "$stable_status" || "$stable_status" == *$'\n'* ]] || ! printf '%s\n' "$stable_status" | grep -Eqi 'update available|up to date'; then
			printf 'Could not determine the latest stable Rust version from rustup check.\n' >&2
			exit 1
		fi
		if printf '%s\n' "$stable_status" | grep -qi 'update available'; then
			if [[ $audit -eq 1 ]]; then
				devsetup_status install "Rust stable" "would update $stable_toolchain and its installed components/targets; rustup itself, other toolchains and defaults are preserved"
			else
				devsetup_status install "Rust stable" "updating $stable_toolchain and its installed components/targets without rustup self-update"
				invoke_rustup update "$stable_toolchain" --no-self-update
				upgrades="$(invoke_rustup_check)"
				stable_status="$(printf '%s\n' "$upgrades" | awk -v toolchain="$stable_toolchain" '$1 == toolchain && $2 == "-"')"
				if [[ "$stable_status" == *$'\n'* ]] || ! printf '%s\n' "$stable_status" | grep -qi 'up to date'; then
					printf 'Rust update verification failed: rustup check does not report %s up to date.\n' "$stable_toolchain" >&2
					exit 1
				fi
			fi
		fi
	fi
fi

if ! printf '%s\n' "$toolchains" | grep -Eq '\([^)]*default[^)]*\)'; then
	if [[ $audit -eq 1 ]]; then
		devsetup_status install "Rust default" "would select stable because no default toolchain exists"
	else
		devsetup_status install "Rust default" "selecting stable because no default toolchain exists"
		invoke_rustup default "$stable_toolchain"
	fi
fi
available="$(invoke_rustup component list --toolchain "$stable_toolchain")"
while IFS= read -r component; do
	[[ -n "$component" ]] || continue
	if ! rust_has_entry "$available" "$component" 1; then
		printf "Rust component '%s' is unavailable for %s. No requested components or targets were added.\n" "$component" "$stable_toolchain" >&2
		exit 1
	fi
done <<< "$component_list"
if [[ -n "$target_list" ]]; then
	available_targets="$(invoke_rustup target list --toolchain "$stable_toolchain")"
	while IFS= read -r target; do
		if ! rust_has_entry "$available_targets" "$target"; then
			printf "Rust target '%s' is unavailable for %s. No requested components or targets were added.\n" "$target" "$stable_toolchain" >&2
			exit 1
		fi
	done <<< "$target_list"
fi
installed="$(invoke_rustup component list --installed --toolchain "$stable_toolchain")"
while IFS= read -r component; do
	[[ -n "$component" ]] || continue
	if rust_has_entry "$installed" "$component" 1; then
		devsetup_status found "Rust $component" "installed for stable"
	elif [[ $audit -eq 1 ]]; then
		devsetup_status install "Rust $component" "would add component to stable"
	else
		invoke_rustup component add --toolchain "$stable_toolchain" "$component"
		installed="$(invoke_rustup component list --installed --toolchain "$stable_toolchain")"
		if ! rust_has_entry "$installed" "$component" 1; then
			printf "Rust component '%s' was not installed after rustup reported success.\n" "$component" >&2
			exit 1
		fi
		devsetup_status install "Rust $component" "added to stable"
	fi
done <<< "$component_list"
if [[ -n "$target_list" ]]; then
	installed_targets="$(invoke_rustup target list --installed --toolchain "$stable_toolchain")"
	while IFS= read -r target; do
		if rust_has_entry "$installed_targets" "$target"; then
			devsetup_status found "Rust target" "$target installed for stable"
		elif [[ $audit -eq 1 ]]; then
			devsetup_status install "Rust target" "would add $target to stable"
		else
			invoke_rustup target add --toolchain "$stable_toolchain" "$target"
			installed_targets="$(invoke_rustup target list --installed --toolchain "$stable_toolchain")"
			if ! rust_has_entry "$installed_targets" "$target"; then
				printf "Rust target '%s' was not installed after rustup reported success.\n" "$target" >&2
				exit 1
			fi
			devsetup_status install "Rust target" "added $target to stable"
		fi
	done <<< "$target_list"
fi
for tool in rustc cargo; do
	if rust_has_entry "$installed" "$tool" 1; then
		version="$(invoke_rustup run "$stable_toolchain" "$tool" --version)"
		devsetup_status found "Rust $tool" "$version"
	fi
done
if rust_has_entry "$component_list" rustfmt 1 && rust_has_entry "$installed" rustfmt 1; then
	version="$(invoke_rustup run "$stable_toolchain" rustfmt --version)"
	devsetup_status found "Rust rustfmt version" "$version"
fi
if rust_has_entry "$component_list" clippy 1 && rust_has_entry "$installed" clippy 1 &&
	rust_has_entry "$installed" cargo 1; then
	version="$(invoke_rustup run "$stable_toolchain" cargo clippy --version)"
	devsetup_status found "Rust clippy version" "$version"
fi
if rust_has_entry "$component_list" rust-analyzer 1 && rust_has_entry "$installed" rust-analyzer 1; then
	version="$(invoke_rustup run "$stable_toolchain" rust-analyzer --version)"
	devsetup_status found "Rust analyzer version" "$version"
fi
if [[ $check_upgrades -eq 1 || $upgrade -eq 1 ]]; then
	while IFS= read -r line; do
		if printf '%s\n' "$line" | grep -qi 'update available'; then
			devsetup_status update Rust "$line (stable: ./setup.sh --upgrade-rust; other toolchains/rustup update separately)"
		elif printf '%s\n' "$line" | grep -qi 'up to date'; then
			devsetup_status found Rust "$line"
		elif [[ -n "$line" ]]; then
			devsetup_status warn Rust "upgrade check: $line"
		fi
	done <<< "$upgrades"
fi
if [[ $audit -eq 1 ]]; then
	devsetup_status skip "Rust build" "linker readiness is unverified; audit does not compile or run code"
	exit 0
fi

export PATH="$rustup_dir:$cargo_bin:$PATH"
devsetup_persist_rust_path "$rustup_dir"
probe="$(mktemp -d)"
trap 'rm -rf -- "$probe"' EXIT
cat > "$probe/Cargo.toml" <<'EOF'
[package]
name = "devsetup_probe"
version = "0.0.0"
edition = "2021"

[workspace]

[[bin]]
name = "devsetup_probe"
path = "probe.rs"
EOF
printf '%s\n' 'fn main() { println!("rust-ready"); }' > "$probe/probe.rs"
if (cd "$probe" && invoke_rustup run "$stable_toolchain" cargo build --offline --quiet --target "$default_host" \
	--manifest-path "$probe/Cargo.toml" --target-dir "$probe/target") &&
	output="$("$probe/target/$default_host/debug/devsetup_probe")" && [[ "$output" == "rust-ready" ]]; then
	devsetup_status found "Rust build" "Cargo compiled, linked, and ran a native executable with stable"
else
	devsetup_status warn "Rust build" "toolchain installed but Cargo native build/run failed; check Cargo configuration and the platform C linker/SDK (Xcode Command Line Tools on macOS). No sudo or global linker override was attempted."
fi
