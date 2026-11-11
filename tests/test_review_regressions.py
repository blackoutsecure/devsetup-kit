import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
PWSH = shutil.which("pwsh")


@unittest.skipUnless(BASH and os.name != "nt", "Unix Bash is required")
class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Disposable installer tests require a non-root user")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.root),
            "TMPDIR": str(self.tmp),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "DEVSETUP_ADMIN_MODE": "0",
        })

    def executable(self, name, content):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + content)
        path.chmod(0o755)
        return path

    def run_script(self, path, *args, env=None):
        return subprocess.run(
            [BASH, str(path), *args], env=env or self.env, text=True,
            capture_output=True, timeout=60, check=False,
        )

    def test_gpg_temporary_files_removed_on_failure_and_combined_export_import(self):
        self.executable("git", r"""
if [[ "$*" == "config --global --get user.signingkey" ]]; then echo OLDKEY; exit 0; fi
printf '%s\n' "$*" >> "$HOME/git-calls"
""")
        self.executable("gpg", r"""
case " $* " in
    *" --gen-key "*)
        [[ ! -f "$HOME/fail-generate" ]] || exit 7
        echo '[GNUPG:] KEY_CREATED B AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
        ;;
    *" --export-secret-keys "*) echo secret ;;
    *" --export "*) echo public ;;
    *" --symmetric "*)
        while [[ $# -gt 0 ]]; do
            if [[ "$1" == -o ]]; then shift; printf encrypted > "$1"; exit; fi
            shift
        done
        exit 1 ;;
    *" --decrypt "*)
        while [[ $# -gt 0 ]]; do
            if [[ "$1" == -o ]]; then shift; cp "$HOME/import.tar.gz" "$1"; exit; fi
            shift
        done
        exit 1 ;;
    *" --import "*) [[ ! -f "$HOME/fail-import" ]] ;;
    *) exit 1 ;;
esac
""")
        script = ROOT / "manage-gpg-key.sh"
        (self.root / "fail-generate").touch()
        failed = self.run_script(
            script, "--generate", "--key-name", "Fixture", "--key-email",
            "fixture@example.test", "--key-passphrase", "fixture-secret",
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(list(self.tmp.iterdir()), [])
        (self.root / "fail-generate").unlink()
        generated = self.run_script(
            script, "--generate", "--key-name", "Fixture", "--key-email",
            "fixture@example.test", "--key-passphrase", "fixture-secret",
        )
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        self.assertIn("user.signingkey " + "A" * 40, (self.root / "git-calls").read_text())
        self.assertEqual(list(self.tmp.iterdir()), [])

        bundle = self.root / "bundle"
        bundle.mkdir()
        (bundle / "secret.asc").write_text("fixture")
        (bundle / "README.txt").write_text("Key ID: IMPORTED\n")
        with tarfile.open(self.root / "import.tar.gz", "w:gz") as archive:
            archive.add(bundle / "secret.asc", arcname="secret.asc")
            archive.add(bundle / "README.txt", arcname="README.txt")
        (self.root / "input.gpg").touch()
        combined = self.run_script(
            script, "--export", str(self.root / "output"),
            "--import", str(self.root / "input.gpg"), "--zip-password", "fixture",
        )
        self.assertEqual(combined.returncode, 0, combined.stdout + combined.stderr)
        self.assertEqual(list(self.tmp.iterdir()), [])
        self.assertIn("user.signingkey IMPORTED", (self.root / "git-calls").read_text())
        (self.root / "fail-import").touch()
        failed_import = self.run_script(
            script, "--export", str(self.root / "output"),
            "--import", str(self.root / "input.gpg"), "--zip-password", "fixture",
        )
        self.assertNotEqual(failed_import.returncode, 0)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_prettier_audit_install_and_repeat_preserve_npm_configuration(self):
        self.executable("node", "echo v22.0.0\n")
        self.executable("npm", r"""
if [[ "${1:-}" == --version ]]; then echo 10.0.0; exit; fi
printf '%s\n' "$*" >> "$HOME/npm-calls"
[[ "$*" == "install --global --prefix $HOME/.npm-global prettier@latest" ]]
mkdir -p "$HOME/.npm-global/bin"
printf '#!/bin/sh\necho 3.0.0\n' > "$HOME/.npm-global/bin/prettier"
chmod +x "$HOME/.npm-global/bin/prettier"
""")
        npmrc = self.root / ".npmrc"
        npmrc.write_text("prefix=/existing/user/prefix\n")
        script = ROOT / "src" / "scripts" / "install-prettier.sh"
        audit = self.run_script(script, "--audit")
        self.assertEqual(audit.returncode, 0, audit.stderr)
        self.assertIn("would add", audit.stdout)
        self.assertFalse((self.root / "npm-calls").exists())
        first = self.run_script(script)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(npmrc.read_text(), "prefix=/existing/user/prefix\n")
        profile = self.root / (".zprofile" if os.uname().sysname == "Darwin" else ".profile")
        previous = profile.read_bytes()
        second = self.run_script(script)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertNotIn("[install]", second.stdout)
        self.assertEqual(profile.read_bytes(), previous)
        self.assertEqual(len((self.root / "npm-calls").read_text().splitlines()), 1)
        login = subprocess.run(
            [BASH, "-c", f'. "{profile}"; command -v prettier'],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(login.returncode, 0, login.stderr)
        self.assertEqual(login.stdout.strip(), str(self.root / ".npm-global/bin/prettier"))

    def test_node_install_succeeds_when_upgrade_checks_are_disabled(self):
        kit = self.root / "kit"
        scripts = kit / "src" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(ROOT / "src/scripts/install-node.sh", scripts / "install-node.sh")
        (kit / "src/config.sh").write_text(
            f'. "{ROOT / "src/config.sh"}"\n'
            "devsetup_is_elevated() { return 1; }\n"
            "devsetup_ensure_homebrew() { return 0; }\n"
        )
        self.executable("node", '[[ -f "$HOME/installed" ]] || exit 1\necho v22\n')
        self.executable("npm", '[[ -f "$HOME/installed" ]] || exit 1\necho 10\n')
        self.executable("brew", '[[ "$*" == "install --formula node" ]]\ntouch "$HOME/installed"\n')
        result = self.run_script(scripts / "install-node.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "installed").exists())

    def test_git_helper_uses_exec_path_and_preserves_existing_configuration(self):
        kit = self.root / "kit"
        scripts = kit / "src" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(ROOT / "src/scripts/install-portable-git.sh", scripts / "install-portable-git.sh")
        (kit / "src/config.sh").write_text(
            f'. "{ROOT / "src/config.sh"}"\n'
            "devsetup_is_elevated() { return 1; }\n"
        )
        exec_dir = self.root / "git-exec"
        exec_dir.mkdir()
        (exec_dir / "git-credential-manager").write_text("#!/bin/sh\nexit 0\n")
        (exec_dir / "git-credential-manager").chmod(0o755)
        self.executable("uname", "echo Linux\n")
        self.env["REAL_GIT"] = shutil.which("git")
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.env["GIT_CONFIG_GLOBAL"] = str(self.root / "gitconfig")
        self.executable("git", r"""
if [[ "$*" == --exec-path ]]; then printf '%s/git-exec\n' "$HOME"; exit; fi
exec "$REAL_GIT" "$@"
""")
        script = scripts / "install-portable-git.sh"
        audit = self.run_script(script, "--audit")
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
        self.assertIn("would set credential helper to 'manager'", audit.stdout)
        self.assertFalse((self.root / "gitconfig").exists())
        applied = self.run_script(script)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("credential helper set to 'manager'", applied.stdout)
        second = self.run_script(script)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("credential helper 'manager' already configured", second.stdout)
        subprocess.run(
            [self.env["REAL_GIT"], "config", "--global", "credential.helper", "other"],
            env=self.env, check=True, timeout=30,
        )
        before = (self.root / "gitconfig").read_bytes()
        preserved = self.run_script(script)
        self.assertEqual(preserved.returncode, 0, preserved.stdout + preserved.stderr)
        self.assertIn("existing credential helper preserved", preserved.stdout)
        self.assertEqual((self.root / "gitconfig").read_bytes(), before)
        subprocess.run(
            [self.env["REAL_GIT"], "config", "--global", "credential.helper", ""],
            env=self.env, check=True, timeout=30,
        )
        before = (self.root / "gitconfig").read_bytes()
        disabled = self.run_script(script)
        self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
        self.assertEqual((self.root / "gitconfig").read_bytes(), before)
        (self.root / "gitconfig").write_text("[credential\n")
        invalid = self.run_script(script)
        self.assertNotEqual(invalid.returncode, 0, invalid.stdout + invalid.stderr)

    def test_parent_activates_new_homebrew_and_uninstalls_prettier_first(self):
        kit = self.root / "kit"
        scripts = kit / "src" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(ROOT / "setup.sh", kit / "setup.sh")
        (kit / "src/config.sh").write_text(
            f'. "{ROOT / "src/config.sh"}"\n'
            "devsetup_is_elevated() { return 1; }\n"
            'devsetup_enabled() { [[ "$1" == user.install.homebrew || '
            '"$1" == user.install.node || "$1" == user.install.prettier ]]; }\n'
            'devsetup_homebrew_path() { printf "%s/.linuxbrew/bin/brew\\n" "$HOME"; }\n'
        )
        (scripts / "install-homebrew.sh").write_text(r"""#!/bin/bash
set -eu
if [[ " $* " == *" --uninstall "* ]]; then exit; fi
mkdir -p "$HOME/.linuxbrew/bin"
printf '#!/bin/bash\nprintf "export PATH=\\"%%s/.linuxbrew/bin:\\$PATH\\"\\n" "$HOME"\n' > "$HOME/.linuxbrew/bin/brew"
printf '#!/bin/bash\nexit 0\n' > "$HOME/.linuxbrew/bin/devsetup-fixture-tool"
chmod +x "$HOME/.linuxbrew/bin/brew" "$HOME/.linuxbrew/bin/devsetup-fixture-tool"
""")
        (scripts / "install-node.sh").write_text(r"""#!/bin/bash
set -eu
if [[ " $* " == *" --uninstall "* ]]; then echo node >> "$HOME/order"; exit; fi
command -v devsetup-fixture-tool >/dev/null
""")
        (scripts / "install-prettier.sh").write_text(r"""#!/bin/bash
set -eu
if [[ " $* " == *" --uninstall "* ]]; then echo prettier >> "$HOME/order"; fi
""")
        setup = self.run_script(kit / "setup.sh", "--skip-upgrade-check")
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        uninstall = self.run_script(kit / "setup.sh", "--uninstall", "--audit")
        self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
        self.assertEqual((self.root / "order").read_text().splitlines(), ["prettier", "node"])


@unittest.skipUnless(PWSH and os.name != "nt", "PowerShell on Unix is required")
class PowerShellReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Disposable installer tests require a non-root user")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.root),
            "TMPDIR": str(self.tmp),
            "PATH": f"{self.bin}:" + os.environ["PATH"],
            "DEVSETUP_ADMIN_MODE": "0",
        })

    def executable(self, path, body):
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)

    def run_powershell(self, code):
        return subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command", code],
            env=self.env, text=True, capture_output=True, timeout=120, check=False,
        )

    def test_gpg_batch_cleanup_and_created_fingerprint(self):
        self.executable(self.bin / "git", r"""
case "$*" in
    *"--get gpg.program"*) exit 1 ;;
    *) printf '%s\n' "$*" >> "$HOME/git-calls" ;;
esac
""")
        self.executable(self.bin / "gpg.exe", r"""
case " $* " in
    *" --gen-key "*)
        for arg do batch="$arg"; done
        printf '%s' "$batch" > "$HOME/batch-path"
        [ ! -f "$HOME/fail-generate" ] || exit 7
        echo '[GNUPG:] KEY_CREATED B AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' ;;
    *) exit 1 ;;
esac
""")
        script = str(ROOT / "manage-gpg-key.ps1").replace("'", "''")
        command = (
            "$p = ConvertTo-SecureString 'fixture-secret' -AsPlainText -Force; "
            f"& '{script}' -Generate -KeyName Fixture "
            "-KeyEmail fixture@example.test -KeyPassphrase $p"
        )
        (self.root / "fail-generate").touch()
        failed = self.run_powershell(command)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(Path((self.root / "batch-path").read_text()).exists())
        (self.root / "fail-generate").unlink()
        generated = self.run_powershell(command)
        self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
        self.assertIn("user.signingkey " + "A" * 40, (self.root / "git-calls").read_text())
        self.assertFalse(Path((self.root / "batch-path").read_text()).exists())
        automatic = self.run_powershell(
            f"& '{script}' -Generate -KeyName Fixture -KeyEmail fixture@example.test"
        )
        self.assertEqual(automatic.returncode, 0, automatic.stderr)
        self.assertFalse(Path((self.root / "batch-path").read_text()).exists())

    def test_portable_git_compares_full_windows_version(self):
        portable = self.root / "portable" / "cmd"
        portable.mkdir(parents=True)
        self.executable(portable / "git.exe", r"""
if [ "${1:-}" = "--version" ]; then echo 'git version 2.51.0.windows.1'; exit; fi
exit 1
""")
        script = str(ROOT / "src/scripts/install-portable-git.ps1").replace("'", "''")
        directory = str(portable.parent).replace("'", "''")
        command = (
            "function Invoke-RestMethod { [pscustomobject]@{tag_name='v2.51.0.windows.1'} }; "
            f"& '{script}' -InstallDir '{directory}' -Audit -CheckUpgrades"
        )
        result = self.run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("newer PortableGit available", result.stdout)
        command = command.replace("v2.51.0.windows.1", "v2.51.0.windows.2")
        updated = self.run_powershell(command)
        self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
        self.assertIn("newer PortableGit available: 2.51.0.windows.2", updated.stdout)

    def test_portable_git_preserves_effective_and_disabled_helpers(self):
        kit = self.root / "kit"
        scripts = kit / "src" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(ROOT / "src/scripts/install-portable-git.ps1", scripts / "install-portable-git.ps1")
        original_config = str(ROOT / "src/config.ps1").replace("'", "''")
        (kit / "src/config.ps1").write_text(
            f". '{original_config}'\n"
            "function Add-DevSetupUserPath { param($Path) }\n"
        )
        portable = self.root / "portable" / "cmd"
        portable.mkdir(parents=True)
        self.executable(portable / "git.exe", 'exec "$REAL_GIT" "$@"\n')
        self.env["REAL_GIT"] = shutil.which("git")
        self.env["GIT_CONFIG_GLOBAL"] = str(self.root / "gitconfig")
        self.env["GIT_CONFIG_SYSTEM"] = str(self.root / "system-gitconfig")
        self.env.pop("GIT_CONFIG_NOSYSTEM", None)
        git = self.env["REAL_GIT"]
        system = Path(self.env["GIT_CONFIG_SYSTEM"])
        global_config = Path(self.env["GIT_CONFIG_GLOBAL"])
        subprocess.run([git, "config", "--file", str(system), "credential.helper", "system-custom"],
                       env=self.env, check=True, timeout=30)
        script = str(scripts / "install-portable-git.ps1").replace("'", "''")
        directory = str(portable.parent).replace("'", "''")
        command = f"& '{script}' -InstallDir '{directory}'"
        before_system = system.read_bytes()
        for value in ("custom", ""):
            subprocess.run([git, "config", "--global", "credential.helper", value],
                           env=self.env, check=True, timeout=30)
            before_global = global_config.read_bytes()
            audit = self.run_powershell(command + " -Audit")
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
            self.assertIn("existing credential helper preserved", audit.stdout)
            applied = self.run_powershell(command)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertIn("existing credential helper preserved", applied.stdout)
            self.assertEqual(global_config.read_bytes(), before_global)
            self.assertEqual(system.read_bytes(), before_system)
        global_config.unlink()
        subprocess.run([git, "config", "--file", str(system), "credential.helper", "manager"],
                       env=self.env, check=True, timeout=30)
        before_system = system.read_bytes()
        effective = subprocess.run([git, "config", "--get", "credential.helper"],
                                   env=self.env, text=True, capture_output=True, timeout=30)
        self.assertEqual(effective.stdout.strip(), "manager")
        applied = self.run_powershell(command)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertNotIn("existing credential helper preserved", applied.stdout)
        self.assertEqual(system.read_bytes(), before_system)
        helper = subprocess.run([git, "config", "--global", "--get", "credential.helper"],
                                env=self.env, text=True, capture_output=True, timeout=30)
        self.assertEqual(helper.returncode, 1)
        global_config.unlink()
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        audit = self.run_powershell(command + " -Audit")
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
        self.assertIn("would set credential.helper", audit.stdout)
        self.assertFalse(global_config.exists())
        applied = self.run_powershell(command)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        before_global = global_config.read_bytes()
        second = self.run_powershell(command)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("credential settings already correct", second.stdout)
        self.assertEqual(global_config.read_bytes(), before_global)
        global_config.write_text("[credential\n")
        invalid = self.run_powershell(command + " -Audit")
        self.assertNotEqual(invalid.returncode, 0, invalid.stdout + invalid.stderr)


if __name__ == "__main__":
    unittest.main()
