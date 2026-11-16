#!/usr/bin/env python3
"""Opt-in GnuPG signing-key management; passphrases stay in pinentry."""

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 300


def fail(message):
    raise SystemExit(message)


def run(command, *, data=None, capture=False, check=True, capture_errors=False):
    try:
        result = subprocess.run(
            command, input=data, stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture_errors else None,
            timeout=TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"{command[0]} failed: {exc}")
    if check and result.returncode:
        fail(f"{command[0]} failed with exit code {result.returncode}")
    return result


def config_value(key, default=""):
    path = Path(os.environ.get("DEVSETUP_CONFIG_FILE", ROOT / "config/dev-setup.config.json"))
    if not path.is_file():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        for part in key.split("."):
            value = value[part]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        fail(f"Cannot read configuration {path}: {exc}")
    return value if isinstance(value, str) and value else default


def git_config(key):
    result = run(["git", "config", "--global", "--get", key], capture=True, check=False)
    if result.returncode == 1:
        return ""
    if result.returncode:
        fail(f"Cannot read Git setting {key}")
    return result.stdout.decode("utf-8").strip()


def gpg_executable():
    configured = git_config("gpg.program")
    candidate = shutil.which(configured) if configured else None
    candidate = candidate or shutil.which("gpg") or shutil.which("gpg.exe")
    if not candidate:
        fail("GnuPG not found; run setup or install it before managing signing keys.")
    return candidate


def list_keys(gpg):
    output = run(
        [gpg, "--batch", "--with-colons", "--with-keygrip", "--list-secret-keys"],
        capture=True,
    ).stdout.decode("utf-8", errors="replace")
    keys = []
    current = None
    primary = False
    for line in output.splitlines():
        parts = line.split(":")
        kind = parts[0]
        if kind == "sec":
            current = {"fingerprint": "", "keygrip": "", "keygrips": [], "uids": [], "validity": parts[1]}
            keys.append(current)
            primary = True
        elif kind == "ssb":
            primary = False
        elif current and kind == "fpr" and primary and not current["fingerprint"]:
            current["fingerprint"] = parts[9].upper()
        elif current and kind == "grp":
            grip = parts[9].upper()
            current["keygrips"].append(grip)
            if primary and not current["keygrip"]:
                current["keygrip"] = grip
        elif current and kind == "uid":
            current["uids"].append(parts[9])
    return [key for key in keys if key["fingerprint"]]


def select_keys(keys, selectors):
    if not selectors:
        return keys
    selected = []
    for selector in selectors:
        selector = selector.upper()
        if not re.fullmatch(r"[0-9A-F]{40}|[0-9A-F]{64}", selector):
            fail("Use a full primary-key fingerprint for --key, --default, and --remove.")
        matches = [key for key in keys if key["fingerprint"] == selector]
        if not matches:
            fail(f"No local secret key matches {selector}.")
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def require_keys(keys):
    if not keys:
        fail("No local secret keys found.")


def describe_keys(keys):
    if not keys:
        print("[skip] GPG key: no local secret keys found")
    for key in keys:
        print(f"[found] GPG key: {key['fingerprint']}  {'; '.join(key['uids'])}")


def require_prompt():
    if not sys.stdin.isatty():
        fail("This operation needs an interactive terminal and native GnuPG pinentry.")


def generate(gpg, name, email):
    if not name or not email or any(c in name + email for c in "\r\n<>"):
        fail("Supply a single-line --key-name and --key-email (or configure user.git values).")
    require_prompt()
    expiry = config_value("advanced.gpg.keyExpiry", "2y")
    print("Enter a strong, non-empty passphrase in the native pinentry prompt.", flush=True)
    result = run(
        [gpg, "--no-tty", "--pinentry-mode", "ask", "--status-fd", "1",
         "--quick-generate-key", f"{name} <{email}>", "rsa4096", "sign", expiry],
        capture=True,
    )
    match = re.search(rb"^\[GNUPG:\] KEY_CREATED [BPS] ([0-9A-F]+)$", result.stdout, re.M)
    if not match:
        fail("GnuPG did not report the generated fingerprint; inspect the keyring.")
    fingerprint = match.group(1).decode("ascii")
    key = select_keys(list_keys(gpg), [fingerprint])[0]
    agent = shutil.which("gpg-connect-agent") or shutil.which("gpg-connect-agent.exe")
    if not agent or not key["keygrip"]:
        fail(f"Generated {fingerprint}, but cannot confirm passphrase protection; inspect it before use.")
    info = run([agent, f"KEYINFO {key['keygrip']}", "/bye"], capture=True).stdout.decode()
    if not re.search(r"^S KEYINFO \S+ \S+ \S+ \S+ \S+ P(?:\s|$)", info, re.M):
        fail(f"Generated {fingerprint}, but its private key is not confirmed passphrase-protected.")
    print(f"[found] GPG key: generated protected key {fingerprint}")
    print("Set it as the default explicitly with --default <fingerprint>.")


