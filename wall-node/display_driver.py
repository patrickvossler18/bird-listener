"""Pluggable e-ink driver.

`get_driver()` returns the real Waveshare 7.3" E6 driver when its library is
importable on the Pi, otherwise a mock driver that writes the frame to a PNG so
the pipeline can be exercised on any machine.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


class DisplayDriver:
    name = "base"

    def show(self, frame: Image.Image) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def sleep(self) -> None:
        """Put the panel into deep sleep (optional; e-ink holds its image)."""


class MockDisplayDriver(DisplayDriver):
    """Writes frames to out/last_frame.png instead of a panel."""

    name = "mock"

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def show(self, frame: Image.Image) -> None:
        path = self.out_dir / "last_frame.png"
        frame.convert("RGB").save(path)
        print(f"[mock-display] wrote {path}")

    def clear(self) -> None:
        path = self.out_dir / "last_frame.png"
        Image.new("RGB", (1, 1), (255, 255, 255)).save(path)
        print("[mock-display] cleared")


class WaveshareE6Driver(DisplayDriver):
    """Real Waveshare 7.3" E6 (Spectra 6) panel via the waveshare_epd library.

    Install on the Pi from Waveshare's e-Paper repo (the `epd7in3e` module).
    """

    name = "waveshare-epd7in3e"

    def __init__(self):
        from waveshare_epd import epd7in3e  # type: ignore

        self._mod = epd7in3e
        self.epd = epd7in3e.EPD()
        self.epd.init()

    def show(self, frame: Image.Image) -> None:
        # The Waveshare buffer expects an image at the panel's native size.
        self.epd.display(self.epd.getbuffer(frame))

    def clear(self) -> None:
        self.epd.Clear()

    def sleep(self) -> None:
        self.epd.sleep()


def get_driver(out_dir: Path, force_mock: bool = False) -> DisplayDriver:
    if force_mock:
        return MockDisplayDriver(out_dir)
    try:
        return WaveshareE6Driver()
    except Exception as exc:  # ImportError on laptop, RuntimeError if no SPI, etc.
        print(f"[display] real panel unavailable ({exc!s}); using mock driver")
        return MockDisplayDriver(out_dir)
