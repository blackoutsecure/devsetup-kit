#!/usr/bin/env bash
#
# Optional helper to generate, export, or import a GPG signing identity for Git.
#
# Separate from setup.sh because it changes real state: a new secret key in your
# GPG keyring and your global git signing config (user.signingkey, commit.gpgsign,
# tag.gpgsign). Nothing here runs as part of the main setup flow.
#
# --export bundles the public/secret key into a tarball encrypted with GPG's
# symmetric cipher (AES-256), so the archive this produces is password protected
# without adding a dependency on a third-party archiver. --import reverses that.
#
# Requires gpg on PATH; run ./setup.sh first if it's missing.
#
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=src/config.sh
. "$script_dir/src/config.sh"

audit=0
generate=0
export_path=""
import_path=""
key_passphrase=""
zip_password=""
key_name=""
key_email=""
while [[ $# -gt 0 ]]; do
	case "$1" in
		--audit) audit=1 ;;
		--generate) generate=1 ;;
		--export) export_path="$2"; shift ;;
		--import) import_path="$2"; shift ;;
		--key-passphrase) key_passphrase="$2"; shift ;;
		--zip-password) zip_password="$2"; shift ;;
		--key-name) key_name="$2"; shift ;;
		--key-email) key_email="$2"; shift ;;
		*) echo "Unknown option: $1" >&2; exit 2 ;;
	esac
	shift
done

devsetup_assert_execution_mode "$audit"

random_secret() {
	# 24 url-safe base64 characters.
	head -c 24 /dev/urandom | base64 | tr -d '+/=\n' | head -c 24
}

signing_key_id() {
	git config --global --get user.signingkey 2>/dev/null || true
}

configure_git_signing_key() {
	local key_id="$1"
	git config --global user.signingkey "$key_id"
	git config --global commit.gpgsign true
	git config --global tag.gpgsign true
	git config --global gpg.program "$(command -v gpg)"
	devsetup_status install "GPG key" "git configured to sign commits/tags with $key_id"
}

if [[ $audit -eq 1 ]]; then
	if ! command -v gpg >/dev/null 2>&1; then
		devsetup_status warn "GPG key" "gpg not found; run ./setup.sh first"
		exit 0
	fi
	current_key="$(signing_key_id)"
	if [[ -n "$current_key" ]]; then
		devsetup_status found "GPG key" "git signs commits/tags with $current_key"
	else
		devsetup_status install "GPG key" "no signing key configured; run --generate or --import"
	fi
	[[ $generate -eq 1 ]] && devsetup_status install "GPG key" "would generate a new key and configure git to sign with it"
	[[ -n "$export_path" ]] && devsetup_status install "GPG key" "would export the current signing key to $export_path"
	[[ -n "$import_path" ]] && devsetup_status install "GPG key" "would import a key from $import_path and configure git to sign with it"
	exit 0
fi

if [[ $generate -eq 0 && -z "$export_path" && -z "$import_path" ]]; then
	echo "Nothing to do. Pass --generate, --export <path>, and/or --import <path>." >&2
	exit 2
fi

if ! command -v gpg >/dev/null 2>&1; then
	echo "gpg was not found on PATH. Run ./setup.sh first (it installs GPG), or install GnuPG from https://gnupg.org/download/." >&2
	exit 1
fi

key_id=""

if [[ $generate -eq 1 ]]; then
	[[ -z "$key_name" ]] && key_name="$(devsetup_config user.git.userName "")"
	[[ -z "$key_email" ]] && key_email="$(devsetup_config user.git.userEmail "")"
	if [[ -z "$key_name" || -z "$key_email" ]]; then
		echo "Set user.git.userName and user.git.userEmail in config/dev-setup.config.json (or pass --key-name/--key-email) before generating a key." >&2
		exit 1
	fi

	generated_passphrase=0
	if [[ -z "$key_passphrase" ]]; then
		key_passphrase="$(random_secret)"
		generated_passphrase=1
	fi

	expiry="$(devsetup_config advanced.gpg.keyExpiry 2y)"
	batch_file="$(mktemp)"
	cat > "$batch_file" <<EOF
%echo Generating GPG key for git signing
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: $key_name
Name-Email: $key_email
Expire-Date: $expiry
Passphrase: $key_passphrase
%commit
%echo done
EOF

	devsetup_status install "GPG key" "generating a new RSA 4096 key for $key_name <$key_email> (expires in $expiry)"
	gpg --batch --pinentry-mode loopback --gen-key "$batch_file" >/dev/null 2>&1
	rm -f "$batch_file"

	key_id="$(gpg --list-secret-keys --with-colons "$key_email" | awk -F: '/^fpr:/ { print $10; exit }')"
	if [[ -z "$key_id" ]]; then
		echo "Key generation reported success but the new key could not be found for $key_email." >&2
		exit 1
	fi
	devsetup_status found "GPG key" "generated $key_id"

	if [[ $generated_passphrase -eq 1 ]]; then
		echo
		echo "Generated key passphrase (shown once - save it now): $key_passphrase"
		echo
	fi

	configure_git_signing_key "$key_id"
