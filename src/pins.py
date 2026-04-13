import machine
import math
import time

# ---------------------------------------------------------------------------
# Pin assignments — edit here to match your board wiring
# ---------------------------------------------------------------------------
PIN_LED = 2   # GPIO2 — built-in LED on most ESP32 dev boards

# ---------------------------------------------------------------------------
# Breathing look-up table  (100 steps × 20 ms = 2 s per cycle)
#
# Uses (1 − cos θ) / 2 so that the curve starts and ends at 0, peaks at 1,
# and has a smooth sinusoidal shape (identical to an "ease-in-out" envelope).
# Pre-computed once at import time.
# ---------------------------------------------------------------------------
_BREATH_STEPS = 100
_BREATH_MS    = 20

_BREATH_LUT = [
    int((1 - math.cos(i * 2 * math.pi / _BREATH_STEPS)) / 2 * 65535)
    for i in range(_BREATH_STEPS)
]


class StatusLed:
    """
    Tick-driven status LED — no timers or interrupts.

    Call tick() from the main loop on every iteration.  With the server's
    poller.poll(20) timeout the loop runs at ~50 Hz, giving smooth breathing
    and accurate blink timing.

    Usage:
        led = StatusLed()
        led.set_ap()          # breathe while in AP config mode
        led.set_connecting()  # fast blink while trying to join Wi-Fi
        led.set_connected()   # solid 3 s then off after a successful join
        led.set_ip_check()    # single blink each time the public IP is read
        led.set_dns_update()  # triple blink each time the DNS record is updated
        led.tick()            # call this every loop iteration
    """

    def __init__(self, pin=PIN_LED):
        self._pwm         = machine.PWM(machine.Pin(pin, machine.Pin.OUT),
                                         freq=1000, duty_u16=0)
        self._mode        = 'off'
        self._step        = 0
        self._blinks_left = 0    # -1 = infinite, 0 = stopped, N = remaining
        self._blink_on    = False
        self._interval_ms = _BREATH_MS
        self._last_ms     = time.ticks_ms()

    # ------------------------------------------------------------------ #
    #  Private                                                            #
    # ------------------------------------------------------------------ #

    def _duty(self, d):
        self._pwm.duty_u16(d)

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def tick(self):
        """Advance the current pattern.  Call on every main-loop iteration."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_ms) < self._interval_ms:
            return
        self._last_ms = now

        if self._mode == 'ap':
            self._duty(_BREATH_LUT[self._step])
            self._step = (self._step + 1) % _BREATH_STEPS

        elif self._mode in ('connecting', 'ip_check', 'dns_update'):
            if self._blinks_left == 0:
                return
            self._blink_on = not self._blink_on
            self._duty(65535 if self._blink_on else 0)
            if not self._blink_on and self._blinks_left > 0:
                self._blinks_left -= 1  # -1 (infinite) is never decremented

        elif self._mode == 'connected':
            # Single interval of 3 s — on expiry, turn off
            self._duty(0)
            self._mode = 'off'

    def set_ap(self):
        """AP config mode: LED breathes once every 2 seconds (PWM sine ramp)."""
        self._step        = 0
        self._interval_ms = _BREATH_MS
        self._last_ms     = time.ticks_ms()
        self._mode        = 'ap'

    def set_connecting(self):
        """Connecting to Wi-Fi: fast blink at 2 Hz (250 ms on / 250 ms off)."""
        self._blinks_left = -1
        self._blink_on    = True
        self._duty(65535)
        self._interval_ms = 250
        self._last_ms     = time.ticks_ms()
        self._mode        = 'connecting'

    def set_connected(self):
        """Just connected: solid on for 3 s, then off."""
        self._duty(65535)
        self._interval_ms = 3000
        self._last_ms     = time.ticks_ms()
        self._mode        = 'connected'

    def set_ip_check(self):
        """Public-IP poll: one blink at 1 Hz (500 ms on, 500 ms off)."""
        self._blinks_left = 1
        self._blink_on    = True
        self._duty(65535)
        self._interval_ms = 500
        self._last_ms     = time.ticks_ms()
        self._mode        = 'ip_check'

    def set_dns_update(self):
        """DNS record updated: three blinks at 1 Hz."""
        self._blinks_left = 3
        self._blink_on    = True
        self._duty(65535)
        self._interval_ms = 500
        self._last_ms     = time.ticks_ms()
        self._mode        = 'dns_update'
