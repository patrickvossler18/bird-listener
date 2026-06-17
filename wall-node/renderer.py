"""Compose the e-ink frame from one or more recent birds and dither it to the
Spectra-6 6-color palette.

- 1 bird  -> full-bleed plate with a caption bar (common + scientific + time).
- 2..N    -> a 2-column grid of cells, each a plate + a small common-name strip.

Kept free of hardware dependencies so it runs anywhere (laptop dry-runs).
A "bird" is a dict: {common, scientific, when, plate_path (Path | None)}.
"""
from __future__ import annotations

import json
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


_FONT_WARNED = False


def _font(fonts_dir: Path, size: int) -> ImageFont.ImageFont:
    candidates = [
        fonts_dir / "caption.ttf",                                    # bundled (preferred)
        Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),       # macOS dev box
        Path("/Library/Fonts/Georgia.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),     # Linux (fonts-dejavu)
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                # OSError (bad font) or ImportError (Pillow built without/can't
                # load libfreetype) — try the next candidate, then warn below.
                continue
    # No scalable font anywhere: Pillow's bitmap default ignores `size`, so text
    # renders tiny and unscalable. Warn once so this never hides silently again.
    global _FONT_WARNED
    if not _FONT_WARNED:
        _FONT_WARNED = True
        print("[renderer] WARNING: no scalable TTF font found; using Pillow's "
              "fixed bitmap font (text will be tiny). Bundle one at "
              "wall-node/fonts/caption.ttf or `apt install fonts-dejavu`.")
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


def _fit_font_box(draw, text, fonts_dir, max_width, max_height, min_size=10):
    """Largest font whose *rendered* text fits both max_width and max_height.

    Sizes by the actual glyph bounding box (not the nominal point size), so the
    text fills the available height regardless of the font's internal metrics —
    i.e. as large as possible within a fixed-height caption bar.
    """
    size = max(min_size + 1, int(max_height * 1.7))
    while size > min_size:
        font = _font(fonts_dir, size)
        b = draw.textbbox((0, 0), text, font=font)
        if (b[2] - b[0]) <= max_width and (b[3] - b[1]) <= max_height:
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


# --- Subject-aware cropping -------------------------------------------------
# Precomputed (offline, via tools/compute_crops.py using rembg salient-object
# segmentation) bounding box per plate, so we crop to the bird instead of a
# blind center-crop. crops.json: {"boxes": {"<filename>": [x, y, w, h]}}.
_CROPS_PATH = Path(__file__).resolve().parent / "crops.json"
_CROPS_CACHE: dict | None = None


def _crops() -> dict:
    global _CROPS_CACHE
    if _CROPS_CACHE is None:
        try:
            _CROPS_CACHE = json.loads(_CROPS_PATH.read_text()).get("boxes", {})
        except Exception:
            _CROPS_CACHE = {}
    return _CROPS_CACHE


def _subject_box(plate_path, img: Image.Image):
    """Cached subject box [x, y, w, h] for this plate, clamped to the image, or
    None if there's no cached box (caller falls back)."""
    box = _crops().get(Path(plate_path).name)
    if not box:
        return None
    x, y, w, h = box
    x = max(0, min(int(x), img.width - 1))
    y = max(0, min(int(y), img.height - 1))
    w = max(1, min(int(w), img.width - x))
    h = max(1, min(int(h), img.height - y))
    return (x, y, w, h)


def _expand_to_aspect(box, W, H, target_w, target_h):
    """Grow a subject box outward to the target aspect (never shrink, so the
    subject is never clipped), centered and clamped to the image."""
    x, y, w, h = box
    ar = target_w / target_h
    cx, cy = x + w / 2, y + h / 2
    if w / h < ar:
        w = h * ar
    else:
        h = w / ar
    w, h = min(w, W), min(h, H)
    cx = min(max(cx, w / 2), W - w / 2)
    cy = min(max(cy, h / 2), H - h / 2)
    return (round(cx - w / 2), round(cy - h / 2), round(w), round(h))


def _smart_fill(plate_path, img: Image.Image, w: int, h: int) -> Image.Image:
    """Frame the plate's subject into WxH without distortion.

    Expand the cached subject box to WxH's aspect and crop. If that box reached
    the exact target aspect (the subject was small enough to grow around), resize
    to fill. If it couldn't — a tall/wide subject that hit the image edge — the
    cropped region is off-aspect, so *contain* it (preserve proportions, pad with
    white) rather than stretch it. Falls back to a center cover-crop when no box
    is cached."""
    img = img.convert("RGB")
    box = _subject_box(plate_path, img)
    if box is None:
        return _fit_cover(img, w, h)
    ex, ey, ew, eh = _expand_to_aspect(box, img.width, img.height, w, h)
    crop = img.crop((ex, ey, ex + ew, ey + eh))
    if abs(crop.width / crop.height - w / h) < 0.02:
        return crop.resize((w, h))                       # reached target aspect: fill
    # Off-aspect: contain on white so the whole subject shows, undistorted.
    scale = min(w / crop.width, h / crop.height)
    fitted = crop.resize((max(1, round(crop.width * scale)),
                          max(1, round(crop.height * scale))))
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    return canvas


def _no_plate_panel(width, height, fonts_dir) -> Image.Image:
    panel = Image.new("RGB", (width, height), _CREAM)
    draw = ImageDraw.Draw(panel)
    msg = "No plate"
    font = _font(fonts_dir, max(14, height // 8))
    bbox = draw.textbbox((0, 0), msg, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, (height - (bbox[3] - bbox[1])) // 2),
              msg, fill=(120, 110, 90), font=font)
    return panel


def _compose_single(width, height, bird, fonts_dir, caption_scale=1.0) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    # Single-row name bar (names sit side by side, not stacked), so it can stay
    # short while the text is large. Scales with caption_scale, capped at 1/4.
    caption_h = min(int(max(52, height // 10) * caption_scale), height // 4)
    art_h = height - caption_h

    plate = bird.get("plate_path")
    if plate and Path(plate).exists():
        canvas.paste(_smart_fill(plate, Image.open(plate), width, art_h), (0, 0))
    else:
        canvas.paste(_no_plate_panel(width, art_h, fonts_dir), (0, 0))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, art_h, width, height], fill=(0, 0, 0))

    common = (bird.get("common") or "").strip()
    sci = (bird.get("scientific") or "").strip()
    when = bird.get("when")
    has_common = bool(common) and common.lower() != sci.lower()

    # Line 1 = common name (large). Line 2 = scientific name (+ time). When there
    # is no distinct common name, the scientific name becomes the title and the
    # second line is just the time — so the name is never printed twice.
    title = common if has_common else sci
    if has_common:
        subtitle = f"{sci}   ·   {when}" if when else sci
    else:
        subtitle = str(when) if when else ""

    # Horizontal layout: common name large on the left, scientific name smaller
    # and right-aligned, both vertically centered — uses the panel's width
    # instead of stacking the two lines vertically. Reserve the scientific name's
    # width on the right first so the common name can't overrun it.
    pad, gap = 24, 24
    if subtitle:
        sci_font = _fit_font_box(draw, subtitle, fonts_dir, (width - 2 * pad) * 2 // 5,
                                 caption_h * 50 // 100, min_size=12)
        sci_w = draw.textlength(subtitle, font=sci_font)
    else:
        sci_font, sci_w = None, 0
    name_avail = width - 2 * pad - (sci_w + gap if sci_font else 0)
    # Fill ~84% of the bar height so the name is as large as the bar allows.
    name_font = _fit_font_box(draw, title, fonts_dir, name_avail,
                              caption_h * 84 // 100, min_size=18)

    nb = draw.textbbox((0, 0), title, font=name_font)
    ny = art_h + (caption_h - (nb[3] - nb[1])) // 2 - nb[1]
    draw.text((pad, ny), title, fill=(255, 255, 255), font=name_font)
    if sci_font:
        sb = draw.textbbox((0, 0), subtitle, font=sci_font)
        sy = art_h + (caption_h - (sb[3] - sb[1])) // 2 - sb[1]
        draw.text((width - pad - sci_w, sy), subtitle, fill=(220, 220, 220), font=sci_font)
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


def compose_birds(width, height, birds, fonts_dir, trim=True, caption_scale=1.0) -> Image.Image:
    """Compose 1..N birds into a single RGB frame (caller dithers via to_panel).

    Multiple birds: plates trimmed to their illustration and grouped centered in
    the upper area, with one shared name bar listing all of them along the
    bottom. `trim` toggles the margin crop. `caption_scale` enlarges the
    single-bird name bar.
    """
    birds = list(birds)
    if not birds:
        return Image.new("RGB", (width, height), (255, 255, 255))
    if len(birds) == 1:
        return _compose_single(width, height, birds[0], fonts_dir, caption_scale)

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
                box = _subject_box(plate, im)        # precomputed rembg box
                if box is not None:
                    x, y, w, h = box
                    im = im.convert("RGB").crop((x, y, x + w, y + h))
                else:
                    im = _trim_to_subject(im)         # fallback: density trim
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


def to_panel(frame: Image.Image, *, dither: bool = True, sharpen: float = 0.0,
             rotate: int = 0, clean_bg: bool = True) -> Image.Image:
    """Quantize an RGB frame to the Spectra-6 palette, ready for the panel.

    dither   Floyd-Steinberg dithering (True) or hard nearest-color (False:
             sharper edges but visible color banding).
    sharpen  UnsharpMask amount applied before quantizing (0 = off); crisps up
             detail so the dithered result reads sharper.
    rotate   Rotate the final frame this many degrees (0 or 180) for a panel
             mounted upside-down. 180 is a lossless flip.
    clean_bg Snap the near-white/cream paper to pure white before dithering so
             the background doesn't dither into yellow/red speckle.
    """
    img = frame.convert("RGB")
    if clean_bg:
        # Flood-fill the paper background to pure white from many points along
        # every edge. The background (cream paper + white scan margins) is
        # connected to the borders, so this whitens it uniformly — no cream/white
        # seam — while the saturated/dark bird + foliage stop the fill.
        img = img.copy()
        w, h = img.size
        steps = 9
        seeds = []
        for i in range(steps):
            x, y = w * i // (steps - 1), h * i // (steps - 1)
            seeds += [(min(x, w - 1), 0), (min(x, w - 1), h - 1),
                      (0, min(y, h - 1)), (w - 1, min(y, h - 1))]
        for xy in seeds:
            px = img.getpixel(xy)
            # Only seed from a light background pixel, so we never flood the dark
            # caption bar (or a dark plate edge) into white.
            if sum(px[:3]) >= 3 * 170:
                ImageDraw.floodfill(img, xy, (255, 255, 255), thresh=48)
    if sharpen and sharpen > 0:
        img = img.filter(ImageFilter.UnsharpMask(
            radius=2, percent=int(round(sharpen * 100)), threshold=2))
    out = img.quantize(
        palette=_palette_image(),
        dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE,
    )
    if rotate % 360:
        out = (out.transpose(Image.Transpose.ROTATE_180)
               if rotate % 360 == 180 else out.rotate(-rotate % 360, expand=False))
    return out
