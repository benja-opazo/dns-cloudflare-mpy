from log import log


def sync_time(wifi):
    """Sync the RTC via NTP. Tries the LAN gateway (router) first, then a public
    NTP host by IP (time.cloudflare.com, so no DNS is required), then pool.ntp.org
    as a DNS-based last resort.
    Returns True on success. Caller must be in client mode with an active link.
    """
    import ntptime
    ntptime.timeout = 5
    for host in (wifi.get_gateway(), '162.159.200.1', 'pool.ntp.org'):
        if not host:
            continue
        ntptime.host = host
        try:
            ntptime.settime()
            log(f'NTP sync OK via {host}')
            return True
        except Exception as e:
            log(f'NTP via {host} failed [{type(e).__name__}]: {e}')
    log('NTP sync failed — all hosts exhausted, clock left unsynced')
    return False
