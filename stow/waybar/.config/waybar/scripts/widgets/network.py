import json
import time
from pathlib import Path
from .common import classes, clamp, perf_text, push_history, run, use_compact_perf_text
from .formatting import compact_rate, human_bytes, human_rate


def ip_json(*args):
    result = run(['ip', '-j', *args])
    try:
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []
    except ValueError:
        return []


def default_route():
    routes = ip_json('route', 'show', 'default') or ip_json('-6', 'route', 'show', 'default')
    routes = [r for r in routes if r.get('dev')]
    if routes:
        return min(routes, key=lambda r: r.get('metric', 0))
    # Keep basic traffic metrics available even when ip is unavailable.
    try:
        for line in Path('/proc/net/route').read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == '00000000':
                return {'dev': fields[0]}
    except (OSError, IndexError):
        pass
    return {}


def rates(previous, iface, rx, tx, now):
    if not previous or previous.get('iface') != iface or now <= previous['time']:
        return 0.0, 0.0
    if rx < previous['rx'] or tx < previous['tx']:
        return 0.0, 0.0
    elapsed = now - previous['time']
    return (rx - previous['rx']) / elapsed, (tx - previous['tx']) / elapsed


def network_module(state):
    route = default_route()
    iface = route.get('dev')
    if not iface:
        state.pop('net_prev', None)
        return {'text': '󰖪 off', 'tooltip': 'No active network interface', 'class': classes('metric', 'muted')}
    base = Path('/sys/class/net') / iface
    try:
        rx = int((base / 'statistics/rx_bytes').read_text())
        tx = int((base / 'statistics/tx_bytes').read_text())
    except (OSError, ValueError):
        state.pop('net_prev', None)
        return {'text': '󰖪 off', 'tooltip': f'{iface}: traffic counters unavailable', 'class': classes('metric', 'muted')}
    now = time.monotonic()
    # Legacy timestamps used wall time and must not be mixed with monotonic time.
    previous = state.get('net_prev') if state.get('net_clock') == 'monotonic' else None
    down, up = rates(previous, iface, rx, tx, now)
    state['net_prev'] = {'iface': iface, 'rx': rx, 'tx': tx, 'time': now}
    state['net_clock'] = 'monotonic'
    try:
        status = (base / 'operstate').read_text().strip()
    except OSError:
        status = 'Unavailable'
    addresses = ip_json('address', 'show', 'dev', iface)
    lines = [f'Interface: {iface}', f'State: {status}']
    for family, label in [('inet', 'IPv4'), ('inet6', 'IPv6')]:
        values = [a['local'] for entry in addresses for a in entry.get('addr_info', [])
                  if a.get('family') == family and a.get('local')]
        lines.append(f'{label}: ' + (', '.join(values) or 'Unavailable'))
    lines += [f'Gateway: {route.get("gateway", "Unavailable")}',
              f'Down: {human_rate(down)}', f'Up: {human_rate(up)}',
              f'Received: {human_bytes(rx)}', f'Sent: {human_bytes(tx)}',
              'Totals since interface counters started/reset']
    combined = down + up
    history = push_history(state, 'net_history', clamp(combined / (1024 * 1024 * 2) * 100))
    compact = use_compact_perf_text(state)
    return {'text': perf_text('󰖟', compact_rate(combined).strip(), history, compact),
            'tooltip': '\n'.join(lines), 'class': classes('metric', 'compact' if compact else None)}
