import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGURE = ROOT / "scripts/configure-shell.sh"
INIT = ROOT / "stow/zsh/.config/workspace-setup/zsh-init.zsh"


class ShellConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="shell config ")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), DRY_RUN="0")
        self.env.pop("ZDOTDIR", None)
        self.init = self.home / ".config/workspace-setup/zsh-init.zsh"
        self.init.parent.mkdir(parents=True)
        self.init.symlink_to(INIT)

    def configure(self, *args, success=True):
        result = subprocess.run(["/bin/bash", str(CONFIGURE), *args], env=self.env,
                                text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def test_fresh_and_idempotent(self):
        self.configure()
        rc = self.home / ".zshrc"
        first = rc.read_bytes()
        self.configure()
        self.assertEqual(rc.read_bytes(), first)
        self.assertEqual(first.count(b"# start workspace-setup"), 1)

    def test_preserves_sdkman_and_personal_settings_with_backup(self):
        rc = self.home / ".zshrc"
        original = '# SDKMAN installer\nexport SDKMAN_DIR="$HOME/.sdkman"\n# personal\nalias hi="echo hi"\n'
        rc.write_text(original)
        self.configure()
        self.assertTrue(rc.read_text().startswith(original))
        self.assertEqual(rc.with_name(".zshrc.workspace-setup.bak").read_text(), original)
        self.configure()
        self.assertEqual(rc.with_name(".zshrc.workspace-setup.bak").read_text(), original)

    def test_updates_only_managed_block(self):
        rc = self.home / ".zshrc"
        rc.write_text("# personal\n# start workspace-setup\nold command\n# end workspace-setup\nalias hi='echo hi'\n")
        self.configure()
        self.assertNotIn("old command", rc.read_text())
        self.assertTrue(rc.read_text().endswith("# end workspace-setup\nalias hi='echo hi'\n"))
        self.assertEqual(rc.read_text().count("# start workspace-setup"), 1)

    def test_zdotdir(self):
        zdot = self.home / "custom zsh"
        self.env["ZDOTDIR"] = str(zdot)
        self.configure()
        self.assertTrue((zdot / ".zshrc").exists())
        self.assertFalse((self.home / ".zshrc").exists())

    def test_legacy_repo_link_does_not_modify_repository(self):
        legacy = ROOT / "stow/zsh/.zshrc"
        original = legacy.read_bytes()
        (self.home / ".zshrc").symlink_to(legacy)
        self.configure()
        self.assertEqual(legacy.read_bytes(), original)
        self.assertTrue((self.home / ".zshrc").is_symlink())

    @unittest.skipUnless(shutil.which("zsh"), "zsh required")
    def test_legacy_loader_works_before_new_init_is_linked(self):
        self.init.unlink()
        (self.home / ".zshrc").symlink_to(ROOT / "stow/zsh/.zshrc")
        result = subprocess.run(["zsh", "-ic", 'print -l $path'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.home / ".local/bin"), result.stdout.splitlines())

    @unittest.skipUnless(shutil.which("stow"), "stow required")
    def test_restow_wrapper_with_and_without_legacy_link(self):
        for legacy in (False, True):
            rc = self.home / ".zshrc"
            if rc.exists() or rc.is_symlink():
                rc.unlink()
            if legacy:
                rc.symlink_to(ROOT / "stow/zsh/.zshrc")
            else:
                rc.write_text("# personal\n")
            result = subprocess.run(["/bin/bash", str(ROOT / "stow/scripts/scripts/restow.sh"), "zsh"],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(rc.is_symlink(), legacy)
            self.assertIn("# start workspace-setup", rc.read_text())
            self.env["DRY_RUN"] = "1"
            before = rc.read_bytes()
            result = subprocess.run(["/bin/bash", str(ROOT / "stow/scripts/scripts/restow.sh"), "zsh"],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(rc.read_bytes(), before)
            self.env["DRY_RUN"] = "0"

    def test_other_symlink_preserved(self):
        target = self.home / "personal-rc"
        target.write_text("# personal\n")
        (self.home / ".zshrc").symlink_to(target)
        self.configure()
        self.assertTrue((self.home / ".zshrc").is_symlink())
        self.assertTrue(target.read_text().startswith("# personal\n"))

    def test_malformed_block_preserves_file(self):
        rc = self.home / ".zshrc"
        original = "# start workspace-setup\n# important personal settings\n"
        rc.write_text(original)
        self.configure(success=False)
        self.assertEqual(rc.read_text(), original)

    def test_missing_init_is_incomplete(self):
        self.init.unlink()
        self.assertEqual(self.configure(success=False).returncode, 2)

    def test_dry_run_leaves_home_unchanged(self):
        self.env["DRY_RUN"] = "1"
        before = sorted(str(p) for p in self.home.rglob("*"))
        self.configure()
        self.assertEqual(sorted(str(p) for p in self.home.rglob("*")), before)

    @unittest.skipUnless(shutil.which("zsh"), "zsh required")
    def test_new_login_and_interactive_shell_find_tasks(self):
        bins = self.home / ".local/bin"
        bins.mkdir(parents=True)
        (bins / "tasks").symlink_to(ROOT / "stow/scripts/.local/bin/tasks")
        self.configure()
        for flag in ("-lic", "-ic"):
            result = subprocess.run(["zsh", flag, 'command -v tasks; source "$HOME/.config/workspace-setup/zsh-init.zsh"; print -l $path'],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], str(bins / "tasks"))
            self.assertEqual(result.stdout.splitlines()[1:].count(str(bins)), 1)

    @unittest.skipUnless(shutil.which("stow"), "stow required")
    def test_stow_and_restow_do_not_claim_existing_rc(self):
        rc = self.home / ".zshrc"
        rc.write_text("# personal\n")
        # Let real Stow build the new managed-file link.
        self.init.unlink()
        for args in (("zsh", "scripts"), ("-R", "zsh", "scripts")):
            result = subprocess.run(["stow", "-d", str(ROOT / "stow"), "-t", str(self.home), *args],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(rc.is_symlink())
        self.configure()
        self.assertTrue((self.home / ".local/bin/tasks").exists())
        self.assertTrue(rc.read_text().startswith("# personal\n"))


@unittest.skipUnless(shutil.which("stow"), "stow required")
class BootstrapConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bootstrap config ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.mock_bin = self.base / "mock bin"
        self.mock_bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{self.mock_bin}:{os.environ['PATH']}")
        self.env.pop("ZDOTDIR", None)
        for name in ("bootstrap.sh", "bootstrap-macos.sh"):
            shutil.copy2(ROOT / name, self.repo / name)
        (self.repo / "scripts").mkdir()
        for name in ("configure-shell.sh", "link-configs.sh"):
            shutil.copy2(ROOT / "scripts" / name, self.repo / "scripts" / name)
        (self.repo / "stow").mkdir()
        shutil.copytree(ROOT / "stow/zsh", self.repo / "stow/zsh")
        launchers = self.repo / "stow/scripts/.local/bin"
        launchers.mkdir(parents=True)
        self.executable(launchers / "tasks", "echo tasks\n")
        packages = self.repo / "packages"
        packages.mkdir()
        (packages / "stow-shared.txt").write_text("zsh\nscripts\n")
        self.executable(self.mock_bin / "uname", "echo Darwin\n")
        self.executable(self.mock_bin / "brew", 'if [ "$1" = shellenv ]; then echo ":"; fi\n')
        self.executable(self.repo / "scripts/install-brew-packages.sh", "exit 0\n")
        self.executable(self.repo / "scripts/install-shell-tools.sh", 'echo "# SDKMAN installer" > "$HOME/.zshrc"\nexit 2\n')

    def executable(self, path, content):
        path.write_text("#!/bin/sh\n" + content)
        path.chmod(0o755)

    def bootstrap(self, *args):
        return subprocess.run([str(self.repo / "bootstrap.sh"), *args], input="y\n",
                              env=self.env, capture_output=True, text=True)

    def test_failed_shell_step_still_links_and_configures(self):
        result = self.bootstrap("--yes")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Bootstrap incomplete", result.stdout)
        self.assertTrue((self.home / ".local/bin/tasks").exists())
        self.assertIn("# start workspace-setup", (self.home / ".zshrc").read_text())
        self.assertTrue((self.home / ".zshrc").read_text().startswith("# SDKMAN installer\n"))
        profile = (self.home / ".zprofile").read_text()
        self.assertIn(str(self.mock_bin).replace(" ", "\\ "), profile)
        self.assertEqual(profile.count("# start workspace-setup"), 1)

    def test_link_only_and_rerun(self):
        result = self.bootstrap("--link")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first = (self.home / ".zshrc").read_bytes()
        result = self.bootstrap("--link")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.home / ".zshrc").read_bytes(), first)

    def test_conflicting_launcher_reports_incomplete(self):
        launcher = self.home / ".local/bin/tasks"
        launcher.parent.mkdir(parents=True)
        self.executable(launcher, "echo personal tasks\n")
        result = self.bootstrap("--link")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("tasks", result.stdout)
        self.assertIn("personal tasks", launcher.read_text())

    def test_dry_run_has_no_writes(self):
        self.executable(self.repo / "scripts/install-shell-tools.sh", "exit 0\n")
        result = self.bootstrap("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_shell_only_repairs_existing_managed_config(self):
        self.bootstrap("--link")
        (self.home / ".zshrc").write_text("# personal\n")
        self.executable(self.repo / "scripts/install-shell-tools.sh", "exit 0\n")
        result = self.bootstrap("--shell")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# start workspace-setup", (self.home / ".zshrc").read_text())


if __name__ == "__main__":
    unittest.main()