def backup_path(path):
    target = Path(path).expanduser()
    if target.suffix.lower() != ".gpg":
        target = Path(str(target) + ".gpg")
    parent = target.parent.resolve(strict=True)
    if not parent.is_dir():
        fail("Backup parent must be an existing directory.")
    target = parent / target.name
    if target.exists() or target.is_symlink():
        fail(f"Refusing to overwrite {target}.")
    result = run(["git", "-C", str(parent), "rev-parse", "--show-toplevel"],
                 capture=True, check=False, capture_errors=True)
    if result.returncode == 0:
        fail("Refusing to write a private-key backup inside a Git repository.")
    if result.returncode != 128:
        fail(f"Could not establish whether the backup destination is inside a Git repository: "
             f"{result.stderr.decode('utf-8', errors='replace').strip()}")
    return target


def export_keys(gpg, keys, destination):
    require_keys(keys)
    require_prompt()
    target = backup_path(destination)
    print("Pinentry will request the backup password and, if needed, each key passphrase.", flush=True)
    fd, temporary = tempfile.mkstemp(prefix=".devsetup-gpg-", suffix=".gpg", dir=target.parent)
    os.close(fd)
    producer = None
    try:
        producer = subprocess.Popen(
            [gpg, "--no-tty", "--pinentry-mode", "ask", "--export-secret-keys",
             *[key["fingerprint"] for key in keys]],
            stdout=subprocess.PIPE,
        )
        try:
            result = subprocess.run(
                [gpg, "--no-tty", "--yes", "--pinentry-mode", "ask", "--symmetric",
                 "--cipher-algo", "AES256", "--output", temporary],
                stdin=producer.stdout, timeout=TIMEOUT, check=False,
            )
        finally:
            producer.stdout.close()
        try:
            producer_code = producer.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            producer.kill()
            producer.wait()
            fail("Private-key export timed out; encrypted backup was not saved.")
        if result.returncode or producer_code:
            fail("Private-key export or encryption failed; encrypted backup was not saved.")
        if Path(temporary).stat().st_size == 0:
            fail("GnuPG produced an empty encrypted backup.")
        try:
            os.link(temporary, target)
        except FileExistsError:
            fail(f"Refusing to overwrite {target}.")
        print(f"[found] GPG backup: encrypted {len(keys)} key(s) to {target}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        if producer and producer.poll() is None:
            producer.kill()
            producer.wait()
        fail(f"Backup failed: {exc}")
    finally:
        Path(temporary).unlink(missing_ok=True)


def import_keys(gpg, path):
    require_prompt()
    source = Path(path).expanduser()
    if not source.is_file():
        fail(f"Backup not found: {source}")
    print("Enter the backup password in pinentry. Imported keys are not set as default.", flush=True)
    producer = None
    try:
        producer = subprocess.Popen(
            [gpg, "--no-tty", "--pinentry-mode", "ask", "--decrypt", str(source)],
            stdout=subprocess.PIPE,
        )
        try:
            result = subprocess.run(
                [gpg, "--batch", "--import"], stdin=producer.stdout,
                timeout=TIMEOUT, check=False,
            )
        finally:
            producer.stdout.close()
        producer_code = producer.wait(timeout=TIMEOUT)
        if result.returncode or producer_code:
            fail("Decryption or import failed; inspect the keyring for partially imported keys.")
    except (OSError, subprocess.TimeoutExpired) as exc:
        if producer and producer.poll() is None:
            producer.kill()
            producer.wait()
        fail(f"Import failed; inspect the keyring for partially imported keys: {exc}")
    print("[found] GPG backup: imported; run --list and --verify to inspect keys.")


def test_key(gpg, key):
    message = b"devsetup-kit GPG signing verification\n"
    signed = run(
        [gpg, "--no-tty", "--batch", "--pinentry-mode", "ask",
         "--local-user", key["fingerprint"], "--clearsign"],
        data=message, capture=True,
    ).stdout
    result = run([gpg, "--batch", "--status-fd", "1", "--verify"],
                 data=signed, capture=True)
    valid = re.findall(rb"^\[GNUPG:\] VALIDSIG ([0-9A-F]+).* ([0-9A-F]+)$",
                       result.stdout, re.M)
    if not any(primary.decode() == key["fingerprint"] for _, primary in valid):
        fail(f"Signature verification did not match {key['fingerprint']}.")
    print(f"[found] GPG key: signing and verification passed for {key['fingerprint']}")


def set_default(gpg, key, email):
    fingerprint = key["fingerprint"]
    for setting, value in (
        ("user.signingkey", fingerprint), ("gpg.format", "openpgp"),
        ("gpg.program", gpg), ("commit.gpgsign", "true"), ("tag.gpgsign", "true"),
    ):
        run(["git", "config", "--global", "--replace-all", setting, value])
    if email:
        run(["git", "config", "--global", "--replace-all", "user.email", email])
    print(f"[found] Git signing: default set to {fingerprint}")


def github_keys():
    gh = shutil.which("gh")
    if not gh:
        fail("GitHub CLI is required; install and authenticate it first.")
    identity = json.loads(run([gh, "api", "--hostname", "github.com", "user"],
                              capture=True).stdout)
    login = identity.get("login")
    if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]+", login):
        fail("GitHub did not return a valid authenticated login.")
    pages = json.loads(run(
        [gh, "api", "--hostname", "github.com", "--paginate", "--slurp",
         f"users/{login}/gpg_keys?per_page=100"], capture=True,
    ).stdout)
    return gh, login, [key for page in pages for key in page]


