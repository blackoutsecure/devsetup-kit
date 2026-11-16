import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manage_gpg_key", ROOT / "src/manage-gpg-key.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
GPG = shutil.which("gpg")
GPGCONF = shutil.which("gpgconf")


class SigningKeyUnitTests(unittest.TestCase):
    def test_selects_all_or_exact_fingerprints(self):
        keys = [{"fingerprint": "A" * 40}, {"fingerprint": "B" * 40}]
        self.assertEqual(manager.select_keys(keys, []), keys)
        self.assertEqual(manager.select_keys(keys, ["b" * 40, "b" * 40]), keys[1:])
        with self.assertRaises(SystemExit):
            manager.select_keys(keys, ["A" * 16])
        with self.assertRaises(SystemExit):
            manager.select_keys(keys, ["C" * 40])

    def test_github_checks_full_fingerprints_not_key_id_suffixes(self):
        key = {"fingerprint": "A" * 24 + "B" * 16}
        registered = [{"key_id": "B" * 16, "raw_key": "-----BEGIN PGP PUBLIC KEY BLOCK-----\nfixture"}]
        result = subprocess.CompletedProcess([], 0, stdout=(
            "pub:::::::::\nfpr:::::::::" + "C" * 24 + "B" * 16 + ":\n"
        ).encode())
        with mock.patch.object(manager, "github_keys", return_value=("gh", "fixture", registered)), \
                mock.patch.object(manager, "run", return_value=result):
            with self.assertRaisesRegex(SystemExit, "Unregistered"):
                manager.github_action("gpg", [key], False, None)

    def test_vscode_changes_only_signing_setting_and_backs_up_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "profile"
            profile.mkdir()
            settings = profile / "settings.json"
            original = '{\n  // preserve a backup of this comment\n  "editor.tabSize": 4\n}\n'
            settings.write_text(original)
            config = {
                "user": {"vscode": {"profiles": ["test"], "settingsSync": {"syncAfterSetup": False}}},
                "advanced": {"vscode": {"profileDirectories": {
                    "macos": {"test": str(profile)}, "linux": {"test": str(profile)},
                    "windows": {"test": str(profile)},
                }}},
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
            with mock.patch.dict(os.environ, {"DEVSETUP_CONFIG_FILE": str(config_path)}):
                manager.vscode_signing(True)
                self.assertEqual(settings.read_text(), original)
                manager.vscode_signing(False)
                manager.vscode_signing(False)
            updated = json.loads(settings.read_text())
            self.assertEqual(updated, {"editor.tabSize": 4, "git.enableCommitSigning": True})
            self.assertEqual((profile / "settings.json.devsetup-signing-backup").read_text(), original)


@unittest.skipUnless(GPG and GPGCONF and os.name != "nt", "GnuPG and Unix pinentry fixture required")
class DisposableGPGTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "gnupg"
        self.home.mkdir(mode=0o700)
        self.pinentry = self.root / "pinentry"
        self.pinentry.write_text(
            "#!/bin/sh\n"
            "printf 'OK fixture\\n'\n"
            "while IFS= read -r line; do\n"
            "  case \"$line\" in\n"
            "    GETPIN) printf 'D fixture-only\\nOK\\n' ;;\n"
            "    BYE) printf 'OK\\n'; exit 0 ;;\n"
            "    *) printf 'OK\\n' ;;\n"
            "  esac\n"
            "done\n"
        )
        self.pinentry.chmod(0o700)
        (self.home / "gpg-agent.conf").write_text(f"pinentry-program {self.pinentry}\n")
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(self.root), "GNUPGHOME": str(self.home),
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stop_agents)

    def stop_agents(self):
        for home in (self.home, self.root / "restore"):
            if home.exists():
                subprocess.run([GPGCONF, "--homedir", str(home), "--kill", "gpg-agent"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)

    def make_key(self, name):
        subprocess.run(
            [GPG, "--batch", "--pinentry-mode", "loopback", "--passphrase", "fixture-only",
             "--quick-generate-key", f"{name} <{name.lower()}@example.test>", "ed25519", "sign", "0"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )

    def test_encrypted_backup_restore_signing_and_repository_guard(self):
        self.make_key("Alpha")
        self.make_key("Beta")
        keys = manager.list_keys(GPG)
        self.assertEqual(len(keys), 2)
        for key in keys:
            manager.test_key(GPG, key)
        manager.set_default(GPG, keys[0], None)
        self.assertEqual(manager.git_config("user.signingkey"), keys[0]["fingerprint"])
        with mock.patch.object(manager, "require_prompt"):
            manager.export_keys(GPG, keys, self.root / "backup")
        archive = self.root / "backup.gpg"
        self.assertTrue(archive.is_file())
        self.assertNotIn(b"PRIVATE KEY", archive.read_bytes())
        with self.assertRaises(SystemExit):
            manager.backup_path(archive)
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        with self.assertRaisesRegex(SystemExit, "Git repository"):
            manager.backup_path(repo / "backup")
        restored = self.root / "restore"
        restored.mkdir(mode=0o700)
        (restored / "gpg-agent.conf").write_text(f"pinentry-program {self.pinentry}\n")
        with mock.patch.dict(os.environ, {"GNUPGHOME": str(restored)}), \
                mock.patch.object(manager, "require_prompt"):
            manager.import_keys(GPG, archive)
            imported = manager.list_keys(GPG)
            self.assertEqual({key["fingerprint"] for key in imported},
                             {key["fingerprint"] for key in keys})
            for key in imported:
                manager.test_key(GPG, key)

    def test_audit_does_not_create_keyring_or_git_configuration(self):
        untouched = self.root / "untouched"
        gitconfig = self.root / "audit-gitconfig"
        env = os.environ.copy()
        env.update({"GNUPGHOME": str(untouched), "GIT_CONFIG_GLOBAL": str(gitconfig)})
        result = subprocess.run(
            [shutil.which("python3"), str(ROOT / "src/manage-gpg-key.py"), "--audit", "--generate"],
            env=env, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(untouched.exists())
        self.assertFalse(gitconfig.exists())

    def test_generate_protects_key_and_remove_requires_confirmation(self):
        with mock.patch.object(manager, "require_prompt"):
            manager.generate(GPG, "Generated Fixture", "generated@example.test")
            key = manager.list_keys(GPG)[0]
            manager.test_key(GPG, key)
            with mock.patch.object(sys, "argv", ["manager", "--cache", "--key", key["fingerprint"]]):
                manager.main()
            manager.set_default(GPG, key, None)
            with mock.patch.object(sys, "argv", ["manager", "--remove", key["fingerprint"]]):
                with self.assertRaisesRegex(SystemExit, "default signing key"):
                    manager.main()
            subprocess.run(["git", "config", "--global", "--unset", "user.signingkey"], check=True)
            with mock.patch.object(sys, "argv", ["manager", "--remove", key["fingerprint"]]), \
                    mock.patch("builtins.input", return_value="not confirmed"):
                with self.assertRaisesRegex(SystemExit, "cancelled"):
                    manager.main()
            self.assertEqual(len(manager.list_keys(GPG)), 1)
            with mock.patch.object(sys, "argv", ["manager", "--remove", key["fingerprint"]]), \
                    mock.patch("builtins.input", return_value=key["fingerprint"]):
                manager.main()
            self.assertEqual(manager.list_keys(GPG), [])

    def test_invalid_backup_reports_import_failure(self):
        broken = self.root / "broken.gpg"
        broken.write_bytes(b"not an encrypted backup")
        with mock.patch.object(manager, "require_prompt"):
            with self.assertRaisesRegex(SystemExit, "inspect the keyring"):
                manager.import_keys(GPG, broken)


if __name__ == "__main__":
    unittest.main()
