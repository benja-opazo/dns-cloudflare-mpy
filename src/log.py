import time


def _ts():
    t = time.localtime()
    return '<{:04d}-{:02d}-{:02d}-{:02d}:{:02d}:{:02d}>'.format(
        t[0], t[1], t[2], t[3], t[4], t[5])


def log(*args):
    print(_ts(), *args)