fi

if [[ -n "$export_path" ]]; then
	[[ -z "$key_id" ]] && key_id="$(signing_key_id)"
	if [[ -z "$key_id" ]]; then
		echo "No signing key configured. Pass --generate first, or set one up with 'git config --global user.signingkey <id>'." >&2
		exit 1
	fi

	generated_zip_password=0
	if [[ -z "$zip_password" ]]; then
		zip_password="$(random_secret)"
		generated_zip_password=1
	fi

	bundle_dir="$(mktemp -d)"
	trap 'rm -rf "$bundle_dir"' EXIT

	gpg --batch --yes --export --armor "$key_id" > "$bundle_dir/public.asc"
	gpg --batch --yes --export-secret-keys --armor "$key_id" > "$bundle_dir/secret.asc"
	cat > "$bundle_dir/README.txt" <<EOF
GPG signing identity backup
Key ID: $key_id
Exported: $(date -u +%Y-%m-%dT%H:%M:%SZ)

To restore: ./manage-gpg-key.sh --import <this file> --zip-password <the password you were given for this export>
EOF
	if [[ -n "$key_passphrase" ]]; then
		# Only ever written inside the archive we are about to encrypt, never left on disk in the clear.
		echo "Private key passphrase: $key_passphrase" > "$bundle_dir/KEY-PASSPHRASE.txt"
	fi

	plain_tar="$(mktemp)"
	bundle_files=(public.asc secret.asc README.txt)
	[[ -f "$bundle_dir/KEY-PASSPHRASE.txt" ]] && bundle_files+=(KEY-PASSPHRASE.txt)
	tar -C "$bundle_dir" -czf "$plain_tar" "${bundle_files[@]}"

	output_path="$export_path"
	[[ "$output_path" != *.gpg ]] && output_path="$output_path.gpg"
	gpg --batch --yes --passphrase "$zip_password" --pinentry-mode loopback --symmetric --cipher-algo AES256 -o "$output_path" "$plain_tar"
	rm -f "$plain_tar"

	devsetup_status install "GPG key" "exported $key_id to $output_path (password protected)"
	if [[ $generated_zip_password -eq 1 ]]; then
		echo
		echo "Generated archive password (shown once - save it now): $zip_password"
		echo
	fi
fi

if [[ -n "$import_path" ]]; then
	if [[ ! -f "$import_path" ]]; then
		echo "Import file not found: $import_path" >&2
		exit 1
	fi

	work_dir="$(mktemp -d)"
	trap 'rm -rf "$work_dir"' EXIT
	plain_tar="$work_dir/bundle.tar.gz"

	if [[ "$import_path" == *.gpg ]]; then
		if [[ -z "$zip_password" ]]; then
			echo "This archive is encrypted. Pass --zip-password <the password you were given when it was exported>." >&2
			exit 1
		fi
		gpg --batch --yes --passphrase "$zip_password" --pinentry-mode loopback --decrypt -o "$plain_tar" "$import_path"
	else
		cp "$import_path" "$plain_tar"
	fi

	extract_dir="$work_dir/extracted"
	mkdir -p "$extract_dir"
	tar -C "$extract_dir" -xzf "$plain_tar"

	if [[ ! -f "$extract_dir/secret.asc" ]]; then
		echo "No secret.asc found in the archive; this doesn't look like a bundle from --export." >&2
		exit 1
	fi

	gpg --batch --yes --import "$extract_dir/secret.asc" >/dev/null 2>&1

	imported_key_id=""
	if [[ -f "$extract_dir/README.txt" ]]; then
		imported_key_id="$(sed -n 's/^Key ID: //p' "$extract_dir/README.txt" | head -n 1)"
	fi
	if [[ -z "$imported_key_id" ]]; then
		echo "Key imported, but its ID could not be determined automatically. Run 'gpg --list-secret-keys' and set it with 'git config --global user.signingkey <id>'." >&2
		exit 1
	fi

	devsetup_status found "GPG key" "imported $imported_key_id"
	configure_git_signing_key "$imported_key_id"

	if [[ -f "$extract_dir/KEY-PASSPHRASE.txt" ]]; then
		echo
		echo "This bundle included a saved private key passphrase: $(cat "$extract_dir/KEY-PASSPHRASE.txt")"
		echo
	fi
fi