def github_action(gpg, keys, publish, title):
    require_keys(keys)
    gh, login, registered = github_keys()
    fingerprints = github_fingerprints(gpg, registered)
    missing = []
    for key in keys:
        fingerprint = key["fingerprint"]
        if fingerprint in fingerprints:
            print(f"[found] GitHub {login}: public key {fingerprint} is registered")
        elif not publish:
            print(f"[warn] GitHub {login}: public key {fingerprint} is not registered")
            missing.append(fingerprint)
        else:
            public = run([gpg, "--armor", "--export", fingerprint], capture=True).stdout
            if not public.startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----"):
                fail(f"No public key exported for {fingerprint}.")
            run([gh, "gpg-key", "add", "--title", title or f"GPG signing {fingerprint}"],
                data=public)
            print(f"[found] GitHub {login}: uploaded public key {fingerprint}")
    if publish:
        _, _, confirmed = github_keys()
        confirmed_fingerprints = github_fingerprints(gpg, confirmed)
        missing = [key["fingerprint"] for key in keys if key["fingerprint"] not in confirmed_fingerprints]
        if missing:
            fail(f"GitHub did not confirm registration: {', '.join(missing)}")
    print("GitHub verifies commits only when the committer email is verified and matches the key.")
    if missing:
        fail(f"Unregistered GitHub public keys: {', '.join(missing)}")


def github_fingerprints(gpg, registered):
    fingerprints = set()
    for item in registered:
        raw = item.get("raw_key")
        if not isinstance(raw, str) or not raw.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"):
            fail("GitHub did not provide an armored public key; cannot verify registration.")
        output = run([gpg, "--batch", "--with-colons", "--show-keys"],
                     data=raw.encode("utf-8"), capture=True).stdout.decode("utf-8")
        for line in output.splitlines():
            parts = line.split(":")
            if parts[0] == "fpr":
                fingerprints.add(parts[9].upper())
                break
        else:
            fail("Cannot determine a registered GitHub public key fingerprint.")
    return fingerprints


