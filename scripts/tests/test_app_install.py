import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'stow/scripts/scripts/app-install'
loader = importlib.machinery.SourceFileLoader('app_install', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='app install ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'opt'
        self.bins = self.base / 'bin'
        self.desktops = self.base / 'desktop'
        self.env = dict(os.environ, INSTALL_ROOT=str(self.root), BIN_DIR=str(self.bins),
                        DESKTOP_DIR=str(self.desktops), DRY_RUN='0')

    def run_install(self, *args, success=True):
        result = subprocess.run([str(SCRIPT), *map(str, args)], env=self.env,
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def appimage(self, filename='Something-1.AppImage', marker='one'):
        path = self.base / filename
        path.write_text('#!/bin/sh\n'
                        'if [ "$1" = --appimage-extract ]; then\n'
                        ' mkdir -p squashfs-root\n'
                        f' echo "{marker}" > squashfs-root/icon.svg\n'
                        ' exit 0\nfi\n'
                        'shift\nprintf "%s\\n" "$@"\n')
        return path

    def archive(self, files=None, name='Something.tar.gz'):
        path = self.base / name
        with tarfile.open(path, 'w:gz') as archive:
            for filename, executable in (files or {'package/bin/something': True}).items():
                content = b'#!/bin/sh\nprintf "%s\\n" "$@"\n' if executable else b'<svg/>'
                info = tarfile.TarInfo(filename)
                info.size = len(content)
                info.mode = 0o755 if executable else 0o644
                archive.addfile(info, io.BytesIO(content))
        return path

    def metadata(self, app='something'):
        return json.loads((self.root / 'apps' / app / 'app-install.json').read_text())

    def test_appimage_updates_and_icons(self):
        self.run_install(self.appimage(), '--name', 'Something')
        icon = Path(self.metadata()['desktop']['Icon'])
        self.assertEqual(icon.read_text().strip(), 'one')
        self.run_install(self.appimage('Something-2.AppImage', 'two'), '--name', 'Something')
        self.assertEqual(Path(self.metadata()['desktop']['Icon']), icon)
        self.assertEqual(Path(self.metadata()['desktop']['Icon']).read_text().strip(), 'one')
        custom = self.base / 'custom.svg'
        custom.write_text('custom')
        self.run_install(self.appimage(), '--name', 'Something', '--icon', custom)
        custom.unlink()
        self.assertEqual(Path(self.metadata()['desktop']['Icon']).read_text(), 'custom')
        result = subprocess.run([str(self.bins / 'something'), 'a b', '$literal'], capture_output=True, text=True)
        self.assertEqual(result.stdout, 'a b\n$literal\n')

    def test_default_name_and_dry_run(self):
        app = self.appimage()
        self.run_install(app, '--dry-run')
        self.assertFalse(self.root.exists())
        self.assertFalse(self.bins.exists())
        self.assertFalse(self.desktops.exists())
        self.run_install(app)
        self.assertEqual(self.metadata('something-1')['name'], 'Something-1')

    def test_tar_launch_and_failed_update(self):
        self.run_install(self.archive())
        current = self.root / 'apps/something/current'
        old = current.resolve()
        result = subprocess.run([str(self.bins / 'something'), 'a b'], capture_output=True, text=True)
        self.assertEqual(result.stdout, 'a b\n')
        ambiguous = self.archive({'pkg/first': True, 'pkg/second': True}, 'update.tar.gz')
        self.assertIn('--exec', self.run_install(ambiguous, '--name', 'Something', success=False).stderr)
        self.assertEqual(current.resolve(), old)
        self.run_install(ambiguous, '--name', 'Something', '--exec', 'second')
        self.assertEqual(self.metadata()['executable'], 'second')

    def test_unsafe_archives(self):
        for filename in ('../escaped', '/absolute'):
            archive = self.archive({filename: True})
            self.assertIn('Unsafe', self.run_install(archive, success=False).stderr)
        path = self.base / 'link.tar'
        with tarfile.open(path, 'w') as archive:
            info = tarfile.TarInfo('outside')
            info.type = tarfile.SYMTYPE
            info.linkname = '../../outside'
            archive.addfile(info)
        self.assertIn('Unsafe', self.run_install(path, success=False).stderr)

    def test_update_selection_and_type(self):
        self.run_install(self.appimage(), '--name', 'Something')
        self.run_install(self.archive(name='Other.tar.gz'), '--name', 'Other')
        self.run_install(self.appimage(), '--update', success=False)
        self.run_install(self.appimage(), '--update', '--name', 'Missing', success=False)
        self.run_install(self.archive(), '--update', '--name', 'Something', success=False)
        self.run_install(self.appimage(), '--update', '--name', 'Something')
        apps = installer.installations(self.root, self.desktops)
        matching = [app for app in apps if app['type'] == 'appimage']
        self.assertEqual([app['id'] for app in matching], ['something'])
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), \
             patch.object(installer.sys.stdout, 'isatty', return_value=True), \
             patch.object(installer.shutil, 'which', return_value=None), \
             patch('builtins.input', return_value=''), patch('builtins.print'):
            self.assertIsNone(installer.select_app(matching))
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), \
             patch.object(installer.sys.stdout, 'isatty', return_value=True), \
             patch.object(installer.shutil, 'which', return_value=None), \
             patch('builtins.input', return_value='1'), patch('builtins.print'):
            self.assertEqual(installer.select_app(matching)['id'], 'something')

    def test_legacy_icon_and_symlinks(self):
        current = self.root / 'apps/something/current'
        current.mkdir(parents=True)
        (current / 'something.AppImage').write_text('old')
        icon = current / 'old.svg'
        icon.write_text('legacy icon')
        self.desktops.mkdir()
        original = self.base / 'tracked.desktop'
        original.write_text(f'[Desktop Entry]\nName=Something\nIcon={icon}\nStartupWMClass=Custom\n')
        (self.desktops / 'something.desktop').symlink_to(original)
        self.bins.mkdir()
        (self.bins / 'something').symlink_to(self.base / 'missing')
        self.run_install(self.appimage(), '--update', '--name', 'Something')
        self.assertEqual(Path(self.metadata()['desktop']['Icon']).read_text(), 'legacy icon')
        self.assertEqual(self.metadata()['desktop']['StartupWMClass'], 'Custom')
        self.assertIn(str(icon), original.read_text())
        self.assertFalse((self.bins / 'something').is_symlink())
        self.assertFalse((self.desktops / 'something.desktop').is_symlink())

    def test_ordered_launchers_and_preservation(self):
        tar = self.archive({'pkg/bin/idea.sh': True}, 'idea.tar.gz')
        self.run_install(tar, '--name', 'IntelliJ IDEA', '--id', 'intellij-idea', '--subdir', 'jetbrains',
                         '--exec', 'bin/idea', '--exec', 'bin/idea.sh')
        self.assertTrue((self.root / 'jetbrains/intellij-idea/current/bin/idea.sh').exists())
        self.run_install(self.appimage(), '--name', 'Something')
        custom = self.base / 'custom-launcher'
        custom.write_text('#!/bin/sh\necho custom\n')
        custom.chmod(0o755)
        (self.bins / 'something').unlink()
        (self.bins / 'something').symlink_to(custom)
        self.run_install(self.appimage(), '--name', 'Something', '--preserve-launcher')
        self.assertTrue((self.bins / 'something').is_symlink())
        self.assertEqual(custom.read_text(), '#!/bin/sh\necho custom\n')

    def test_compression_formats(self):
        for suffix, mode in (('.tar', 'w'), ('.tgz', 'w:gz'), ('.tar.xz', 'w:xz'), ('.tar.bz2', 'w:bz2')):
            path = self.base / ('format' + suffix)
            with tarfile.open(path, mode) as archive:
                info = tarfile.TarInfo('format')
                content = b'#!/bin/sh\nexit 0\n'
                info.mode, info.size = 0o755, len(content)
                archive.addfile(info, io.BytesIO(content))
            self.run_install(path)
        if installer.shutil.which('zstd'):
            source = self.base / 'format.tar'
            target = self.base / 'format.tar.zst'
            with target.open('wb') as output:
                subprocess.run(['zstd', '-c', str(source)], stdout=output, check=True)
            self.run_install(target)

    def test_batch_installer_dry_run(self):
        downloads = self.base / 'downloads'
        downloads.mkdir()
        result = subprocess.run(['bash', str(SCRIPT.parents[3] / 'scripts/install-apps.sh'), '--dry-run'],
                                env=dict(self.env, DOWNLOAD_DIR=str(downloads)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.root.exists())
        self.assertFalse(self.bins.exists())
        self.assertFalse(self.desktops.exists())

    def test_invalid_exec_and_missing_icon(self):
        self.run_install(self.archive(), '--exec', '../outside', success=False)
        self.run_install(self.appimage(), '--icon', self.base / 'missing.svg', success=False)
        self.assertFalse((self.root / 'apps/something/current').exists())

    def test_desktop_escaping(self):
        value = '/some space/a"b$c`d%e\\f'
        escaped = installer.desktop_escape(installer.exec_quote(value))
        self.assertEqual(installer.desktop_unescape(escaped), installer.exec_quote(value))
        self.assertIn('%%', escaped)
        self.assertIn('\\\\$', escaped)

    def test_batch_install_integration(self):
        downloads = self.base / 'downloads'
        downloads.mkdir()
        self.archive({'pkg/bin/idea.sh': True, 'pkg/bin/idea.svg': False}, 'idea.tar.gz').rename(downloads / 'idea.tar.gz')
        self.archive({'pkg/cursor': True}, 'cursor.tar.gz').rename(downloads / 'cursor.tar.gz')
        self.appimage('archon.AppImage').rename(downloads / 'archon.AppImage')
        result = subprocess.run(['bash', str(SCRIPT.parents[3] / 'scripts/install-apps.sh'), '--yes'],
                                env=dict(self.env, DOWNLOAD_DIR=str(downloads)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for app in ('intellij-idea', 'cursor', 'archon'):
            self.assertTrue((self.bins / app).is_file())
            self.assertTrue((self.desktops / (app + '.desktop')).is_file())
        self.assertEqual(self.metadata('cursor')['type'], 'tar')


if __name__ == '__main__':
    unittest.main()
