"""Compose the e-ink frame from one or more recent birds and dither it to the
Spectra-6 6-color palette.

- 1 bird  -> full-bleed plate with a caption bar (common + scientific + time).
- 2..N    -> a 2-column grid of cells, each a plate + a small common-name strip.

Kept free of hardware dependencies so it runs anywhere (laptop dry-runs).
A "bird" is a dict: {common, scientific, when, plate_path (Path | None)}.
"""
from __future__ import annotations

from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Waveshare 7.3" E6 (Spectra 6) palette: black, white, red, yellow, blue, green.
SPECTRA6_PALETTE = [
    (0, 0, 0),        # black
    (255, 255, 255),  # white
    (255, 0, 0),      # red
    (255, 255, 0),    # yellow
    (0, 0, 255),      # blue
    (0, 255, 0),      # green
]

_CREAM = (245, 240, 225)


def _palette_image() -> Image.Image:
    pal_img = Image.new("P", (1, 1))
    flat: list[int] = []
    for r, g, b in SPECTRA6_PALETTE:
        flat += [r, g, b]
    flat += [0, 0, 0] * (256 - len(SPECTRA6_PALETTE))
    pal_img.putpalette(flat)
    return pal_img


def _font(fonts_dir: Path, size: int) -> ImageFont.FreeTypeFont:
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


def _fit_font(draw, text, fonts_dir, max_width, start_size, min_size=10):
    """Largest font (<= start_size) whose text fits max_width, else min_size."""
    size = start_size
    while size > min_size:
        font = _font(fonts_dir, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(fonts_dir, min_size)


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + center-crop so the image fills WxH without distortion."""
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    new = img.resize((round(img.width * scale), round(img.height * scale)))
    left = (new.width - w) // 2
    top = (new.height - h) // 2
    return new.crop((left, top, left + w, top + h))


def _no_plate_panel(width, height, fonts_dir) -> Image.Image:
    panel = Image.new("RGB", (width, height), _CREAM)
    draw = ImageDraw.Draw(panel)
    msg = "No plate"
    font = _font(fonts_dir, max(14, height // 8))
    bbox = draw.textbbox((0, 0), msg, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, (height - (bbox[3] - bbox[1])) // 2),
              msg, fill=(120, 110, 90), font=font)
    return panel


def _compose_single(width, height, bird, fonts_dir) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    caption_h = max(48, height // 10)
    art_h = height - caption_h

    plate = bird.get("plate_path")
    if plate and Path(plate).exists():
        canvas.paste(_fit_cover(Image.open(plate), width, art_h), (0, 0))
    else:
        canvas.paste(_no_plate_panel(width, art_h, fonts_dir), (0, 0))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, art_h, width, height], fill=(0, 0, 0))
    common = bird.get("common") or bird.get("scientific") or ""
    sci = bird.get("scientific") or ""
    when = bird.get("when")
    name_font = _font(fonts_dir, caption_h * 9 // 20)
    sci_font = _font(fonts_dir, caption_h * 5 // 20)
    pad = 16
    draw.text((pad, art_h + caption_h * 2 // 20), common, fill=(255, 255, 255), font=name_font)
    sci_line = f"{sci}   ·   {when}" if when else sci
    draw.text((pad, art_h + caption_h * 12 // 20), sci_line, fill=(220, 220, 220), font=sci_font)
    return canvas


def _compose_cell(width, height, bird, fonts_dir) -> Image.Image:
    """One grid cell: plate on top, thin black common-name strip at the bottom."""
    cell = Image.new("RGB", (width, height), (255, 255, 255))
    strip_h = max(22, height // 6)
    art_h = height - strip_h

    plate = bird.get("plate_path")
    if plate and Path(plate).exists():
        cell.paste(_fit_cover(Image.open(plate), width, art_h), (0, 0))
    else:
        cell.paste(_no_plate_panel(width, art_h, fonts_dir), (0, 0))

    draw = ImageDraw.Draw(cell)
    draw.rectangle([0, art_h, width, height], fill=(0, 0, 0))
    common = bird.get("common") or bird.get("scientific") or ""
    font = _fit_font(draw, common, fonts_dir, width - 16, strip_h * 3 // 5)
    bbox = draw.textbbox((0, 0), common, font=font)
    ty = art_h + (strip_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((8, ty), common, fill=(255, 255, 255), font=font)
    return cell


def compose_birds(width, height, birds, fonts_dir) -> Image.Image:
    """Compose 1..N birds into a single RGB frame (caller dithers via to_panel)."""
    birds = list(birds)
    if not birds:
        return Image.new("RGB", (width, height), (255, 255, 255))
    if len(birds) == 1:
        return _compose_single(width, height, birds[0], fonts_dir)

    cols = 2
    rows = ceil(len(birds) / cols)
    cw = width // cols
    ch = height // rows
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    for i, bird in enumerate(birds):
        r, c = divmod(i, cols)
        canvas.paste(_compose_cell(cw, ch, bird, fonts_dir), (c * cw, r * ch))

    # Thin separators between cells for a clean gallery look.
    draw = ImageDraw.Draw(canvas)
    for c in range(1, cols):
        draw.line([(c * cw, 0), (c * cw, rows * ch)], fill=(0, 0, 0), width=2)
    for r in range(1, rows):
        draw.line([(0, r * ch), (width, r * ch)], fill=(0, 0, 0), width=2)
    return canvas


def to_panel(frame: Image.Image) -> Image.Image:
    """Quantize an RGB frame to the Spectra-6 palette with Floyd-Steinberg dithering."""
    return frame.convert("RGB").quantize(
        palette=_palette_image(), dither=Image.Dither.FLOYDSTEINBERG
    )
