import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PythonPackageSetupTests(unittest.TestCase):
    def test_audit_and_print_path_install_configured_packages_user_locally(self):
        if os.name == "nt":
            self.skipTest("The Bash Python installer is not used on Windows")
        if os.geteuid() == 0:
            self.skipTest("Run the installer test as a non-root user")
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("Bash is unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            package_marker = root / "installed"
            pip_log = root / "pip.log"
            fake_python = bin_dir / "python3"
            fake_python.write_text(
                f"""#!{sys.executable}
import os
import sys
from pathlib import Path

args = sys.argv[1:]
marker = os.environ["FAKE_PYTHON_PACKAGE_MARKER"]
if args == ["--version"]:
    print("Python 3.14.0")
elif args[:3] == ["-m", "pip", "--version"]:
    print("pip 26.0")
elif args[:3] == ["-m", "pip", "show"]:
    sys.exit(0 if os.path.exists(marker) else 1)
elif args[:3] == ["-m", "pip", "install"]:
    with open(os.environ["FAKE_PIP_LOG"], "a", encoding="utf-8") as log:
        log.write(" ".join(args[3:]) + "\\n")
    Path(marker).touch()
elif args[0] == "-c" and "sys.prefix != sys.base_prefix" in args[1]:
    print("False")
elif args[0] == "-c" and "path, key" in args[1]:
    os.execv(os.environ["REAL_PYTHON"], [os.environ["REAL_PYTHON"], *args])
else:
    sys.exit(2)
""",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            config = root / "config.json"
            config.write_text(json.dumps({"user": {"python": {"packages": ["PyYAML"]}}}))
            env = os.environ.copy()
            env.update(
                DEVSETUP_CONFIG_FILE=str(config),
                FAKE_PYTHON_PACKAGE_MARKER=str(package_marker),
                FAKE_PIP_LOG=str(pip_log),
                REAL_PYTHON=sys.executable,
                PATH=str(bin_dir) + os.pathsep + env["PATH"],
                NO_COLOR="1",
            )
            installer = ROOT / "src" / "scripts" / "install-python.sh"

            audit = subprocess.run(
                [bash, str(installer), "--audit"],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
            self.assertIn("Python package PyYAML", audit.stdout)
            self.assertIn("would install via pip --user", audit.stdout)
            self.assertFalse(package_marker.exists())
            self.assertFalse(pip_log.exists())

            apply = subprocess.run(
                [bash, str(installer), "--print-path"],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
            self.assertEqual(apply.stdout.strip(), str(fake_python))
            self.assertIn("--user PyYAML", pip_log.read_text(encoding="utf-8"))
            self.assertTrue(package_marker.exists())

            repeat = subprocess.run(
                [bash, str(installer), "--print-path"],
                env=env, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
            self.assertEqual(repeat.stdout.strip(), str(fake_python))
            self.assertEqual(pip_log.read_text(encoding="utf-8").count("PyYAML"), 1)
            self.assertIn("Python package PyYAML already installed", repeat.stderr)


if __name__ == "__main__":
    unittest.main()
