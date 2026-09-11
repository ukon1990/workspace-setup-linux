import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from widgets.network import apps as network_apps, collector


class AccountingTests(unittest.TestCase):
    def test_trace_parse_and_bad_input(self):
        self.assertEqual(collector.parse_row('/opt/my browser/browser/42/1000\t123\t456\n'),
                         (('/opt/my browser/browser', 42, 1000), (123, 456)))
        for line in ['Refreshing:', 'Unknown connection: 1.2.3.4', 'x/1/2\tnan\t3',
                     'x/1/2\t-1\t3', 'x/1/2\tinf\t3']:
            self.assertIsNone(collector.parse_row(line))

    def test_rates_grouping_and_exited_apps(self):
        accounting = collector.Accounting({}, 'boot', 100)
        one, two = ('/usr/bin/browser', 10, 1000), ('/usr/bin/browser', 11, 1000)
        accounting.update({one: (100, 200), two: (50, 100)}, 102)
        app = next(iter(accounting.data['apps'].values()))
        self.assertEqual((app['sent'], app['received']), (150, 300))
        self.assertEqual((app['up_rate'], app['down_rate']), (75, 150))
        accounting.update({one: (200, 400)}, 104)
        self.assertEqual((app['sent'], app['received']), (250, 500))
        accounting.update({}, 106)
        self.assertEqual((app['sent'], app['received']), (250, 500))
        self.assertEqual(app['down_rate'], 0)

    def test_restart_and_counter_reset(self):
        identity = ('/usr/bin/browser', 10, 1000)
        accounting = collector.Accounting({}, 'boot', 100)
        accounting.update({identity: (100, 200)}, 102)
        accounting.update({identity: (10, 20)}, 104)
        app = next(iter(accounting.data['apps'].values()))
        self.assertEqual(app['received'], 220)
        resumed = collector.Accounting(accounting.data, 'boot', 110)
        resumed.update({identity: (1, 2)}, 112)
        self.assertEqual(next(iter(resumed.data['apps'].values()))['received'], 222)
        self.assertEqual(resumed.data['started'], 100)
        self.assertEqual(resumed.data['interruptions'], 1)
        rebooted = collector.Accounting(resumed.data, 'new-boot', 200)
        self.assertEqual(rebooted.data['apps'], {})
        self.assertEqual(rebooted.data['started'], 200)

    def test_unknown_traffic(self):
        accounting = collector.Accounting({}, 'boot', 100)
        accounting.update({('unknown TCP', 0, 0): (10, 50)}, 102)
        self.assertEqual(next(iter(accounting.data['apps'].values()))['name'], 'Unattributed traffic')

    def test_atomic_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'usage.json'
            with patch.object(collector, 'OUTPUT', path):
                collector.publish({'apps': {}}, 'eth0', 'running')
                self.assertEqual(json.loads(path.read_text())['interface'], 'eth0')
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_default_route_selection(self):
        from subprocess import CompletedProcess
        with patch.object(collector.subprocess, 'run', return_value=CompletedProcess([], 0,
                         '[{"dev":"wlan0","metric":600},{"dev":"eth0","metric":100}]')):
            self.assertEqual(collector.default_interface(), 'eth0')

    def test_trace_stream_publishes_complete_frames(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.StringIO(
            'Refreshing:\n/usr/bin/browser/42/1000\t100\t200\n'
            'Refreshing:\n/usr/bin/browser/42/1000\t150\t300\n'
            'Refreshing:\n')
        accounting = collector.Accounting({}, 'boot', 100)
        with patch.object(collector.subprocess, 'Popen', return_value=process), \
             patch.object(collector, 'publish') as publish:
            with self.assertRaisesRegex(RuntimeError, 'NetHogs exited'):
                collector.capture(accounting, 'eth0')
        self.assertEqual(publish.call_count, 3)
        self.assertEqual(next(iter(accounting.data['apps'].values()))['received'], 300)
        process.terminate.assert_called_once()


class TooltipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.snapshot = Path(self.temp.name) / 'usage.json'
        boot = Path(self.temp.name) / 'boot_id'
        boot.write_text('boot')
        for name, value in [('SNAPSHOT', self.snapshot), ('BOOT_ID', boot)]:
            p = patch.object(network_apps, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.data = {'version': 1, 'boot_id': 'boot', 'started': 100,
                     'updated': 198, 'status': 'running', 'interface': 'eth0', 'apps': {
                         'browser': {'name': 'browser', 'sent': 1024, 'received': 4096, 'down_rate': 2048, 'up_rate': 512},
                         'closed': {'name': 'closed app', 'sent': 1024, 'received': 8192, 'down_rate': 0, 'up_rate': 0},
                     }}

    def render(self, interface='eth0'):
        self.snapshot.write_text(json.dumps(self.data))
        with patch.object(network_apps.time, 'time', return_value=200):
            return '\n'.join(network_apps.app_tooltip(interface))

    def test_separate_current_and_boot_rankings(self):
        tooltip = self.render()
        current, totals = tooltip.split('Top apps this boot')
        self.assertIn('browser: ↓ 2.0K/s', current)
        self.assertNotIn('closed app', current)
        self.assertLess(totals.index('closed app'), totals.index('browser'))

    def test_stale_and_wrong_interface_keep_totals(self):
        self.assertIn('Live monitoring unavailable', self.render('wlan0'))
        self.data['updated'] = 100
        tooltip = self.render()
        self.assertIn('Collector stopped or stale', tooltip)
        self.assertNotIn('2.0K/s', tooltip)
        self.assertIn('closed app', tooltip)

    def test_missing_corrupt_and_previous_boot(self):
        self.assertIn('not active', '\n'.join(network_apps.app_tooltip('eth0')))
        self.snapshot.write_text('{broken')
        self.assertIn('not active', '\n'.join(network_apps.app_tooltip('eth0')))
        self.data['boot_id'] = 'old'
        self.assertIn('not active', self.render())

    def test_offline_and_gaps(self):
        self.data.update(status='offline', interface=None, interruptions=1)
        tooltip = self.render(None)
        self.assertIn('Live monitoring unavailable', tooltip)
        self.assertIn('totals may have gaps', tooltip)


if __name__ == '__main__':
    unittest.main()
