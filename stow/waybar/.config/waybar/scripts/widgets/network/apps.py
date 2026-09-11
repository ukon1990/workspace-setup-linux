"""Render the privileged collector's snapshot without elevating Waybar."""
import json
from pathlib import Path
import time
from ..formatting import human_bytes, human_rate

SNAPSHOT = Path('/run/waybar-network/usage.json')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')


def app_tooltip(interface):
    try:
        data = json.loads(SNAPSHOT.read_text())
        if data.get('version') != 1 or data.get('boot_id') != BOOT_ID.read_text().strip():
            raise ValueError('Old snapshot')
        apps = list(data['apps'].values())
        started = time.strftime('%H:%M', time.localtime(data['started']))
        fresh = 0 <= time.time() - data['updated'] < 15
        active = fresh and data.get('status') == 'running' and data.get('interface') == interface
        lines = ['', 'Top apps now (download / upload):']
        if active:
            current = sorted(apps, key=lambda a: a['down_rate'] + a['up_rate'], reverse=True)
            current = [a for a in current if a['down_rate'] + a['up_rate'] > 0][:5]
            lines.extend(f'{a["name"]}: ↓ {human_rate(a["down_rate"])}  ↑ {human_rate(a["up_rate"])}' for a in current)
            if not current:
                lines.append('No traffic in the last sample')
        else:
            lines.append('Collecting…' if fresh and data.get('status') == 'collecting' else 'Live monitoring unavailable')
        lines += ['', f'Top apps this boot — tracked since {started}:']
        totals = sorted(apps, key=lambda a: a['received'] + a['sent'], reverse=True)
        totals = [a for a in totals if a['received'] + a['sent'] > 0][:5]
        lines.extend(f'{a["name"]}: ↓ {human_bytes(a["received"])}  ↑ {human_bytes(a["sent"])}' for a in totals)
        if not totals:
            lines.append('No recorded traffic yet')
        lines += ['Approximate TCP/UDP totals on the monitored default interface(s)',
                  'Grouped by executable name; includes system apps and unattributed traffic']
        if data.get('interruptions'):
            lines.append('Monitoring was interrupted; totals may have gaps')
        if not fresh:
            lines.append('Collector stopped or stale; totals are from its last update')
        return lines
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return ['', 'Per-app traffic: monitoring is not active']
