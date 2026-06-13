"""BH1750 ambient-light reading with on/off hysteresis.

On the Pi it reads lux over I2C via smbus2. Anywhere else (or with
BL_FORCE_MOCK_LIGHT=1) it falls back to a mock that reports a lit room, so the
display stays "on" during laptop dry-runs.
"""
from __future__ import annotations

# BH1750 I2C: default address 0x23 (ADDR low), continuous high-res mode.
_BH1750_ADDR = 0x23
_CONT_HIRES = 0x10  # 1 lx resolution, ~120ms


class LightSensor:
    """Reads lux and applies hysteresis to a boolean 'should the display be on'.

    `lux_off`/`lux_on` define the dead band: turn off below lux_off, turn back
    on above lux_on. Between them, keep the current state (avoids dusk flicker).
    """

    def __init__(self, lux_off: float, lux_on: float, force_mock: bool = False):
        assert lux_on >= lux_off, "lux_on must be >= lux_off"
        self.lux_off = lux_off
        self.lux_on = lux_on
        self._on = True  # assume lit at startup
        self._bus = None
        if not force_mock:
            try:
                import smbus2  # type: ignore

                self._bus = smbus2.SMBus(1)
            except Exception as exc:
                print(f"[light] BH1750 unavailable ({exc!s}); assuming lit room")

    @property
    def is_mock(self) -> bool:
        return self._bus is None

    def read_lux(self) -> float | None:
        if self._bus is None:
            return None
        try:
            data = self._bus.read_i2c_block_data(_BH1750_ADDR, _CONT_HIRES, 2)
            raw = (data[0] << 8) | data[1]
            return raw / 1.2  # datasheet conversion factor
        except Exception as exc:
            print(f"[light] read failed ({exc!s})")
            return None

    def display_should_be_on(self) -> bool:
        """Update and return the hysteresis-filtered on/off decision."""
        lux = self.read_lux()
        if lux is None:  # mock / read error → keep display usable
            self._on = True
            return self._on
        if self._on and lux < self.lux_off:
            self._on = False
        elif not self._on and lux > self.lux_on:
            self._on = True
        return self._on
