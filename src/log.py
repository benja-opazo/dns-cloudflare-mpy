import time


def fmt_datetime(t=None):
    """Format a time tuple (default: current localtime) as 'YYYY-MM-DD HH:MM:SS'.

    Uses str.format() rather than an f-string: zero-padded numeric specs
    ({:04d}) are the one place this project avoids f-strings, since f-string
    format-spec support is unverified on the target MicroPython build. This is
    the single home for that formatting so the rest of the code stays f-string.
    """
    if t is None:
        t = time.localtime()
    return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
        t[0], t[1], t[2], t[3], t[4], t[5])


def _ts():
    t = time.localtime()
    return '<{:04d}-{:02d}-{:02d}-{:02d}:{:02d}:{:02d}>'.format(
        t[0], t[1], t[2], t[3], t[4], t[5])


def log(*args):
    print(_ts(), *args)
