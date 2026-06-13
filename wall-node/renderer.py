"""Compose the final e-ink frame: an Audubon plate fitted to the panel with a
small caption bar, quantized/dithered to the Spectra-6 6-color palette.

Kept free of hardware dependencies so it can run anywhere (laptop dry-runs).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Waveshare 7.3" E6 (Spectra 6) palette: black, white, red, yellow, blue, green.
# RGB approximations good enough for Floyd-Steinberg dithering previews.
SPECTRA6_PALETTE = [
    (0, 0, 0),        # black
    (255, 255, 255),  # white
    (255, 0, 0),      # red
    (255, 255, 0),    # yellow
    (0, 0, 255),      # blue
    (0, 255, 0),      # green
]


def _palette_image() -> Image.Image:
    """A 'P'-mode image carrying the Spectra-6 palette for quantize()."""
    pal_img = Image.new("P", (1, 1))
    flat: list[int] = []
    for r, g, b in SPECTRA6_PALETTE:
        flat += [r, g, b]
    flat += [0, 0, 0] * (256 - len(SPECTRA6_PALETTE))  # pad to 256 entries
    pal_img.putpalette(flat)
    return pal_img


def _load_font(fonts_dir: Path, size: int) -> ImageFont.FreeTypeFont:
    """Best-effort font load: bundled font → common system font → PIL default."""
    candidates = [
        fonts_dir / "caption.ttf",
        Path("/Library/Fonts/Georgia.ttf"),
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + center-crop so the image fills WxH without distortion."""
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    new = img.resize((round(img.width * scale), round(img.height * scale)))
    left = (new.width - w) // 2
    top = (new.height - h) // 2
    return new.crop((left, top, left + w, top + h))


def compose(
    *,
    width: int,
    height: int,
    common_name: str,
    scientific_name: str,
    detected_at: str | None,
    plate_path: Path | None,
    fonts_dir: Path,
) -> Image.Image:
    """Build the RGB frame (caller dithers via to_panel)."""
    canvas = Image.new("RGB", (width, height), (255, 255, 255))

    caption_h = max(48, height // 10)
    art_h = height - caption_h

    if plate_path and plate_path.exists():
        art = _fit_cover(Image.open(plate_path), width, art_h)
        canvas.paste(art, (0, 0))
    else:
        # Fallback "card": cream background, no art available.
        draw = ImageDraw.Draw(canvas)
        draw.rectangle([0, 0, width, art_h], fill=(245, 240, 225))
        nf = _load_font(fonts_dir, art_h // 6)
        msg = "No plate available"
        bbox = draw.textbbox((0, 0), msg, font=nf)
        draw.text(
            ((width - (bbox[2] - bbox[0])) // 2, (art_h - (bbox[3] - bbox[1])) // 2),
            msg,
            fill=(120, 110, 90),
            font=nf,
        )

    # Caption bar.
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, art_h, width, height], fill=(0, 0, 0))
    name_font = _load_font(fonts_dir, caption_h * 9 // 20)
    sci_font = _load_font(fonts_dir, caption_h * 5 // 20)

    pad = 16
    draw.text((pad, art_h + caption_h * 2 // 20), common_name,
              fill=(255, 255, 255), font=name_font)
    sci_line = scientific_name
    if detected_at:
        sci_line = f"{scientific_name}   ·   {detected_at}"
    draw.text((pad, art_h + caption_h * 12 // 20), sci_line,
              fill=(220, 220, 220), font=sci_font)

    return canvas


def to_panel(frame: Image.Image) -> Image.Image:
    """Quantize an RGB frame to the Spectra-6 palette with Floyd-Steinberg
    dithering. Returns a 'P'-mode image the Waveshare driver can consume."""
    return frame.convert("RGB").quantize(
        palette=_palette_image(), dither=Image.Dither.FLOYDSTEINBERG
    )
