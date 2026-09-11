"""Per-widget transactions; legacy state is read only on first use."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

CACHE_DIR = Path.home() / '.config/waybar/.cache/widgets'
LEGACY_PATH = CACHE_DIR.parent / 'status-widgets.json'
LEGACY_KEYS = {
    'cpu': ('cpu_prev', 'cpu_history'),
    'memory': ('mem_history',),
    'gpu': ('gpu_history',),
    'network': ('net_prev', 'net_history'),
    'disk': ('disk_prev', 'disk_history'),
    'hyprsunset': ('hyprsunset',),
}


def read_json(path):
    try:
        value = path.read_text()
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def transaction(widget):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f'{widget}.json'
    with (CACHE_DIR / f'{widget}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            state = read_json(path)
        else:
            legacy = read_json(LEGACY_PATH)
            state = {key: legacy[key] for key in LEGACY_KEYS.get(widget, ()) if key in legacy}
        yield state
        fd, temporary = tempfile.mkstemp(prefix=f'.{widget}-', dir=CACHE_DIR)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(state, handle)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
