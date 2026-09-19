import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "stow/scripts/scripts/app-install.sh"
sys.path.insert(0, str(SCRIPT.parent))
from app_install import desktop, management, metadata, registry


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="app install ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "opt"
        self.bins = self.base / "bin"
        self.desktops = self.base / "desktop"
        self.env = dict(
            os.environ,
            INSTALL_ROOT=str(self.root),
            BIN_DIR=str(self.bins),
            DESKTOP_DIR=str(self.desktops),
            DRY_RUN="0",
        )

    def run_install(self, *args, success=True):
        result = subprocess.run(
            [str(SCRIPT), *map(str, args)], env=self.env, capture_output=True, text=True
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def appimage(self, filename="Something-1.AppImage", marker="one"):
        path = self.base / filename
        path.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = --appimage-extract ]; then\n'
            " mkdir -p squashfs-root\n"
            f' echo "{marker}" > squashfs-root/icon.svg\n'
            " exit 0\nfi\n"
            'shift\nprintf "%s\\n" "$@"\n'
        )
        return path

    def archive(self, files=None, name="Something.tar.gz"):
        path = self.base / name
        with tarfile.open(path, "w:gz") as archive:
            for filename, executable in (files or {"package/bin/something": True}).items():
                content = b'#!/bin/sh\nprintf "%s\\n" "$@"\n' if executable else b"<svg/>"
                info = tarfile.TarInfo(filename)
                info.size = len(content)
                info.mode = 0o755 if executable else 0o644
                archive.addfile(info, io.BytesIO(content))
        return path

    def metadata(self, app="something"):
        return json.loads((self.root / "apps" / app / "app-install.json").read_text())

    def test_password_store_persists_across_update_and_edit(self):
        self.run_install(
            self.appimage(), "--name", "Something", "--password-store", "gnome-libsecret"
        )
        wrapper = (self.bins / "something").read_text()
        self.assertIn("--password-store=gnome-libsecret", wrapper)
        self.assertEqual(self.metadata()["password_store"], "gnome-libsecret")
        self.run_install(self.appimage("Something-2.AppImage", "two"), "--name", "Something")
        self.assertIn("--password-store=gnome-libsecret", (self.bins / "something").read_text())
        self.assertEqual(self.metadata()["password_store"], "gnome-libsecret")
        self.run_install(
            self.appimage("Something-3.AppImage", "three"),
            "--name",
            "Something",
            "--password-store",
            "kwallet5",
        )
        self.assertIn("--password-store=kwallet5", (self.bins / "something").read_text())
        self.assertEqual(self.metadata()["password_store"], "kwallet5")
        self.run_install("--edit", "--name", "Something", "--password-store", "gnome-libsecret")
        self.assertIn("--password-store=gnome-libsecret", (self.bins / "something").read_text())
        self.assertEqual(self.metadata()["password_store"], "gnome-libsecret")
        self.run_install("--edit", "--name", "Something", "--password-store", "")
        self.assertNotIn("--password-store=", (self.bins / "something").read_text())
        self.assertNotIn("password_store", self.metadata())
        self.run_install(
            self.appimage(), "--name", "Something", "--password-store", "nope", success=False
        )

    def test_entry_points_from_another_directory(self):
        linked_command = self.base / "app-install"
        linked_command.symlink_to(SCRIPT)
        for command in (
            [str(linked_command)],
            [sys.executable, "-P", "-m", "app_install"],
        ):
            result = subprocess.run(
                [*command, "--help"],
                cwd=self.base,
                env=dict(self.env, PYTHONPATH=str(SCRIPT.parent)),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--rename", result.stdout)
            self.assertIn("--uninstall", result.stdout)

    def test_list_apps(self):
        self.assertIn("No managed", self.run_install("--list").stdout)
        self.assertFalse(self.root.exists())
        self.run_install(self.appimage(), "--name", "Something")
        self.run_install(self.archive(name="Other.tar.gz"), "--name", "Other")
        output = self.run_install("--list").stdout
        for value in ("Something", "Other", "appimage", "tar", "Utility;"):
            self.assertIn(value, output)
        self.assertNotIn("Other", self.run_install("--list", "--name", "Something").stdout)
        self.run_install("--list", "--categories", "Game", success=False)

    def test_edit_metadata_and_update(self):
        source = self.appimage()
        self.run_install(source, "--name", "Something")
        binary = (self.bins / "something").read_bytes()
        payload = (self.root / "apps/something/current").resolve()
        icon = self.metadata()["desktop"]["Icon"]
        self.run_install(
            "--edit",
            "--name",
            "Something",
            "--categories",
            "Development;IDE;IDE",
            "--comment",
            "Useful app",
            "--keywords",
            "editor;code",
            "--terminal",
            "--startup-class",
            "SomethingWindow",
        )
        values = self.metadata()["desktop"]
        self.assertEqual(values["Categories"], "Development;IDE;")
        self.assertEqual(values["Keywords"], "editor;code;")
        self.assertEqual(values["Terminal"], "true")
        self.assertEqual(values["Icon"], icon)
        self.assertEqual((self.bins / "something").read_bytes(), binary)
        self.assertEqual((self.root / "apps/something/current").resolve(), payload)
        self.run_install(source, "--name", "Something")
        self.assertEqual(self.metadata()["desktop"]["Comment"], "Useful app")
        self.assertEqual(self.metadata()["desktop"]["Categories"], "Development;IDE;")
        self.run_install("--edit", "--name", "Something", "--no-terminal", "--categories", "")
        self.assertEqual(self.metadata()["desktop"]["Terminal"], "false")
        self.assertEqual(self.metadata()["desktop"]["Categories"], "")

    def test_edit_dry_run_validation_and_symlink(self):
        self.run_install(self.appimage(), "--name", "Something")
        before = self.metadata()
        self.run_install("--edit", "--name", "Something", "--categories", "Game", "--dry-run")
        self.assertEqual(self.metadata(), before)
        self.run_install("--edit", "--name", "Something", success=False)
        self.run_install("--edit", "--categories", "bad category", success=False)
        self.run_install("--edit", "--name", "Missing", "--categories", "Game", success=False)
        path = self.desktops / "something.desktop"
        original = path.read_text() + "\n[Desktop Action NewWindow]\nName=New window\nExec=custom\n"
        external = self.base / "external.desktop"
        external.write_text(original)
        path.unlink()
        path.symlink_to(external)
        supplied = self.base / "new.svg"
        supplied.write_text("new icon")
        self.run_install(
            "--edit", "--name", "Something", "--icon", supplied, "--categories", "Game"
        )
        self.assertEqual(external.read_text(), original)
        self.assertIn("[Desktop Action NewWindow]", path.read_text())
        self.assertIn("Exec=custom", path.read_text())
        supplied.unlink()
        self.assertEqual(Path(self.metadata()["desktop"]["Icon"]).read_text(), "new icon")

    def test_edit_selector_cancellation(self):
        from argparse import Namespace

        self.run_install(self.appimage(), "--name", "Something")
        before = self.metadata()
        args = Namespace(
            name=None,
            categories="Game",
            startup_class=None,
            comment=None,
            keywords=None,
            terminal=None,
            icon=None,
            password_store=None,
            dry_run=False,
        )
        with patch.object(metadata, "select_app", return_value=None) as select:
            metadata.edit_app(args, self.root, self.bins, self.desktops)
            self.assertEqual(select.call_args.args[1], "edit")
        self.assertEqual(self.metadata(), before)

    def test_appimage_updates_and_icons(self):
        self.run_install(self.appimage(), "--name", "Something")
        icon = Path(self.metadata()["desktop"]["Icon"])
        self.assertEqual(icon.read_text().strip(), "one")
        self.run_install(self.appimage("Something-2.AppImage", "two"), "--name", "Something")
        self.assertEqual(Path(self.metadata()["desktop"]["Icon"]), icon)
        self.assertEqual(Path(self.metadata()["desktop"]["Icon"]).read_text().strip(), "one")
        custom = self.base / "custom.svg"
        custom.write_text("custom")
        self.run_install(self.appimage(), "--name", "Something", "--icon", custom)
        custom.unlink()
        self.assertEqual(Path(self.metadata()["desktop"]["Icon"]).read_text(), "custom")
        result = subprocess.run(
            [str(self.bins / "something"), "a b", "$literal"], capture_output=True, text=True
        )
        self.assertEqual(result.stdout, "a b\n$literal\n")

    def test_default_name_and_dry_run(self):
        app = self.appimage()
        self.run_install(app, "--dry-run")
        self.assertFalse(self.root.exists())
        self.assertFalse(self.bins.exists())
        self.assertFalse(self.desktops.exists())
        self.run_install(app)
        self.assertEqual(self.metadata("something-1")["name"], "Something-1")

    def test_tar_launch_and_failed_update(self):
        self.run_install(self.archive())
        current = self.root / "apps/something/current"
        old = current.resolve()
        result = subprocess.run(
            [str(self.bins / "something"), "a b"], capture_output=True, text=True
        )
        self.assertEqual(result.stdout, "a b\n")
        ambiguous = self.archive({"pkg/first": True, "pkg/second": True}, "update.tar.gz")
        self.assertIn(
            "--exec", self.run_install(ambiguous, "--name", "Something", success=False).stderr
        )
        self.assertEqual(current.resolve(), old)
        self.run_install(ambiguous, "--name", "Something", "--exec", "second")
        self.assertEqual(self.metadata()["executable"], "second")

    def test_unsafe_archives(self):
        for filename in ("../escaped", "/absolute"):
            archive = self.archive({filename: True})
            self.assertIn("Unsafe", self.run_install(archive, success=False).stderr)
        path = self.base / "link.tar"
        with tarfile.open(path, "w") as archive:
            info = tarfile.TarInfo("outside")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            archive.addfile(info)
        self.assertIn("Unsafe", self.run_install(path, success=False).stderr)

    def test_update_selection_and_type(self):
        self.run_install(self.appimage(), "--name", "Something")
        self.run_install(self.archive(name="Other.tar.gz"), "--name", "Other")
        self.run_install(self.appimage(), "--update", success=False)
        self.run_install(self.appimage(), "--update", "--name", "Missing", success=False)
        self.run_install(self.archive(), "--update", "--name", "Something", success=False)
        self.run_install(self.appimage(), "--update", "--name", "Something")
        apps = registry.installations(self.root, self.desktops)
        matching = [app for app in apps if app["type"] == "appimage"]
        self.assertEqual([app["id"] for app in matching], ["something"])
        with (
            patch.object(registry.sys.stdin, "isatty", return_value=True),
            patch.object(registry.sys.stdout, "isatty", return_value=True),
            patch.object(registry.shutil, "which", return_value=None),
            patch("builtins.input", return_value=""),
            patch("builtins.print"),
        ):
            self.assertIsNone(registry.select_app(matching))
        with (
            patch.object(registry.sys.stdin, "isatty", return_value=True),
            patch.object(registry.sys.stdout, "isatty", return_value=True),
            patch.object(registry.shutil, "which", return_value=None),
            patch("builtins.input", return_value="1"),
            patch("builtins.print"),
        ):
            self.assertEqual(registry.select_app(matching)["id"], "something")

    def test_legacy_icon_and_symlinks(self):
        current = self.root / "apps/cursor/current"
        current.mkdir(parents=True)
        (current / "cursor.AppImage").write_text("old")
        icon = current / "old.svg"
        icon.write_text("legacy icon")
        self.desktops.mkdir()
        original = self.base / "tracked.desktop"
        original.write_text(f"[Desktop Entry]\nName=Cursor\nIcon={icon}\nStartupWMClass=Custom\n")
        (self.desktops / "cursor.desktop").symlink_to(original)
        self.bins.mkdir()
        (self.bins / "cursor").symlink_to(self.base / "missing")
        self.run_install(self.appimage(), "--update", "--name", "Cursor")
        self.assertEqual(
            Path(self.metadata("cursor")["desktop"]["Icon"]).read_text(), "legacy icon"
        )
        self.assertEqual(self.metadata("cursor")["desktop"]["StartupWMClass"], "Custom")
        self.assertIn(str(icon), original.read_text())
        self.assertFalse((self.bins / "cursor").is_symlink())
        self.assertFalse((self.desktops / "cursor.desktop").is_symlink())

    def test_ordered_launchers_and_preservation(self):
        tar = self.archive({"pkg/bin/idea.sh": True}, "idea.tar.gz")
        self.run_install(
            tar,
            "--name",
            "IntelliJ IDEA",
            "--id",
            "intellij-idea",
            "--subdir",
            "jetbrains",
            "--exec",
            "bin/idea",
            "--exec",
            "bin/idea.sh",
        )
        self.assertTrue((self.root / "jetbrains/intellij-idea/current/bin/idea.sh").exists())
        self.run_install(self.appimage(), "--name", "Something")
        custom = self.base / "custom-launcher"
        custom.write_text("#!/bin/sh\necho custom\n")
        custom.chmod(0o755)
        (self.bins / "something").unlink()
        (self.bins / "something").symlink_to(custom)
        self.run_install(self.appimage(), "--name", "Something", "--preserve-launcher")
        self.assertTrue((self.bins / "something").is_symlink())
        self.assertEqual(custom.read_text(), "#!/bin/sh\necho custom\n")

    def test_compression_formats(self):
        for suffix, mode in (
            (".tar", "w"),
            (".tgz", "w:gz"),
            (".tar.xz", "w:xz"),
            (".tar.bz2", "w:bz2"),
        ):
            path = self.base / ("format" + suffix)
            with tarfile.open(path, mode) as archive:
                info = tarfile.TarInfo("format")
                content = b"#!/bin/sh\nexit 0\n"
                info.mode, info.size = 0o755, len(content)
                archive.addfile(info, io.BytesIO(content))
            self.run_install(path)
        if registry.shutil.which("zstd"):
            source = self.base / "format.tar"
            target = self.base / "format.tar.zst"
            with target.open("wb") as output:
                subprocess.run(["zstd", "-c", str(source)], stdout=output, check=True)
            self.run_install(target)

    def test_batch_installer_dry_run(self):
        downloads = self.base / "downloads"
        downloads.mkdir()
        result = subprocess.run(
            ["bash", str(SCRIPT.parents[3] / "scripts/install-apps.sh"), "--dry-run"],
            env=dict(self.env, DOWNLOAD_DIR=str(downloads)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.bins.exists())
        self.assertFalse(self.desktops.exists())

    def test_invalid_exec_and_missing_icon(self):
        self.run_install(self.archive(), "--exec", "../outside", success=False)
        self.run_install(self.appimage(), "--icon", self.base / "missing.svg", success=False)
        self.assertFalse((self.root / "apps/something/current").exists())

    def test_desktop_escaping(self):
        value = '/some space/a"b$c`d%e\\f'
        escaped = desktop.desktop_escape(desktop.exec_quote(value))
        self.assertEqual(desktop.desktop_unescape(escaped), desktop.exec_quote(value))
        self.assertIn("%%", escaped)
        self.assertIn("\\\\$", escaped)

    def test_batch_install_integration(self):
        downloads = self.base / "downloads"
        downloads.mkdir()
        self.archive({"pkg/bin/idea.sh": True, "pkg/bin/idea.svg": False}, "idea.tar.gz").rename(
            downloads / "idea.tar.gz"
        )
        self.archive({"pkg/cursor": True}, "cursor.tar.gz").rename(downloads / "cursor.tar.gz")
        self.appimage("archon.AppImage").rename(downloads / "archon.AppImage")
        result = subprocess.run(
            ["bash", str(SCRIPT.parents[3] / "scripts/install-apps.sh"), "--yes"],
            env=dict(self.env, DOWNLOAD_DIR=str(downloads)),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for app in ("intellij-idea", "cursor", "archon"):
            self.assertTrue((self.bins / app).is_file())
            self.assertTrue((self.desktops / (app + ".desktop")).is_file())
        self.assertEqual(self.metadata("cursor")["type"], "tar")

    def test_rename_update_and_uninstall(self):
        source = self.appimage()
        self.run_install(source)
        old_parent = self.root / "apps/something-1"
        old_icon = json.loads((old_parent / "app-install.json").read_text())["desktop"]["Icon"]
        self.run_install("--rename", "Something", "--name", "Something-1")
        self.assertFalse((self.bins / "something-1").exists())
        self.assertFalse((self.desktops / "something-1.desktop").exists())
        self.assertTrue((self.bins / "something").is_file())
        metadata = json.loads((old_parent / "app-install.json").read_text())
        self.assertEqual(metadata["id"], "something")
        self.assertEqual(metadata["desktop"]["Icon"], old_icon)
        result = subprocess.run(
            [str(self.bins / "something"), "hello world"], capture_output=True, text=True
        )
        self.assertEqual(result.stdout, "hello world\n")
        self.run_install(source, success=False)  # Old directory belongs to renamed app.
        self.run_install(self.appimage("Something-2.AppImage"), "--update", "--name", "Something")
        self.run_install("--uninstall", "--name", "Something")
        self.assertFalse(old_parent.exists())
        self.assertFalse((self.bins / "something").exists())
        self.assertFalse((self.desktops / "something.desktop").exists())
        self.assertTrue(source.exists())

    def test_management_dry_run_and_conflicts(self):
        self.run_install(self.appimage(), "--name", "Something")
        before = (self.root / "apps/something/app-install.json").read_text()
        self.run_install("--rename", "Other", "--name", "Something", "--dry-run")
        self.run_install("--remove", "--name", "Something", "--dry-run")
        self.assertEqual((self.root / "apps/something/app-install.json").read_text(), before)
        self.run_install("--rename", "Other", "--name", "Missing", success=False)
        self.run_install("--uninstall", "--name", "Missing", success=False)
        self.run_install("--uninstall", success=False)
        self.run_install("--rename", "Other", success=False)
        self.run_install(self.appimage(), "--remove", "--name", "Something", success=False)
        self.run_install("--rename", "Other", "--remove", success=False)
        (self.bins / "other").symlink_to(self.base / "missing")
        self.run_install("--rename", "Other", "--name", "Something", success=False)
        self.assertEqual((self.root / "apps/something/app-install.json").read_text(), before)

    def test_remove_keeps_external_files_and_unmanaged_apps(self):
        self.run_install(self.appimage(), "--name", "Something")
        external = self.base / "external"
        external.write_text("keep")
        (self.bins / "something").unlink()
        (self.bins / "something").symlink_to(external)
        (self.root / "apps/something/external").symlink_to(self.base, target_is_directory=True)
        unmanaged = self.root / "apps/unmanaged/current"
        unmanaged.mkdir(parents=True)
        apps = registry.installations(self.root, self.desktops)
        self.assertEqual([app["id"] for app in apps], ["something"])
        self.run_install("--remove", "--name", "Something")
        self.assertEqual(external.read_text(), "keep")
        self.assertTrue(unmanaged.exists())

    def test_management_selector(self):
        self.run_install(self.appimage(), "--name", "Something")
        self.run_install(self.archive(name="Other.tar.gz"), "--name", "Other")
        apps = registry.installations(self.root, self.desktops)
        self.assertEqual({app["type"] for app in apps}, {"tar", "appimage"})
        from argparse import Namespace

        args = Namespace(name=None, uninstall=True, rename=None, dry_run=False)
        with patch.object(management, "select_app", return_value=None) as select:
            management.manage_app(args, self.root, self.bins, self.desktops)
            self.assertEqual(len(select.call_args.args[0]), 2)
            self.assertEqual(select.call_args.args[1], "uninstall")
        self.assertTrue((self.root / "apps/something").exists())
        with patch.object(
            management,
            "select_app",
            return_value=next(app for app in apps if app["id"] == "something"),
        ):
            management.manage_app(args, self.root, self.bins, self.desktops)
        self.assertFalse((self.root / "apps/something").exists())
        self.assertTrue((self.root / "apps/other").exists())

    def test_legacy_rename(self):
        current = self.root / "jetbrains/rider/current"
        (current / "bin").mkdir(parents=True)
        binary = current / "bin/rider.sh"
        binary.write_text("#!/bin/sh\necho rider\n")
        binary.chmod(0o755)
        self.run_install("--rename", "My Rider", "--name", "Rider")
        result = subprocess.run([str(self.bins / "my-rider")], capture_output=True, text=True)
        self.assertEqual(result.stdout, "rider\n")
        self.run_install("--remove", "--name", "My Rider")
        self.assertFalse(current.parent.exists())


if __name__ == "__main__":
    unittest.main()
