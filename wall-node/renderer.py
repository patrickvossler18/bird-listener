"""Compose the e-ink frame from one or more recent birds and dither it to the
Spectra-6 6-color palette.

- 1 bird  -> full-bleed plate with a caption bar (common + scientific + time).
- 2..N    -> a 2-column grid of cells, each a plate + a small common-name strip.

Kept free of hardware dependencies so it runs anywhere (laptop dry-runs).
A "bird" is a dict: {common, scientific, when, plate_path (Path | None)}.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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


def _trim_to_subject(img: Image.Image, *, erode: int = 7, density: float = 0.04,
                     pad_frac: float = 0.06, max_cut: float = 0.34) -> Image.Image:
    """Crop a plate's empty cream margin down to the illustration.

    Audubon plates vary: some birds fill the sheet, others sit in a big cream
    field with engraved captions, plate numbers, and a ragged scan edge. We
    build a content mask (saturated *or* dark pixels), erode it to remove thin
    features (the scan-edge frame, caption text, specks), then keep the band of
    rows/columns whose content density clears a threshold. A `max_cut` clamp
    guarantees we never shave more than that fraction off any one side, so a
    full-sheet composition is left essentially intact and we can't over-crop a
    bird. Returns the original if the mask is empty.
    """
    img = img.convert("RGB")
    W, Hh = img.size
    _, S, V = img.convert("HSV").split()
    mask = ImageChops.lighter(S.point(lambda p: 255 if p > 55 else 0),
                              V.point(lambda p: 255 if p < 160 else 0))
    mask = mask.filter(ImageFilter.MinFilter(erode))
    col = list(mask.resize((W, 1), Image.BOX).get_flattened_data())
    row = list(mask.resize((1, Hh), Image.BOX).get_flattened_data())
    cs = [i for i, v in enumerate(col) if v > 255 * density]
    rs = [i for i, v in enumerate(row) if v > 255 * density]
    if not cs or not rs:
        return img
    l, r, t, b = cs[0], cs[-1], rs[0], rs[-1]
    pw, ph = round(pad_frac * W), round(pad_frac * Hh)
    l, t = max(0, l - pw), max(0, t - ph)
    r, b = min(W, r + pw), min(Hh, b + ph)
    # Clamp: never cut more than max_cut off any single side.
    l, t = min(l, int(W * max_cut)), min(t, int(Hh * max_cut))
    r, b = max(r, int(W * (1 - max_cut))), max(b, int(Hh * (1 - max_cut)))
    return img.crop((l, t, r, b))


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


def _draw_name_bar(canvas, x0, y0, w, h, names, fonts_dir) -> None:
    """One shared caption bar listing all bird names, centered, 1–2 lines."""
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x0, y0, x0 + w, y0 + h], fill=(0, 0, 0))
    sep = "   ·   "
    text = sep.join(names)
    max_w = w - 28

    font = _fit_font(draw, text, fonts_dir, max_w, min(30, h * 3 // 5), min_size=12)
    lines = [text]
    if draw.textlength(text, font=font) > max_w:
        mid = (len(names) + 1) // 2  # balance names across two lines
        lines = [sep.join(names[:mid]), sep.join(names[mid:])]
        widest = max(lines, key=len)
        font = _fit_font(draw, widest, fonts_dir, max_w, min(24, h * 2 // 5), min_size=12)

    line_h = font.size + 4
    ty = y0 + (h - line_h * len(lines)) // 2
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text((x0 + (w - lw) // 2, ty), line, fill=(255, 255, 255), font=font)
        ty += line_h


def compose_birds(width, height, birds, fonts_dir, trim=True) -> Image.Image:
    """Compose 1..N birds into a single RGB frame (caller dithers via to_panel).

    Multiple birds: plates trimmed to their illustration and grouped centered in
    the upper area, with one shared name bar listing all of them along the
    bottom. `trim` toggles the margin crop.
    """
    birds = list(birds)
    if not birds:
        return Image.new("RGB", (width, height), (255, 255, 255))
    if len(birds) == 1:
        return _compose_single(width, height, birds[0], fonts_dir)

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    bar_h = max(56, height // 8)
    art_h = height - bar_h
    gap, vpad = 16, 12

    # Open plates and note each one's aspect ratio (default for missing plates).
    plates: list[Image.Image | None] = []
    aspects: list[float] = []
    for bird in birds:
        plate = bird.get("plate_path")
        if plate and Path(plate).exists():
            im = Image.open(plate)
            if trim:
                im = _trim_to_subject(im)
            plates.append(im)
            aspects.append(im.width / im.height)
        else:
            plates.append(None)
            aspects.append(0.7)  # typical tall Audubon-plate aspect

    # Scale every plate to one shared height so they line up; cap that height so
    # the packed row fits the panel width, then center the block both ways.
    n = len(birds)
    avail_w = width - gap * (n - 1) - 2 * vpad
    row_h = int(min(art_h - 2 * vpad, avail_w / max(sum(aspects), 0.01)))
    row_h = max(1, row_h)

    sized = []
    for im, aspect in zip(plates, aspects):
        w_i = max(1, int(row_h * aspect))
        sized.append(im.resize((w_i, row_h)) if im is not None
                     else _no_plate_panel(w_i, row_h, fonts_dir))

    total_w = sum(s.width for s in sized) + gap * (n - 1)
    x = (width - total_w) // 2
    y = (art_h - row_h) // 2
    for s in sized:
        canvas.paste(s, (x, y))
        x += s.width + gap

    names = [b.get("common") or b.get("scientific") or "" for b in birds]
    _draw_name_bar(canvas, 0, art_h, width, bar_h, names, fonts_dir)
    return canvas


def to_panel(frame: Image.Image) -> Image.Image:
    """Quantize an RGB frame to the Spectra-6 palette with Floyd-Steinberg dithering."""
    return frame.convert("RGB").quantize(
        palette=_palette_image(), dither=Image.Dither.FLOYDSTEINBERG
    )
