"""Human-readable units shared by metric widgets."""
def human_rate(bytes_per_second):
    if bytes_per_second < 1024:
        return f"{bytes_per_second:.0f}B/s"
    if bytes_per_second < 1024 ** 2:
        return f"{bytes_per_second / 1024:.1f}K/s"
    if bytes_per_second < 1024 ** 3:
        return f"{bytes_per_second / 1024 ** 2:.1f}M/s"
    return f"{bytes_per_second / 1024 ** 3:.1f}G/s"


def compact_rate(bytes_per_second):
    if bytes_per_second < 1024 ** 2:
        return f"{bytes_per_second / 1024:4.0f}K"
    if bytes_per_second < 1024 ** 3:
        return f"{bytes_per_second / 1024 ** 2:4.1f}M"
    return f"{bytes_per_second / 1024 ** 3:4.1f}G"

def human_bytes(value):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