def vscode_signing(audit):
    spec = importlib.util.spec_from_file_location("devsetup_vscode", ROOT / "src/configure-vscode.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config_path = Path(os.environ.get("DEVSETUP_CONFIG_FILE", ROOT / "config/dev-setup.config.json"))
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    targets = module.profile_targets(config)
    if not targets:
        fail("No configured VS Code profiles were found.")
    for name, directory in targets:
        if not directory.is_dir():
            print(f"[skip] VS Code {name}: profile directory does not exist")
            continue
        path = directory / "settings.json"
        settings = module.load_json(path)
        if settings.get("git.enableCommitSigning") is True:
            print(f"[found] VS Code {name}: commit signing already enabled")
            continue
        if audit:
            print(f"[install] VS Code {name}: would enable git.enableCommitSigning")
            continue
        if path.exists():
            backup = directory / "settings.json.devsetup-signing-backup"
            if backup.exists():
                fail(f"Refusing to overwrite existing backup {backup}.")
            shutil.copy2(path, backup)
            print(f"[found] VS Code {name}: original settings backed up to {backup}")
        settings["git.enableCommitSigning"] = True
        module.write_json(path, settings)
        if module.load_json(path).get("git.enableCommitSigning") is not True:
            fail(f"Could not validate VS Code settings for {name}.")
        print(f"[found] VS Code {name}: commit signing enabled")
    module.sync_settings(config, audit)
    print("Settings Sync does not transfer Git configuration, private keys, or passphrases.")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--list", action="store_true")
    actions.add_argument("--generate", action="store_true")
    actions.add_argument("--verify", action="store_true")
    actions.add_argument("--cache", action="store_true")
    actions.add_argument("--github-check", action="store_true")
    actions.add_argument("--github-publish", action="store_true")
    actions.add_argument("--vscode-signing", action="store_true")
    actions.add_argument("--export", metavar="PATH")
    actions.add_argument("--import", dest="import_path", metavar="PATH")
    actions.add_argument("--default", metavar="FINGERPRINT")
    actions.add_argument("--remove", metavar="FINGERPRINT")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--key", action="append", default=[], metavar="FINGERPRINT")
    parser.add_argument("--key-name")
    parser.add_argument("--key-email")
    parser.add_argument("--title")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.audit:
        print("[found] GPG audit: read-only; no keyring or settings changes")
        if args.vscode_signing:
            vscode_signing(True)
        else:
            print(f"[found] Git signing: {git_config('user.signingkey') or 'not configured'}")
            print("[install] GPG: selected operation would run only without --audit")
        return
    if args.vscode_signing:
        vscode_signing(False)
        return
    gpg = gpg_executable()
    if args.generate:
        generate(gpg, args.key_name or config_value("user.git.userName"),
                 args.key_email or config_value("user.git.userEmail"))
        return
    if args.import_path:
        import_keys(gpg, args.import_path)
        return
    keys = select_keys(list_keys(gpg), args.key)
    if args.default:
        set_default(gpg, select_keys(keys, [args.default])[0], args.key_email)
    elif args.remove:
        key = select_keys(keys, [args.remove])[0]
        if git_config("user.signingkey").upper().rstrip("!") in {
            key["fingerprint"], key["fingerprint"][-16:], key["fingerprint"][-8:]
        }:
            fail("This is Git's default signing key; change the default before removing it.")
        require_prompt()
        print(f"Removing {key['fingerprint']} deletes its local private and public key.")
        if input("Type the full fingerprint to confirm: ").strip().upper() != key["fingerprint"]:
            fail("Removal cancelled.")
        run([gpg, "--batch", "--yes", "--delete-secret-and-public-key", key["fingerprint"]])
        print("[found] GPG key: removed locally; GitHub registrations are unchanged")
    elif args.export:
        export_keys(gpg, keys, args.export)
    elif args.verify or args.cache:
        require_keys(keys)
        require_prompt()
        if args.cache:
            if platform.system() == "Darwin":
                print("In pinentry, select 'Save in Keychain' for each key if offered.")
            else:
                print("Use your installed GnuPG pinentry and agent cache; OS credential-vault integration varies.")
            agent = shutil.which("gpg-connect-agent") or shutil.which("gpg-connect-agent.exe")
            if not agent:
                fail("gpg-connect-agent is required to prompt for each selected key.")
            for key in keys:
                if not key["keygrips"]:
                    fail(f"No keygrip reported for {key['fingerprint']}.")
                for grip in key["keygrips"]:
                    result = run([agent, f"CLEAR_PASSPHRASE --mode=normal {grip}", "/bye"], capture=True)
                    if re.search(rb"^ERR(?:\s|$)", result.stdout, re.M):
                        fail(f"Could not clear the GnuPG agent cache for {key['fingerprint']}.")
        for key in keys:
            test_key(gpg, key)
    elif args.github_check or args.github_publish:
        github_action(gpg, keys, args.github_publish, args.title)
    else:
        describe_keys(keys)
        print(f"[found] Git signing: {git_config('user.signingkey') or 'not configured'}")


if __name__ == "__main__":
    main()
