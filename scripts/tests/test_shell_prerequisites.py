#!/usr/bin/env python3
"""Offline dependency/preflight tests; no host packages or profiles are changed."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.prefix = self.home / "brew"
        self.log = self.home / "brew.log"
        for name in ("grep", "dirname", "basename"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.write("uname", "printf '%s\\n' Darwin")
        self.write("bash", "exit 1")
        self.write("python3", "exit 1")
        self.write("rbenv", "[[ $1 == commands ]] && echo install; exit 0")
        self.write("brew", r'''case "$1" in
  shellenv) printf 'export PATH=%q:$PATH\n' "$TEST_BIN" ;;
  --prefix) echo "$TEST_PREFIX/$2" ;;
  list) [[ ${INSTALLED:-0} == 1 ]] ;;
  install|upgrade)
    echo "$1 $2" >> "$TEST_LOG"
    [[ ${REPAIR_FAIL:-0} != 1 ]] || exit 1
    mkdir -p "$TEST_PREFIX/$2/bin"
    name="$2"; [[ $name != python ]] || name=python3
    printf '#!/bin/bash\nexit 0\n' > "$TEST_PREFIX/$2/bin/$name"
    chmod +x "$TEST_PREFIX/$2/bin/$name"
    ;;
esac''')
        # Used only by mock Homebrew, never real package installers.
        for name in ("mkdir", "chmod"):
            (self.bin / name).symlink_to(shutil.which(name))

    def write(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
        return path

    def run_preflight(self, **overrides):
        env = os.environ.copy()
        env.pop("BASH_BIN", None)
        env.pop("PYTHON_BIN", None)
        env.update(HOME=str(self.home), PATH=str(self.bin), DRY_RUN="0",
                   TEST_BIN=str(self.bin), TEST_PREFIX=str(self.prefix),
                   TEST_LOG=str(self.log))
        env.update(overrides)
        command = f'''set -eu; source "{ROOT}/scripts/lib/shell-prerequisites.sh"
prepare_shell_prerequisites
printf 'READY %s %s %s\\n' "$BASH_READY" "$PYTHON_READY" "$RUBY_READY"
printf 'BASH %s\\nPYTHON %s\\n' "$BASH_BIN" "$PYTHON_BIN"'''
        return subprocess.run([BASH, "-c", command], env=env, text=True,
                              capture_output=True, check=True).stdout

    def test_old_versions_install_and_use_formula_executables(self):
        result = self.run_preflight()
        self.assertIn("READY 1 1 1", result)
        self.assertIn(f"BASH {self.prefix}/bash/bin/bash", result)
        self.assertIn(f"PYTHON {self.prefix}/python/bin/python3", result)
        self.assertEqual(self.log.read_text(), "install bash\ninstall python\n")

    def test_installed_incompatible_formulas_upgrade(self):
        self.run_preflight(INSTALLED="1")
        self.assertEqual(self.log.read_text(), "upgrade bash\nupgrade python\n")

    def test_compatible_path_does_not_touch_homebrew_formulas(self):
        self.write("bash", "exit 0")
        self.write("python3", "exit 0")
        self.assertIn("READY 1 1 1", self.run_preflight())
        self.assertFalse(self.log.exists())

    def test_explicit_invalid_executables_are_not_replaced(self):
        result = self.run_preflight(BASH_BIN=str(self.bin / "bash"),
                                    PYTHON_BIN=str(self.bin / "python3"))
        self.assertIn("READY 0 0 1", result)
        self.assertIn("Invalid explicit BASH_BIN", result)
        self.assertFalse(self.log.exists())

    def test_repair_failures_leave_dependencies_unavailable(self):
        self.assertIn("READY 0 0 1", self.run_preflight(REPAIR_FAIL="1"))

    def test_dry_run_does_not_install(self):
        result = self.run_preflight(DRY_RUN="1")
        self.assertIn("Would install Homebrew prerequisite: bash", result)
        self.assertIn("READY 1 1 1", result)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.prefix.exists())

    def test_dry_run_plans_missing_rbenv_and_ruby_build(self):
        (self.bin / "rbenv").unlink()
        result = self.run_preflight(DRY_RUN="1")
        self.assertIn("Would install Homebrew prerequisite: rbenv", result)
        self.assertIn("Would install Homebrew prerequisite: ruby-build", result)
        self.assertIn("READY 1 1 1", result)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.prefix.exists())

    def test_missing_ruby_build_skips_only_ruby_on_linux(self):
        self.write("uname", "echo Linux")
        self.write("bash", "exit 0")
        self.write("python3", "exit 0")
        self.write("rbenv", "echo versions")
        self.assertIn("READY 1 1 0", self.run_preflight())
        self.assertFalse(self.log.exists())


class InstallerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "dispatch.log"
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), PATH=f"{self.bin}:/usr/bin:/bin",
                        NVM_DIR=str(self.home / "nvm"),
                        SDKMAN_DIR=str(self.home / "sdkman"),
                        TEST_LOG=str(self.log), DRY_RUN="0")
        self.env.pop("ZDOTDIR", None)
        self.env.pop("PROFILE", None)

    def write(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
        return path

    def dispatch(self, tool):
        return subprocess.run([BASH, str(ROOT / "scripts/install-shell-tools.sh"),
                               "--tool", tool], env=self.env,
                              text=True, capture_output=True)

    def test_sdkman_and_java_use_verified_bash_without_login(self):
        verified = self.write("verified-bash", f'''echo "bash $*" >> "$TEST_LOG"
exec "{BASH}" "$@"''')
        self.env["BASH_BIN"] = str(verified)
        self.write("curl", "echo 'echo installer >> \"$TEST_LOG\"'")
        result = self.dispatch("install_sdkman")
        self.assertEqual(result.returncode, 0, result.stderr)
        init = self.home / "sdkman/bin/sdkman-init.sh"
        init.parent.mkdir(parents=True)
        init.write_text('sdk() { echo "sdk $*" >> "$TEST_LOG"; }\n')
        result = self.dispatch("install_sdkman_java")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.log.read_text()
        self.assertIn("installer", text)
        self.assertIn("bash -c", text)
        self.assertNotIn("bash -lc", text)
        self.assertIn("sdk install java", text)

    def test_tasks_receives_verified_python(self):
        setup = self.write("tasks-setup", 'echo "$PYTHON_BIN" >> "$TEST_LOG"')
        self.env.update(PYTHON_BIN="/verified/python3", TASKS_SETUP_SCRIPT=str(setup))
        result = self.dispatch("install_tasks_runtime")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().strip(), "/verified/python3")

    def test_installers_preserve_repository_owned_zshrc(self):
        (self.home / ".zshrc").symlink_to(ROOT / "stow/zsh/.zshrc")
        self.write("curl", r'''case "$*" in
  *nvm*) echo 'echo "profile $PROFILE" >> "$TEST_LOG"' ;;
  *) echo 'echo "zshdir $ZDOTDIR" >> "$TEST_LOG"' ;;
esac''')
        self.env["BASH_BIN"] = BASH
        for tool in ("install_nvm", "install_sdkman"):
            result = self.dispatch(tool)
            self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines[0], "profile /dev/null")
        directory = Path(lines[1].removeprefix("zshdir "))
        self.assertNotEqual(directory, self.home)
        self.assertFalse(directory.exists(), "temporary SDKMAN profile should be cleaned up")

    def test_dry_run_never_downloads_installers(self):
        self.write("curl", 'echo unexpected >> "$TEST_LOG"; exit 1')
        self.env.update(DRY_RUN="1", BASH_BIN="/missing/bash")
        for tool in ("install_nvm", "install_sdkman", "install_sdkman_java"):
            result = self.dispatch(tool)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())


class MainRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "tools.log"
        nvm = self.home / "nvm/nvm.sh"
        nvm.parent.mkdir()
        nvm.write_text('nvm() { echo "nvm $*" >> "$TEST_LOG"; }\n')
        sdkman = self.home / "sdkman/bin/sdkman-init.sh"
        sdkman.parent.mkdir(parents=True)
        sdkman.write_text('sdk() { echo "sdk $*" >> "$TEST_LOG"; }\n')
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), PATH=f"{self.bin}:/usr/bin:/bin",
                        NVM_DIR=str(nvm.parent), SDKMAN_DIR=str(sdkman.parent.parent),
                        RBENV_ROOT=str(self.home / "rbenv"), TEST_LOG=str(self.log),
                        DRY_RUN="0", BASH_BIN=str(self.bin / "bash"),
                        PYTHON_BIN=str(self.bin / "python3"))
        self.env.pop("ZDOTDIR", None)
        self.env.pop("PROFILE", None)
        self.write("uname", "echo Linux")
        self.write("bash", f'''if [[ $1 == -c && $2 == *BASH_VERSINFO* ]]; then
  exit "${{BASH_INVALID:-0}}"
fi
exec "{BASH}" "$@"''')
        self.write("python3", 'exit "${PYTHON_INVALID:-0}"')
        self.write("rbenv", '''if [[ $1 == commands ]]; then
  echo versions
  [[ ${RUBY_BUILD_MISSING:-0} == 1 ]] || echo install
else
  echo "rbenv $*" >> "$TEST_LOG"
fi''')
        self.write("npm", "exit 0")
        self.write("curl", 'echo unexpected-download >> "$TEST_LOG"; exit 1')
        self.env["TASKS_SETUP_SCRIPT"] = str(self.write("tasks-setup", 'echo tasks-runtime >> "$TEST_LOG"'))

    def write(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
        return path

    def run_main(self, **overrides):
        env = self.env.copy()
        env.update(overrides)
        result = subprocess.run([BASH, str(ROOT / "scripts/install-shell-tools.sh")],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Shell tools setup incomplete", result.stdout)
        self.assertIn("nvm: already available", result.stdout)
        self.assertIn("Node.js and npm globals: installed", result.stdout)
        self.assertNotIn("unexpected-download", self.log.read_text())
        self.assertIn("nvm install", self.log.read_text())
        return result.stdout, self.log.read_text()

    def test_missing_python_skips_tasks_and_continues_other_tools(self):
        output, log = self.run_main(PYTHON_INVALID="1")
        self.assertIn("tasks: skipped (Python 3.12+ unavailable)", output)
        self.assertNotIn("tasks-runtime", log)
        self.assertIn("sdk install java", log)
        self.assertIn("rbenv install", log)

    def test_incompatible_bash_skips_sdkman_java_and_continues_tasks(self):
        output, log = self.run_main(BASH_INVALID="1")
        self.assertIn("SDKMAN: skipped (Bash 4+ unavailable)", output)
        self.assertIn("Java: skipped (Bash 4+ unavailable)", output)
        self.assertNotIn("sdk install java", log)
        self.assertIn("tasks-runtime", log)
        self.assertIn("rbenv install", log)

    def test_missing_ruby_build_skips_ruby_and_continues_tasks(self):
        output, log = self.run_main(RUBY_BUILD_MISSING="1")
        self.assertIn("Ruby: skipped (rbenv or ruby-build unavailable)", output)
        self.assertNotIn("rbenv install", log)
        self.assertIn("tasks-runtime", log)
        self.assertIn("sdk install java", log)


if __name__ == "__main__":
    unittest.main()
